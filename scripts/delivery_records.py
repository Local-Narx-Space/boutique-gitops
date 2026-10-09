"""Signed release attestations and reviewable GitOps delivery records."""
import json
import re
from pathlib import Path

from evidence import EvidenceError, ROOT, read_json, selected_image, verify_signature


def validate_release(payload, service, image):
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 2:
        raise EvidenceError("Unsupported release attestation schema")
    if service not in ("frontend", "catalogue", "cart", "orders", "incident-bridge"):
        raise EvidenceError("Invalid attested service")
    if not re.fullmatch(rf"ghcr\.io/subhankar12-spec/boutique-{service}@sha256:[a-f0-9]{{64}}", image):
        raise EvidenceError("Expected immutable attested service image")
    if payload.get("service") != service or payload.get("image") != image:
        raise EvidenceError("Release attestation identity mismatch")
    if payload.get("tests_passed") is not True or payload.get("security_gate_passed") is not True:
        raise EvidenceError("Release quality gates did not pass")
    if not re.fullmatch(r"[a-f0-9]{40}", payload.get("source_commit", "")):
        raise EvidenceError("Release attestation requires a full source commit")
    for key in ("sbom_sha256", "scan_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", payload.get(key, "")):
            raise EvidenceError("Release attestation requires report checksums")
    if not isinstance(payload.get("build_url"), str) or not payload["build_url"].startswith(("http://", "https://")):
        raise EvidenceError("Release attestation requires trusted build provenance")
    if service != "incident-bridge":
        from helm_release import validate_chart
        validate_chart(payload.get("chart"),service,payload["source_commit"])
    return payload


def verified_release(path, public_key, service, image):
    return validate_release(verify_signature(path, public_key), service, image)


def record_path(service, environment):
    return f"promotionrecords/{environment}/{service}.json"


def write_delivery_record(service, environment, image, mode, release_record, release_public_key, verification_record=None, root=ROOT):
    if bool(release_record) != bool(release_public_key):
        raise EvidenceError("Release attestation and its trusted public key must be supplied together")
    if not release_record:
        return
    verified_release(release_record, release_public_key, service, image)
    record = {
        "schema_version": 2, "mode": mode, "service": service,
        "environment": environment, "image": image,
        "previous_image": selected_image(root, service, environment),
        "previous_chart": __import__("helm_release").selected_chart(root,service,environment),
        "release": read_json(release_record),
        "verification": read_json(verification_record) if verification_record else None,
    }
    path = Path(root) / record_path(service, environment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
