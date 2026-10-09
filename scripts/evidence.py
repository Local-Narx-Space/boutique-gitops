"""Trusted release evidence shared by verification, promotion and rollback."""
import base64
import datetime as dt
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

SERVICES = ("frontend", "catalogue", "cart", "orders")
ENVIRONMENTS = ("dev", "staging", "production")
SMOKE_CHECKS = {
    "browse", "cart", "validation", "origin", "session_isolation",
    "server_pricing", "checkout", "repeat_idempotency",
    "concurrent_idempotency", "order_ownership", "empty_cart", "deletion",
}
ROOT = Path(__file__).resolve().parents[1]


class EvidenceError(ValueError):
    pass


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError) as error:
        raise EvidenceError("Invalid evidence timestamp") from error
    if result.tzinfo is None or result.utcoffset() != dt.timedelta(0):
        raise EvidenceError("Evidence timestamp must be UTC")
    return result


def validate_identity(service, environment, image):
    if service not in SERVICES or environment not in ENVIRONMENTS:
        raise EvidenceError("Invalid service or environment")
    if not re.fullmatch(rf"ghcr\.io/subhankar12-spec/boutique-{service}@sha256:[a-f0-9]{{64}}", image):
        raise EvidenceError("Expected immutable service image digest")


def read_json(path):
    data = Path(path).read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise EvidenceError("Evidence input exceeds 2 MiB")
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise EvidenceError("Invalid JSON evidence input") from error


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _openssl(arguments):
    result = subprocess.run(["openssl", *arguments], capture_output=True)
    if result.returncode:
        raise EvidenceError("Evidence key or signature validation failed")
    return result.stdout


def key_id(path, private=False):
    arguments = ["pkey", "-in", str(path), "-pubout", "-outform", "DER"]
    if not private:
        arguments.insert(1, "-pubin")
    der = _openssl(arguments)
    if len(der) != 44 or not der.startswith(bytes.fromhex("302a300506032b6570032100")):
        raise EvidenceError("Evidence keys must use Ed25519")
    return hashlib.sha256(der).hexdigest()


def sign(payload, signing_key, output):
    identifier = key_id(signing_key, private=True)
    with tempfile.TemporaryDirectory(prefix="boutique-evidence-") as temporary:
        message = Path(temporary) / "payload.json"
        message.write_bytes(canonical(payload))
        signature = _openssl(["pkeyutl", "-sign", "-rawin", "-inkey", str(signing_key), "-in", str(message)])
    envelope = {
        "algorithm": "Ed25519", "key_id": identifier, "payload": payload,
        "signature": base64.b64encode(signature).decode(),
    }
    Path(output).write_text(json.dumps(envelope, indent=2) + "\n")


