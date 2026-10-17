#!/usr/bin/env python3
"""Render application Helm profiles from their pinned packages and value files."""
import argparse
from pathlib import Path
import subprocess

from release_config import ROOT, ENVIRONMENTS, ReleaseError


def value_files(environment, profile='cloud'):
    files=['values.yaml','releases.yaml']
    if profile=='laptop':
        files.append(f'../../laptop-profiles/{environment}/values.yaml')
    elif profile!='cloud':raise ReleaseError('Invalid Helm profile')
    return files


def render(root, environment, profile='cloud', helm='helm', lint=False):
    if environment not in ENVIRONMENTS:raise ReleaseError('Invalid Helm environment')
    folder=Path(root)/'environments'/environment
    arguments=[helm,'lint','--strict',str(folder)] if lint else [helm,'template','boutique-'+environment,str(folder),'--namespace','boutique-'+environment,'--include-crds']
    for name in value_files(environment,profile):arguments+=['--values',str(folder/name)]
    result=subprocess.run(arguments,capture_output=True,text=True)
    if result.returncode:raise ReleaseError('Helm profile validation/render failed: '+result.stderr.strip())
    return result.stdout


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('environment',choices=ENVIRONMENTS);p.add_argument('--profile',choices=['cloud','laptop'],default='cloud');p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--helm',default='helm');p.add_argument('--lint',action='store_true');args=p.parse_args()
    try:print(render(args.root,args.environment,args.profile,args.helm,args.lint),end='')
    except (ReleaseError,OSError,ValueError) as error:p.exit(1,'Helm render rejected: '+str(error)+'\n')


if __name__=='__main__':main()
