#!/usr/bin/env python3
"""Fail closed when a GitOps PR changes image selections without trusted proof."""
import argparse
import json
import tempfile
from pathlib import Path

from delivery_records import record_path, validate_release
from evidence import ROOT, ENVIRONMENTS, SERVICES, EvidenceError, check_history, git, read_json, selected_image, validate_payload, verify_signature


def verify_embedded(envelope, public_key):
    with tempfile.TemporaryDirectory(prefix="boutique-pr-evidence-") as temporary:
        path = Path(temporary) / "envelope.json"
        path.write_text(json.dumps(envelope))
        return verify_signature(path, public_key)


def check_change(base, release_public_key, evidence_public_key, root=ROOT):
    if not base or base.startswith("-"):
        raise EvidenceError("Expected a trusted GitOps base commit")
    base = git(root, "rev-parse", "--verify", base + "^{commit}")
    git(root, "merge-base", "--is-ancestor", base, "HEAD")
    changed = set(git(root, "diff", "--name-only", base, "HEAD").splitlines())
    verified_records = set()
    result = []
    for environment in ENVIRONMENTS:
        for service in SERVICES:
            before = selected_image(root, service, environment, base)
            after = selected_image(root, service, environment, "HEAD")
            if before == after:
                continue
            relative = record_path(service, environment)
            if relative not in changed:
                raise EvidenceError(f"Image change requires a new signed delivery record: {relative}")
            record = json.loads(git(root, "show", f"HEAD:{relative}"))
            if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1 or record.get("service") != service or record.get("environment") != environment or record.get("image") != after:
                raise EvidenceError("Delivery record identity does not match the changed image")
            if record.get("previous_image") != before:
                raise EvidenceError("GitOps base image changed; re-plan and review delivery")
            release = verify_embedded(record.get("release"), release_public_key)
            validate_release(release, service, after)
            mode = record.get("mode")
            if mode == "promote" and environment == "dev":
                if record.get("verification") is not None:
                    raise EvidenceError("Initial dev promotion cannot claim unrelated verification")
            else:
                if mode not in ("promote", "rollback"):
                    raise EvidenceError("Invalid delivery mode")
                source = environment if mode == "rollback" else ("dev" if environment == "staging" else "staging")
                proof = verify_embedded(record.get("verification"), evidence_public_key)
                validate_payload(proof, service, source, after, max_age_hours=720 if mode == "rollback" else 24)
                check_history(root, proof, tip=base)
                if mode == "promote" and selected_image(root, service, source, base) != after:
                    raise EvidenceError("Preceding environment image changed on the PR base")
                if mode == "rollback" and proof["gitops_commit"] == base:
                    raise EvidenceError("Rollback requires an earlier verified deployment")
            verified_records.add(relative)
            result.append({"service": service, "environment": environment, "image": after, "mode": mode})
    for relative in changed:
        if relative.startswith("promotionrecords/") and relative.endswith(".json") and relative not in verified_records:
            raise EvidenceError("Delivery records may change only with their matching image selection")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--release-public-key", required=True)
    parser.add_argument("--evidence-public-key", required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help="PR checkout evaluated by protected-main tools")
    args = parser.parse_args()
    try:
        print(json.dumps({"verified_changes": check_change(args.base, args.release_public_key, args.evidence_public_key, root=args.root)}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "GitOps delivery change rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