def verify_signature(path, public_key):
    envelope = read_json(path)
    if not isinstance(envelope, dict) or set(envelope) != {"algorithm", "key_id", "payload", "signature"}:
        raise EvidenceError("Invalid signed evidence envelope")
    if envelope["algorithm"] != "Ed25519" or envelope["key_id"] != key_id(public_key):
        raise EvidenceError("Evidence was not signed by the trusted verification key")
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
    except (ValueError, TypeError) as error:
        raise EvidenceError("Invalid evidence signature") from error
    if len(signature) != 64:
        raise EvidenceError("Invalid Ed25519 signature length")
    with tempfile.TemporaryDirectory(prefix="boutique-evidence-") as temporary:
        message, detached = Path(temporary) / "payload.json", Path(temporary) / "signature.bin"
        message.write_bytes(canonical(envelope["payload"]))
        detached.write_bytes(signature)
        _openssl(["pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key), "-in", str(message), "-sigfile", str(detached)])
    return envelope["payload"]


def git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True)
    if result.returncode:
        raise EvidenceError("Evidence GitOps commit is unavailable or not in trusted history")
    return result.stdout.strip()


def overlay(service, environment):
    return f"environments/{environment}/releases.yaml"


def selected_image(root, service, environment, commit=None):
    from helm_release import load, values_path
    data=load(root,values_path(environment),commit)
    if not isinstance(data,dict) or set(data)!=set(SERVICES):
        raise EvidenceError("Helm release values require exactly the four services")
    for name, configuration in data.items():
        if not isinstance(configuration,dict) or set(configuration)!={"image"}:
            raise EvidenceError("Release values can change only service image selections")
        image=configuration["image"]
        if not isinstance(image,dict) or set(image)!={"repository","digest","tag"}:
            raise EvidenceError("Invalid Helm image selection")
    image=data[service]["image"]
    if image["digest"]:
        if image["tag"]:raise EvidenceError("An immutable image selection cannot also specify a tag")
        return image["repository"]+"@"+image["digest"]
    return image["repository"]+":"+image["tag"]


def check_history(root, payload, tip="HEAD"):
    commit = payload.get("gitops_commit", "")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise EvidenceError("Evidence must contain a full GitOps commit SHA")
    git(root, "merge-base", "--is-ancestor", commit, tip)
    from helm_release import selected_chart
    if payload.get("chart") != selected_chart(root,payload["service"],payload["environment"],commit):
        raise EvidenceError("Evidence chart does not match its recorded GitOps commit")
    if selected_image(root, payload["service"], payload["environment"], commit) != payload["image"]:
        raise EvidenceError("Evidence image does not match its recorded GitOps commit")


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise EvidenceError(f"Invalid measured {name}")
    return value


def validate_payload(payload, service, environment, image, max_age_hours=24, now=None):
    validate_identity(service, environment, image)
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 2:
        raise EvidenceError("Unsupported release evidence schema")
    for key, expected in (("service", service), ("environment", environment), ("image", image)):
        if payload.get(key) != expected:
            raise EvidenceError(f"Evidence {key} does not match the requested release")
    if not 0 < max_age_hours <= 720:
        raise EvidenceError("Evidence freshness must be between zero and 720 hours")
    now = now or utcnow()
    verified = timestamp(payload.get("verified_at"))
    if verified > now + dt.timedelta(seconds=60) or now - verified > dt.timedelta(hours=max_age_hours):
        raise EvidenceError("Verification evidence is stale or dated in the future")
    chart=payload.get("chart")
    if not isinstance(chart,dict) or set(chart)!={"name","repository","version","package_sha256"}:
        raise EvidenceError("Measured Helm chart selection is required")
    deployment = payload.get("deployment", {})
    if deployment.get("image") != image:
        raise EvidenceError("Measured deployment image does not match the requested release")
    desired = _integer(deployment.get("desired_replicas"), "desired replicas", 1)
    generation = _integer(deployment.get("generation"), "generation", 1)
    observed = _integer(deployment.get("observed_generation"), "observed generation", 1)
    if observed < generation:
        raise EvidenceError("Deployment controller has not observed this generation")
    for name in ("updated_replicas", "ready_replicas", "available_replicas"):
        if _integer(deployment.get(name), name) != desired:
            raise EvidenceError("Deployment rollout did not complete successfully")
    if deployment.get("available") is not True or deployment.get("progressing") is not True:
        raise EvidenceError("Deployment health conditions are not successful")
    runtime = payload.get("runtime", {})
    if _integer(runtime.get("ready_pods"), "ready pods") != desired:
        raise EvidenceError("Runtime pod count does not match the completed rollout")
    image_ids = runtime.get("image_ids", [])
    digest = image.rsplit("@", 1)[1]
    if not image_ids or any(not isinstance(value, str) or value.rsplit("@", 1)[-1] != digest for value in image_ids):
        raise EvidenceError("Runtime container image IDs do not match the requested digest")
    argo = payload.get("argocd", {})
    if argo.get("revision") != payload.get("gitops_commit") or argo.get("sync_status") != "Synced" or argo.get("health_status") != "Healthy":
        raise EvidenceError("Argo CD did not synchronize the verified GitOps commit successfully")
    smoke = payload.get("smoke", {})
    if smoke.get("success") is not True or smoke.get("environment") != environment or set(smoke.get("checks", [])) != SMOKE_CHECKS:
        raise EvidenceError("Required functional smoke checks did not pass")
    started, completed = timestamp(smoke.get("started_at")), timestamp(smoke.get("completed_at"))
    if completed < started or completed - started > dt.timedelta(minutes=15) or completed > verified or verified - completed > dt.timedelta(minutes=10):
        raise EvidenceError("Smoke tests are not contemporaneous with deployment verification")
    origin = urlsplit(smoke.get("origin", ""))
    if origin.username or origin.password or origin.query or origin.fragment or origin.path not in ("", "/"):
        raise EvidenceError("Invalid verified application origin")
    if not origin.hostname or (origin.scheme != "https" and not (origin.scheme == "http" and origin.hostname in ("localhost", "127.0.0.1", "::1"))):
        raise EvidenceError("Smoke origin requires HTTPS or a loopback lab endpoint")
    if not isinstance(payload.get("build_url"), str) or not payload["build_url"].startswith(("https://", "http://")):
        raise EvidenceError("Missing verification build provenance")
    return payload


def verified_evidence(path, public_key, service, environment, image, root=ROOT, max_age_hours=24):
    payload = verify_signature(path, public_key)
    validate_payload(payload, service, environment, image, max_age_hours)
    check_history(root, payload)
    return payload
