#!/usr/bin/env python3
"""Ensure Helm produces exactly the app images authorized by each Helm release."""
import argparse
import json
import subprocess
from pathlib import Path

import yaml

from render import render
from release_config import ROOT, ENVIRONMENTS, SERVICES, ReleaseError, selected_image


def check_profile(root, profile, environment, helm="helm"):
    parent=profile.split('/')[0]
    rendered=render(root,environment,'lab' if parent=='lab-profiles' else 'cloud',helm)
    resources=[item for item in yaml.safe_load_all(rendered) if item]
    allowed={'Namespace','NetworkPolicy','ResourceQuota','Deployment','Service','ServiceAccount','PodDisruptionBudget'}
    if parent=='lab-profiles':allowed.update({'Certificate','ConfigMap','Ingress','StatefulSet'})
    identities=[]
    for item in resources:
        kind=item.get('kind');metadata=item.get('metadata',{})
        if kind not in allowed:raise ReleaseError('Unapproved application resource kind')
        namespace=metadata.get('namespace','')
        if kind=='Namespace':
            if metadata.get('name')!='boutique-'+environment:raise ReleaseError('Unexpected application namespace')
        elif namespace!='boutique-'+environment:raise ReleaseError('Application resource targets an unexpected namespace')
        identities.append((item.get('apiVersion'),kind,namespace,metadata.get('name')))
    if len(identities)!=len(set(identities)):raise ReleaseError('Duplicate application resource identity')
    data_images={
        'postgres':'postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea',
        'redis':'redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499',
    }
    statefulsets=[item for item in resources if item.get('kind')=='StatefulSet']
    if parent=='lab-profiles' and {item['metadata']['name'] for item in statefulsets}!=set(data_images):
        raise ReleaseError('Lab requires only its two approved data StatefulSets')
    for item in statefulsets:
        spec=item.get('spec',{}).get('template',{}).get('spec',{})
        name=item['metadata']['name'];containers=spec.get('containers',[])
        if name not in data_images or len(containers)!=1 or containers[0].get('name')!=name or containers[0].get('image')!=data_images[name] or spec.get('initContainers') or spec.get('ephemeralContainers'):
            raise ReleaseError('Unapproved lab data image or sidecar')
    deployments=[item for item in resources if item.get('kind')=='Deployment']
    names = [item.get("metadata", {}).get("name") for item in deployments]
    if len(names) != len(SERVICES) or set(names) != set(SERVICES):
        raise ReleaseError("Application profile must contain exactly the four authorized Deployments")
    for deployment in deployments:
        service = deployment["metadata"]["name"]
        if deployment["metadata"].get("namespace") != "boutique-" + environment:
            raise ReleaseError("Rendered application Deployment targets an unexpected namespace")
        spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
        containers = spec.get("containers", [])
        if len(containers) != 1 or containers[0].get("name") != service or spec.get("initContainers") or spec.get("ephemeralContainers"):
            raise ReleaseError("Unapproved app sidecar, init container or service container rename")
        expected = selected_image(root, service, environment)
        if containers[0].get("image") != expected:
            raise ReleaseError(f"Rendered {service} image bypasses its Helm release selection")
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--helm", default="helm")
    args = parser.parse_args()
    try:
        checked = []
        for environment in ENVIRONMENTS:
            for parent in ("environments", "lab-profiles"):
                profile = f"{parent}/{environment}"
                if (args.root / profile).is_dir():
                    checked.append(check_profile(args.root, profile, environment, args.helm))
        print(json.dumps({"checked_profiles": checked}))
    except (ReleaseError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, "Rendered image policy rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
