#!/usr/bin/env python3
"""Prove real controller recovery in a fixed, isolated namespace only.

Requires the pinned namespace controller and CRDs installed separately. The
fixture image must already exist on --node; no registry credentials are used.
Application namespaces, public routes and GitOps Applications are never mutated.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'boutique-rollouts-check'
SERVICE = 'frontend'
PORT = 8080
IMAGE = 'ghcr.io/subhankar12-spec/boutique-frontend@sha256:719736fb72cf4aac5131630374ab44fcd1aa7a365250bfbf40caacda4cca25aa'


def kubectl(*args, body=None):
    result = subprocess.run(['kubectl', '-n', NAMESPACE, *args],
                            input=body, text=True, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError(result.stderr[:1000])
    return result.stdout


def get(kind, name):
    return json.loads(kubectl('get', kind, name, '-o', 'json'))


def apply(items):
    kubectl('apply', '-f', '-', body=yaml.safe_dump_all(items, sort_keys=False))


def serving():
    # This sampler is deliberately small: repeatedly starting fetch/Undici on a
    # CPU-limited probe can time out during client initialization, before I/O.
    program = "const h=require('node:http');h.get('http://SERVICE:PORT/version',r=>{let b='';r.on('data',x=>b+=x);r.on('end',()=>{console.log(b);process.exit(r.statusCode===200?0:1)})}).on('error',()=>process.exit(1));setTimeout(()=>process.exit(1),5000).unref()"
    program = program.replace('SERVICE', SERVICE).replace('PORT', str(PORT))
    return json.loads(kubectl('exec', 'traffic-probe', '--', 'node', '-e', program))['version']


def wait(predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(2)
    raise RuntimeError('Isolated rollout did not reach the expected state')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--service', choices=['frontend','catalogue','cart','orders'], default='frontend')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    global SERVICE, PORT
    SERVICE = args.service
    PORT = {'frontend':8080, 'catalogue':8081, 'cart':8082, 'orders':8083}[SERVICE]
    args.evidence.mkdir(parents=True, exist_ok=True)
    # Render the actual optional templates; only shorten analysis windows for
    # isolated failure injection. Real profile defaults remain unchanged.
    command = ['helm', 'template', 'boutique-staging', str(ROOT / 'environments/staging'),
               '-n', NAMESPACE, '-f', str(ROOT / 'environments/staging/values.yaml'),
               '-f', str(ROOT / 'environments/staging/releases.yaml'),
               '-f', str(ROOT / 'laptop-profiles/staging/values.yaml'),
               '--set', 'progressiveDelivery.enabled=true', '--set', 'progressiveDelivery.backendsEnabled=true', '--set', 'progressiveDelivery.apiServerCIDR=172.18.0.2/32']
    rendered = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    documents = [item for item in yaml.safe_load_all(rendered) if item]
    selected = [item for item in documents
                if item['kind']=='Rollout' and item['metadata']['name']==SERVICE
                or item['kind']=='AnalysisTemplate' and item['metadata']['name'].startswith(SERVICE+'-')
                or item['kind'] in ['ConfigMap','ServiceAccount'] and item['metadata']['name'] in ['frontend-rollout-analysis']
                or item['kind']=='Service' and item['metadata']['name'] in [SERVICE,SERVICE+'-preview']]
    for item in selected:
        item['metadata']['namespace'] = NAMESPACE
        if item['kind'] == 'AnalysisTemplate':
            for metric in item['spec']['metrics']:
                metric['interval'] = '2s'
                metric['count'] = 2 if 'preview' in item['metadata']['name'] else 4
                phase = 'preview' if 'preview' in item['metadata']['name'] else 'serving'
                if phase == 'serving':
                    metric['initialDelay'] = '5s'  # Observe real cutover before injecting failure.
                if 'web' in metric['provider']:
                    metric['provider']['web']['headers'] = [{'key': 'X-Fixture-Phase', 'value': phase}]
                if 'job' in metric['provider']:
                    metric['count'] = 1 if 'preview' in item['metadata']['name'] else 2
                    pod = metric['provider']['job']['spec']['template']['spec']
                    pod['nodeName'] = args.node
                    pod.pop('imagePullSecrets', None)
                    pod['containers'][0]['imagePullPolicy'] = 'Never'
        if item['kind'] == 'Rollout':
            item['spec']['minReadySeconds'] = 1
            item['spec']['progressDeadlineSeconds'] = 180
            item['spec']['strategy']['blueGreen']['abortScaleDownDelaySeconds'] = 1

    template = {'metadata': {'labels': {'app.kubernetes.io/name': SERVICE}},
                'spec': {'nodeName': args.node, 'automountServiceAccountToken': False,
                         'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'runAsNonRoot': True},
                         'containers': [{'name': SERVICE, 'image': IMAGE, 'imagePullPolicy': 'Never',
                                         'command': ['node', '/fixture/server.mjs'],
                                         'ports': [{'name': 'http', 'containerPort': PORT}],
                                         'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '100m', 'memory': '64Mi'}},
                                         'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}, 'seccompProfile': {'type': 'RuntimeDefault'}},
                                         'readinessProbe': {'httpGet': {'path': '/health/ready', 'port': 'http'}, 'periodSeconds': 1, 'failureThreshold': 1},
                                         'env': [{'name': 'VERSION', 'value': 'stable-v1'}, {'name': 'READY', 'value': 'true'}, {'name': 'FAIL_AFTER', 'value': ''}, {'name': 'FAIL_POST', 'value': ''}],
                                         'volumeMounts': [{'name': 'fixture', 'mountPath': '/fixture', 'readOnly': True}]}],
                         'volumes': [{'name': 'fixture', 'configMap': {'name': 'fixture-server'}}]}}
    deployment = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': SERVICE, 'namespace': NAMESPACE},
                  'spec': {'replicas': 1, 'selector': {'matchLabels': {'app.kubernetes.io/name': SERVICE}}, 'template': template}}
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'fixture-server', 'namespace': NAMESPACE},
              'data': {'server.mjs': (ROOT / 'platform/argo-rollouts/fixture-server.mjs').read_text()}}
    probe_spec = copy.deepcopy(template['spec'])
    probe_spec['terminationGracePeriodSeconds'] = 1
    probe_spec['containers'][0].update(command=['node', '-e', 'setInterval(()=>{},1000)'])
    probe_spec['containers'][0].pop('readinessProbe')
    probe_spec['containers'][0].pop('ports')
    probe = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'traffic-probe', 'namespace': NAMESPACE}, 'spec': probe_spec}
    # The sampler is a bare Pod; replace it when test configuration changes.
    kubectl('delete', 'pod', 'traffic-probe', '--ignore-not-found=true', '--wait=true', '--timeout=35s')
    dependencies = []
    if SERVICE != 'frontend':
        for name, port in [('catalogue',8081),('cart',8082)]:
            if name == SERVICE:
                continue
            dep = copy.deepcopy(deployment)
            dep['metadata']['name'] = name
            dep['spec']['selector']['matchLabels']['app.kubernetes.io/name'] = name
            dep['spec']['template']['metadata']['labels']['app.kubernetes.io/name'] = name
            container = dep['spec']['template']['spec']['containers'][0]
            container['name'] = name
            container['ports'][0]['containerPort'] = port
            container['env'] = [{'name':'SERVICE','value':name},{'name':'PORT','value':str(port)},{'name':'VERSION','value':'dependency'}]
            dependencies += [dep, {'apiVersion':'v1','kind':'Service','metadata':{'name':name,'namespace':NAMESPACE},
                                  'spec':{'selector':{'app.kubernetes.io/name':name},'ports':[{'port':port,'targetPort':'http'}]}}]
        template['spec']['containers'][0]['env'] += [{'name':'SERVICE','value':SERVICE},{'name':'PORT','value':str(PORT)}]
    apply([config, deployment, probe, *dependencies, *selected])
    kubectl('wait', 'pod/traffic-probe', '--for=condition=Ready', '--timeout=90s')
    def initial_traffic_ready():
        try:
            rollout = get('rollout', SERVICE)
            return rollout.get('status', {}).get('phase') == 'Healthy' and serving() == 'stable-v1'
        except RuntimeError:
            return False  # Initial Service/DNS creation is still propagating.
    wait(initial_traffic_ready, timeout=240)
    results = []

    def scenario(version, ready=True, fail_after=None, fail_post=False, success=False, expected='stable-v2'):
        # Mutate only the reference Deployment's pod template, as normal GitOps
        # image/template changes do. Never manually abort or revert the Rollout.
        kubectl('patch', 'rollout', SERVICE, '--type=merge', '-p', json.dumps({'spec': {'progressDeadlineSeconds': 180 if ready else 20}}))
        current = get('deployment', SERVICE)
        pod = current['spec']['template']
        pod['spec']['containers'][0]['env'] = [{'name': 'VERSION', 'value': version},
                                              {'name': 'READY', 'value': str(ready).lower()}]
        if SERVICE != 'frontend':
            pod['spec']['containers'][0]['env'] += [{'name':'SERVICE','value':SERVICE},{'name':'PORT','value':str(PORT)}]
        if fail_after is not None:
            pod['spec']['containers'][0]['env'].append({'name': 'FAIL_AFTER', 'value': str(fail_after)})
        if fail_post:
            pod['spec']['containers'][0]['env'].append({'name': 'FAIL_POST', 'value': 'true'})
        generation = int(get('rollout', SERVICE).get('status', {}).get('workloadObservedGeneration', 0))
        kubectl('patch', 'deployment', SERVICE, '--type=merge', '-p', json.dumps({'spec': {'template': pod}}))
        samples = []
        protected_samples = 0

        def finished():
            nonlocal protected_samples
            rollout = get('rollout', SERVICE); status = rollout.get('status', {})
            live = serving()
            samples.append({'phase': status.get('phase'), 'abort': status.get('abort'),
                            'serving': live, 'stableRS': status.get('stableRS'),
                            'activeSelector': get('service', SERVICE)['spec']['selector'].get('rollouts-pod-template-hash')})
            if int(status.get('workloadObservedGeneration', 0)) <= generation:
                return False
            if not ready:
                # A never-ready candidate must never receive traffic. Retained
                # old revisions can delay the controller's deadline-abort timer;
                # do not misreport that safety gate as a completed rollback.
                protected = live == expected and status.get('currentPodHash') != status.get('stableRS') and get('service', SERVICE)['spec']['selector'].get('rollouts-pod-template-hash') == status.get('stableRS')
                protected_samples = protected_samples + 1 if protected else 0
                return protected_samples >= 3
            return status.get('phase') == 'Healthy' and live == version if success else status.get('abort') is True and live == expected

        wait(finished, timeout=240)
        if not success and ready:
            assert get('service', SERVICE)['spec']['selector']['rollouts-pod-template-hash'] == get('rollout', SERVICE)['status']['stableRS']
            # Failure is retained as failed desired state, not silently blessed.
            assert get('rollout', SERVICE)['status']['phase'] == 'Degraded'
        results.append({'scenario': version, 'success': True, 'automatic': not success,
                        'outcome': 'promoted' if success else 'stable traffic preserved without cutover' if not ready else 'automatically aborted and stable traffic restored',
                        'samples': samples})
        (args.evidence / 'scenarios.json').write_text(json.dumps(results, indent=2) + '\n')
        for kind in ['rollout', 'analysisruns', 'jobs', 'services', 'replicasets']:
            (args.evidence / (version + '-' + kind + '.json')).write_text(kubectl('get', kind, '-o', 'json'))
        print('PASS', version, flush=True)

    scenario('stable-v2', success=True)
    scenario('bad-readiness', ready=False)
    scenario('bad-preview', fail_after=0)
    # The first serving-phase check activates a fixture-wide products failure;
    # preview checks cannot activate it. The candidate must actually serve traffic.
    scenario('bad-after-switch', fail_post=True)
    assert any(sample['serving'] == 'bad-after-switch' for sample in results[-1]['samples']), 'Post-switch failure never actually served traffic'
    scenario('stable-v3', success=True)
    print('All isolated controller promotion and automatic recovery scenarios passed', flush=True)


if __name__ == '__main__':
    main()
