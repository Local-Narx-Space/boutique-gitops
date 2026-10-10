#!/usr/bin/env python3
"""Restore a service's image and chart from a previous protected-main Git commit."""
import argparse
import json
import re
from release_config import ROOT, SERVICES, ENVIRONMENTS, ReleaseError, git, selected_image, validate_identity
from helm_release import selected_chart, package_path, load, select_release

def rollback(root, service, target, commit):
    if service not in SERVICES or target not in ENVIRONMENTS or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ReleaseError('Expected approved service/environment and full GitOps commit')
    git(root, 'merge-base', '--is-ancestor', commit, 'origin/main')
    image = selected_image(root, service, target, commit)
    validate_identity(service, target, image)
    chart = selected_chart(root, service, target, commit)
    package = load(root, package_path(service, target, chart['version']), commit, binary=True)
    select_release(root, service, target, image, chart['version'], package)
    return {'service': service, 'environment': target, 'image': image, 'restored_commit': commit}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=SERVICES)
    parser.add_argument('target', choices=ENVIRONMENTS)
    parser.add_argument('commit', help='Previous protected-main commit containing the working release')
    args = parser.parse_args()
    try:
        print(json.dumps(rollback(ROOT, args.service, args.target, args.commit)))
    except (ReleaseError, OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, 'Rollback rejected: ' + str(error) + '\n')
if __name__ == '__main__':
    main()
