#!/usr/bin/env python3
"""Ensure Kustomize produces exactly the app images authorized by each overlay."""
import argparse
import json
import subprocess
from pathlib import Path

import yaml

from evidence import ROOT, ENVIRONMENTS, SERVICES, EvidenceError, selected_image


def check_profile(root, profile, environment, kubectl="kubectl"):
    result = subprocess.run([kubectl, "kustomize", str(Path(root) / profile)], capture_output=True, text=True)
    if result.returncode:
        raise EvidenceError("Cannot render the application profile: " + profile)
    deployments = [item for item in yaml.safe_load_all(result.stdout) if item and item.get("kind") == "Deployment"]
    names = [item.get("metadata", {}).get("name") for item in deployments]
    if len(names) != len(SERVICES) or set(names) != set(SERVICES):
        raise EvidenceError("Application profile must contain exactly the four authorized Deployments")
    for deployment in deployments:
        service = deployment["metadata"]["name"]
        if deployment["metadata"].get("namespace") != "boutique-" + environment:
            raise EvidenceError("Rendered application Deployment targets an unexpected namespace")
        spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
        containers = spec.get("containers", [])
        if len(containers) != 1 or containers[0].get("name") != service or spec.get("initContainers"):
            raise EvidenceError("Unapproved app sidecar, init container or service container rename")
        expected = selected_image(root, service, environment)
        if containers[0].get("image") != expected:
            raise EvidenceError(f"Rendered {service} image bypasses its environment overlay selection")
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--kubectl", default="kubectl")
    args = parser.parse_args()
    try:
        checked = []
        for environment in ENVIRONMENTS:
            for parent in ("environments", "lab-profiles"):
                profile = f"{parent}/{environment}"
                if (args.root / profile).is_dir():
                    checked.append(check_profile(args.root, profile, environment, args.kubectl))
        print(json.dumps({"checked_profiles": checked}))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Rendered image policy rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
