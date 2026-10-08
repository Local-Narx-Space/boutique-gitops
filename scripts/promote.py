#!/usr/bin/env python3
import re,sys
from pathlib import Path
import yaml
service,target,image=sys.argv[1:]
if service not in ['frontend','catalogue','cart','orders']: raise SystemExit('Invalid service')
if target not in ['dev','staging','production']: raise SystemExit('Invalid target')
if not re.fullmatch(r'ghcr\.io/subhankar12-spec/boutique-'+service+r'@sha256:[a-f0-9]{64}',image): raise SystemExit('Invalid image digest')
root=Path(__file__).resolve().parents[1]
def config(env):return root/'services'/service/'overlays'/env/'kustomization.yaml'
if target!='dev':
    source='dev' if target=='staging' else 'staging'
    current=yaml.safe_load(config(source).read_text())['images'][0]
    if image!=current['name']+'@'+current.get('digest',''): raise SystemExit('Image must already be selected in '+source)
p=config(target);data=yaml.safe_load(p.read_text());data['images'][0].pop('newTag',None);data['images'][0]['digest']=image.split('@')[1];p.write_text(yaml.safe_dump(data,sort_keys=False))
print('Selected immutable image for',target)
