#!/usr/bin/env python3
"""Prepare a GitOps rollback to a previously verified same-environment digest."""
import argparse
import json

import yaml

from evidence import ROOT, EvidenceError, git, overlay, selected_image, validate_identity, verified_evidence
from delivery_records import write_delivery_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service")
    parser.add_argument("target")
    parser.add_argument("image")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--current-image", required=True, help="Expected currently selected digest; prevents a stale rollback")
    parser.add_argument("--max-age-hours", type=float, default=720)
    parser.add_argument("--release-record")
    parser.add_argument("--release-public-key")
    args = parser.parse_args()
    try:
        validate_identity(args.service, args.target, args.image)
        validate_identity(args.service, args.target, args.current_image)
        if selected_image(ROOT, args.service, args.target) != args.current_image:
            raise EvidenceError("Current environment image changed; re-evaluate the rollback")
        if args.image == args.current_image:
            raise EvidenceError("Rollback image is already selected")
        payload = verified_evidence(args.evidence, args.public_key, args.service, args.target, args.image, max_age_hours=args.max_age_hours)
        if payload["gitops_commit"] == git(ROOT, "rev-parse", "HEAD"):
            raise EvidenceError("Rollback requires an earlier verified deployment")
        write_delivery_record(args.service, args.target, args.image, "rollback", args.release_record, args.release_public_key, args.evidence)
        path = ROOT / overlay(args.service, args.target)
        data = yaml.safe_load(path.read_text())
        images = [entry for entry in data["images"] if entry["name"] == args.image.split("@")[0]]
        if len(images) != 1:
            raise EvidenceError("Expected exactly one service image entry")
        images[0].pop("newTag", None)
        images[0]["digest"] = args.image.split("@")[1]
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        print(json.dumps({"image": args.image, "previous_image": args.current_image, "environment": args.target, "service": args.service, "verified_build": payload["build_url"]}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Rollback rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
