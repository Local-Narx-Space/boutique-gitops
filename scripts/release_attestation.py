#!/usr/bin/env python3
"""Sign or verify the trusted protected-main release job's quality record."""
import argparse
import json

from delivery_records import validate_release, verified_release
from evidence import EvidenceError, read_json, sign


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    signing = commands.add_parser("sign")
    for name in ("record", "signing-key", "output"):
        signing.add_argument("--" + name, required=True)
    verification = commands.add_parser("verify")
    for name in ("attestation", "public-key", "service", "image"):
        verification.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        if args.command == "sign":
            payload = read_json(args.record)
            validate_release(payload, payload.get("service"), payload.get("image"))
            sign(payload, args.signing_key, args.output)
        else:
            payload = verified_release(args.attestation, args.public_key, args.service, args.image)
        print(json.dumps({"service": payload["service"], "image": payload["image"], "source_commit": payload["source_commit"]}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Release attestation rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
