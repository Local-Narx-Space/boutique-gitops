#!/usr/bin/env python3
"""Ensure Helm produces exactly the app images authorized by each Helm release."""
import argparse
import json
import subprocess
from pathlib import Path

import yaml

from render import render
from progressive_policy import checked_application_resources, merge
from render import value_files
from release_config import ROOT, ENVIRONMENTS, SERVICES, ReleaseError, selected_image


def check_autoscaling(root, environment, profile, resources):
    values = {}
    for name in value_files(environment, profile):
        merge(values, yaml.safe_load((Path(root) / 'environments' / environment / name).read_text()) or {})
    config = values.get('frontendAutoscaling', {})
    enabled = config.get('enabled', False)
    hpas = [r for r in resources if r.get('kind') == 'HorizontalPodAutoscaler']
    if type(enabled) is not bool:
        raise ReleaseError('Frontend autoscaling switch must be boolean')
    if not enabled:
        if hpas:
            raise ReleaseError('Unexpected autoscaler in a disabled profile')
        return resources
    minimum, maximum, cpu = (config.get(k) for k in ('minReplicas', 'maxReplicas', 'targetCPUUtilizationPercentage'))
    if (profile != 'laptop' or environment not in ('staging', 'production')
            or any(type(v) is not int for v in (minimum, maximum, cpu))
            or not 2 <= minimum <= maximum <= 3 or not 1 <= cpu <= 100):
        raise ReleaseError('Frontend autoscaling requires bounded QA/prod laptop settings')
    progressive = values.get('progressiveDelivery', {}).get('enabled', False)
    expected = {'apiVersion': 'autoscaling/v2', 'kind': 'HorizontalPodAutoscaler',
        'metadata': {'name': 'frontend', 'namespace': 'boutique-' + environment},
        'spec': {'scaleTargetRef': {'apiVersion': 'argoproj.io/v1alpha1' if progressive else 'apps/v1',
                                  'kind': 'Rollout' if progressive else 'Deployment', 'name': 'frontend'},
                 'minReplicas': minimum, 'maxReplicas': maximum,
                 'metrics': [{'type': 'Resource', 'resource': {'name': 'cpu',
                     'target': {'type': 'Utilization', 'averageUtilization': cpu}}}],
                 'behavior': {key: {'stabilizationWindowSeconds': seconds,
                                   'policies': [{'type': 'Pods', 'value': 1, 'periodSeconds': 60}]}
                              for key, seconds in [('scaleUp', 30), ('scaleDown', 300)]}}}
    if hpas != [expected]:
        raise ReleaseError('Frontend autoscaler differs from the approved target/metrics/bounds')
    return [r for r in resources if r.get('kind') != 'HorizontalPodAutoscaler']


def check_profile(root, profile, environment, helm="helm", *, rendered=None):
    parent=profile.split('/')[0]
    profile_name={'laptop-profiles':'laptop','environments':'cloud'}[parent]
    if rendered is None:
        rendered=render(root,environment,profile_name,helm)
    resources=[item for item in yaml.safe_load_all(rendered) if item]
    resources=check_autoscaling(root, environment, profile_name, resources)
    resources=checked_application_resources(root, environment, profile_name, resources, helm)
    allowed={'Namespace','NetworkPolicy','ResourceQuota','Deployment','Service','ServiceAccount','PodDisruptionBudget'}
    if parent=='laptop-profiles':allowed.update({'Ingress','StatefulSet'})
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
    if parent == 'laptop-profiles' and {item['metadata']['name'] for item in statefulsets}!=set(data_images):
        raise ReleaseError('Laptop profile requires only its two approved data StatefulSets')
    for item in statefulsets:
        spec=item.get('spec',{}).get('template',{}).get('spec',{})
        name=item['metadata']['name'];containers=spec.get('containers',[])
        if name not in data_images or len(containers)!=1 or containers[0].get('name')!=name or containers[0].get('image')!=data_images[name] or spec.get('initContainers') or spec.get('ephemeralContainers'):
            raise ReleaseError('Unapproved laptop data image or sidecar')
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
    parser.add_argument("--rendered-file", type=Path, help="Validate manifests already rendered by the protected validator")
    parser.add_argument("--environment", choices=ENVIRONMENTS)
    parser.add_argument("--profile", choices=("cloud", "laptop"))
    args = parser.parse_args()
    if any((args.rendered_file, args.environment, args.profile)) and not all((args.rendered_file, args.environment, args.profile)):
        parser.error("--rendered-file, --environment and --profile must be supplied together")
    try:
        checked = []
        if args.rendered_file:
            parent = {"cloud": "environments", "laptop": "laptop-profiles"}[args.profile]
            profile = f"{parent}/{args.environment}"
            checked.append(check_profile(args.root, profile, args.environment, args.helm,
                                         rendered=args.rendered_file.read_text()))
            print(json.dumps({"checked_profiles": checked}))
            return
        for environment in ENVIRONMENTS:
            for parent in ("environments", "laptop-profiles"):
                profile = f"{parent}/{environment}"
                if (args.root / profile).is_dir():
                    checked.append(check_profile(args.root, profile, environment, args.helm))
        print(json.dumps({"checked_profiles": checked}))
    except (ReleaseError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        parser.exit(1, "Rendered image policy rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
