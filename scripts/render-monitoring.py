#!/usr/bin/env python3
"""Render the monitoring Helm chart with its reviewed cloud or lab values."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('homelab', 'nonprod', 'production')


def render(root, profile, lab=False, helm='helm', lint=False):
    if profile not in PROFILES or (lab and profile == 'homelab'):
        raise ValueError('Select homelab/nonprod/production; lab supports nonprod/production')
    root = Path(root)
    chart = root / 'monitoring'
    arguments = [helm, 'lint', '--strict', str(chart)] if lint else [helm, 'template', ('lab-monitoring-' if lab else 'boutique-monitoring-') + profile, str(chart), '--namespace', 'monitoring', '--include-crds']
    arguments += ['--values', str(chart / 'profiles' / profile / 'values.yaml')]
    if lab:
        arguments += ['--values', str(root / 'lab-profiles/monitoring' / profile / 'values.yaml')]
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Monitoring Helm validation/render failed: ' + result.stderr.strip())
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=PROFILES)
    parser.add_argument('--lab', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--helm', default='helm')
    parser.add_argument('--lint', action='store_true')
    args = parser.parse_args()
    try:
        print(render(args.root, args.profile, args.lab, args.helm, args.lint), end='')
    except (ValueError, OSError) as error:
        parser.exit(1, 'Monitoring render rejected: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
