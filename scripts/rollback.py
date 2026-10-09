#!/usr/bin/env python3
"""Prepare a GitOps rollback to a previously verified same-environment digest."""
import argparse
import json

import yaml

from evidence import ROOT, EvidenceError, git, overlay, selected_image, validate_identity, verified_evidence
from delivery_records import write_delivery_record, verified_release
from helm_release import select_release, selected_chart, chart_identity, verified_package


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
    parser.add_argument("--chart-package")
    args = parser.parse_args()
    try:
        validate_identity(args.service, args.target, args.image)
        validate_identity(args.service, args.target, args.current_image)
        if selected_image(ROOT, args.service, args.target) != args.current_image:
            raise EvidenceError("Current environment image changed; re-evaluate the rollback")
        original=verified_release(args.release_record,args.release_public_key,args.service,args.image) if args.release_record else None
        if args.image == args.current_image and (not original or chart_identity(original["chart"])==selected_chart(ROOT,args.service,args.target)):
            raise EvidenceError("Rollback image and chart are already selected")
        payload = verified_evidence(args.evidence, args.public_key, args.service, args.target, args.image, max_age_hours=args.max_age_hours)
        if payload["gitops_commit"] == git(ROOT, "rev-parse", "HEAD"):
            raise EvidenceError("Rollback requires an earlier verified deployment")
        release=verified_release(args.release_record,args.release_public_key,args.service,args.image) if args.release_record else None
        if release and payload.get("chart")!=chart_identity(release["chart"]):
            raise EvidenceError("Rollback chart differs from previous verified deployment")
        if release:
            verified_package(release,args.service,args.chart_package)
        write_delivery_record(args.service, args.target, args.image, "rollback", args.release_record, args.release_public_key, args.evidence)
        select_release(ROOT,args.service,args.target,args.image,release,args.chart_package)
        print(json.dumps({"image": args.image, "previous_image": args.current_image, "environment": args.target, "service": args.service, "verified_build": payload["build_url"]}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Rollback rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
