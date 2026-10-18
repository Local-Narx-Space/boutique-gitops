"""Compare optional controller/analysis resources with protected policy sources.

Candidate charts are data. Only the validator's protected template and probe may
create the extra workload/RBAC/Job privileges needed for progressive delivery.
"""
import ipaddress
import subprocess
import tempfile
from pathlib import Path
import yaml
from render import value_files
from release_config import ReleaseError

POLICY = Path(__file__).resolve().parents[1] / 'platform/argo-rollouts'


def merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value


def identity(item):
    return (item['apiVersion'], item['kind'], item['metadata'].get('namespace', ''), item['metadata']['name'])


def checked_application_resources(root, environment, profile, resources, helm='helm'):
    values = {}
    for name in value_files(environment, profile):
        merge(values, yaml.safe_load((Path(root) / 'environments' / environment / name).read_text()) or {})
    progressive = values.get('progressiveDelivery', {})
    enabled = progressive.get('enabled', False)
    if type(enabled) is not bool:
        raise ReleaseError('Progressive delivery switch must be boolean')
    backends = progressive.get('backendsEnabled', False)
    if type(backends) is not bool or (backends and not enabled):
        raise ReleaseError('Backend delivery requires an enabled boolean progressive policy')
    if not enabled:
        return resources
    try:
        endpoint = ipaddress.ip_network(progressive['apiServerCIDR'])
        laptop_api_network = profile == 'laptop' and str(endpoint) == '172.18.0.0/16'
        if endpoint.version != 4 or (endpoint.prefixlen != 32 and not laptop_api_network):
            raise ValueError()
        frontend = next(x for x in resources if x['kind'] == 'Deployment' and x['metadata']['name'] == 'frontend')
        spec = frontend['spec']
        container = spec['template']['spec']['containers'][0]
        origin = next(x['value'] for x in container['env'] if x['name'] == 'PUBLIC_ORIGIN')
        replicas = spec['replicas']
        if type(replicas) is not int or replicas < 1:
            raise ValueError()
        if spec['selector']['matchLabels'] != {'app.kubernetes.io/name': 'frontend'}:
            raise ValueError()
        if spec['template']['metadata']['labels'].get('app.kubernetes.io/name') != 'frontend':
            raise ValueError()
        if container['ports'] != [{'containerPort': 8080, 'name': 'http'}]:
            raise ValueError()
        service = next(x for x in resources if x['kind'] == 'Service' and x['metadata']['name'] == 'frontend')
        if service['spec']['selector'] != {'app.kubernetes.io/name': 'frontend'}:
            raise ValueError()
        if service['spec']['ports'] != [{'name': 'http', 'port': 8080, 'targetPort': 'http'}]:
            raise ValueError()
    except (KeyError, StopIteration, ValueError, TypeError):
        raise ReleaseError('Progressive frontend requires the approved selector/HTTP port, positive replicas and an approved API network')
    safe_values = {
        'progressiveDelivery': {'enabled': True, 'backendsEnabled': backends, 'apiServerCIDR': str(endpoint)},
        'frontend': {'replicaCount': replicas, 'deployment': {'template': {'spec': {'containers': [{'env': [{'name': 'PUBLIC_ORIGIN', 'value': origin}]}]}}}},
    }
    if backends:
        for name, port in [('catalogue', 8081), ('cart', 8082), ('orders', 8083)]:
            try:
                deployment = next(x for x in resources if x['kind'] == 'Deployment' and x['metadata']['name'] == name)
                spec = deployment['spec']
                replicas = spec['replicas']
                if type(replicas) is not int or replicas < 1:
                    raise ValueError()
                if spec['selector']['matchLabels'] != {'app.kubernetes.io/name': name}:
                    raise ValueError()
                if spec['template']['metadata']['labels'].get('app.kubernetes.io/name') != name:
                    raise ValueError()
                if spec['template']['spec']['containers'][0]['ports'] != [{'containerPort': port, 'name': 'http'}]:
                    raise ValueError()
                service = next(x for x in resources if x['kind'] == 'Service' and x['metadata']['name'] == name)
                if service['spec']['selector'] != {'app.kubernetes.io/name': name}:
                    raise ValueError()
                if service['spec']['ports'] != [{'name': 'http', 'port': port, 'targetPort': 'http'}]:
                    raise ValueError()
            except (KeyError, StopIteration, ValueError, TypeError):
                raise ReleaseError('Progressive backend requires approved selector/HTTP port and positive replicas')
            safe_values[name] = {'replicaCount': replicas}
    with tempfile.TemporaryDirectory(prefix='boutique-progressive-policy-') as directory:
        chart = Path(directory)
        (chart / 'templates').mkdir()
        (chart / 'analysis').mkdir()
        (chart / 'Chart.yaml').write_text('apiVersion: v2\nname: protected-progressive-policy\nversion: 1.0.0\n')
        (chart / 'values.yaml').write_text(yaml.safe_dump(safe_values))
        (chart / 'templates/frontend.yaml').write_bytes((POLICY / 'frontend.yaml.tpl').read_bytes())
        (chart / 'analysis/checkout-check.mjs').write_bytes((POLICY / 'checkout-check.mjs').read_bytes())
        (chart / 'analysis/backend-check.mjs').write_bytes((POLICY / 'backend-check.mjs').read_bytes())
        rendered = subprocess.check_output([helm, 'template', 'policy', str(chart), '-n', 'boutique-' + environment], text=True)
    expected = [item for item in yaml.safe_load_all(rendered) if item]
    controller = subprocess.check_output(['python3', str(POLICY / 'render-controller.py'), '--namespace', 'boutique-' + environment], text=True)
    expected += [item for item in yaml.safe_load_all(controller) if item]
    approved = {identity(item): item for item in expected}
    found = {}
    application = []
    for item in resources:
        key = identity(item)
        if key in approved:
            if key in found or item != approved[key]:
                raise ReleaseError('Progressive resource differs from protected controller/analysis policy: ' + key[-1])
            found[key] = item
        else:
            application.append(item)
    if set(found) != set(approved):
        raise ReleaseError('Progressive profile is missing required controller/analysis resources')
    return application
