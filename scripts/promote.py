#!/usr/bin/env python3
"""Select a digest; staging/production require signed preceding-env evidence."""
import argparse
import json

import yaml

from evidence import ROOT, EvidenceError, overlay, selected_image, validate_identity, verified_evidence
from delivery_records import write_delivery_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service")
    parser.add_argument("target")
    parser.add_argument("image")
    parser.add_argument("--evidence")
    parser.add_argument("--public-key")
    parser.add_argument("--max-age-hours", type=float, default=24)
    parser.add_argument("--release-record")
    parser.add_argument("--release-public-key")
    args = parser.parse_args()
    try:
        validate_identity(args.service, args.target, args.image)
        if args.target != "dev":
            source = "dev" if args.target == "staging" else "staging"
            if selected_image(ROOT, args.service, source) != args.image:
                raise EvidenceError("Image must already be selected in " + source)
            if not args.evidence or not args.public_key:
                raise EvidenceError("Signed successful " + source + " verification evidence and trusted public key are required")
            verified_evidence(args.evidence, args.public_key, args.service, source, args.image, max_age_hours=args.max_age_hours)
        write_delivery_record(args.service, args.target, args.image, "promote", args.release_record, args.release_public_key, args.evidence if args.target != "dev" else None)
        path = ROOT / overlay(args.service, args.target)
        data = yaml.safe_load(path.read_text())
        images = [entry for entry in data["images"] if entry["name"] == args.image.split("@")[0]]
        if len(images) != 1:
            raise EvidenceError("Expected exactly one service image entry")
        images[0].pop("newTag", None)
        images[0]["digest"] = args.image.split("@")[1]
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        print(json.dumps({"image": args.image, "environment": args.target, "service": args.service}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Promotion rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
