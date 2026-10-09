#!/usr/bin/env python3
"""Select a digest; staging/production require signed preceding-env evidence."""
import argparse
import json

import yaml

from evidence import ROOT, EvidenceError, overlay, selected_image, validate_identity, verified_evidence
from delivery_records import write_delivery_record, verified_release
from helm_release import select_release, selected_chart, chart_identity, verified_package


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
    parser.add_argument("--chart-package")
    args = parser.parse_args()
    try:
        validate_identity(args.service, args.target, args.image)
        if args.target != "dev":
            source = "dev" if args.target == "staging" else "staging"
            if selected_image(ROOT, args.service, source) != args.image:
                raise EvidenceError("Image must already be selected in " + source)
            if not args.evidence or not args.public_key:
                raise EvidenceError("Signed successful " + source + " verification evidence and trusted public key are required")
            proof=verified_evidence(args.evidence, args.public_key, args.service, source, args.image, max_age_hours=args.max_age_hours)
            if args.release_record:
                release=verified_release(args.release_record,args.release_public_key,args.service,args.image)
                if proof.get("chart")!=chart_identity(release["chart"]) or selected_chart(ROOT,args.service,source)!=proof["chart"]:
                    raise EvidenceError("The same verified Helm chart must be promoted from "+source)
        release=verified_release(args.release_record,args.release_public_key,args.service,args.image) if args.release_record else None
        if release:
            verified_package(release,args.service,args.chart_package)
        write_delivery_record(args.service, args.target, args.image, "promote", args.release_record, args.release_public_key, args.evidence if args.target != "dev" else None)
        select_release(ROOT,args.service,args.target,args.image,release,args.chart_package)
        print(json.dumps({"image": args.image, "environment": args.target, "service": args.service}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Promotion rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
