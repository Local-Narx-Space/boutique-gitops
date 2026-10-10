#!/usr/bin/env python3
"""Prepare a GitOps change; promotion copies an existing image and chart unchanged."""
import argparse
import json
from pathlib import Path
from release_config import ROOT, SERVICES, ENVIRONMENTS, ReleaseError, selected_image, validate_identity
from helm_release import selected_chart, package_path, load, select_release

def promote(root, service, target, image=None, chart_package=None, source_commit=None):
    if service not in SERVICES or target not in ENVIRONMENTS:
        raise ReleaseError('Invalid service or environment')
    if target == 'dev':
        if not image or not chart_package or not source_commit:
            raise ReleaseError('Dev requires a published digest, chart package and full source commit')
        validate_identity(service, target, image)
        version = '0.1.0-' + source_commit
        path = Path(chart_package)
        if path.is_symlink():
            raise ReleaseError('Chart package cannot be a symbolic link')
        package = path.read_bytes()
    else:
        if chart_package or source_commit:
            raise ReleaseError('Promote the existing preceding-environment chart; do not replace it')
        source = 'dev' if target == 'staging' else 'staging'
        selected = selected_image(root, service, source)
        if image and image != selected:
            raise ReleaseError('Requested image differs from preceding environment')
        image = selected
        validate_identity(service, target, image)
        chart = selected_chart(root, service, source)
        version = chart['version']
        package = load(root, package_path(service, source, version), binary=True)
    select_release(root, service, target, image, version, package)
    return {'service': service, 'environment': target, 'image': image, 'chart_version': version}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=SERVICES)
    parser.add_argument('target', choices=ENVIRONMENTS)
    parser.add_argument('image', nargs='?')
    parser.add_argument('--chart-package')
    parser.add_argument('--source-commit')
    args = parser.parse_args()
    try:
        print(json.dumps(promote(ROOT, args.service, args.target, args.image, args.chart_package, args.source_commit)))
    except (ReleaseError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, 'Promotion rejected: ' + str(error) + '\n')
if __name__ == '__main__':
    main()
