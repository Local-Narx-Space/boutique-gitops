"""Optional delivery must keep native profiles unchanged until activation."""
import os
import copy
import shutil
import sys
from unittest.mock import patch
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(environment, enabled=False):
    folder = ROOT / 'environments' / environment
    command = ['helm', 'template', 'boutique-' + environment, str(folder), '-n', 'boutique-' + environment]
    for path in [folder / 'values.yaml', folder / 'releases.yaml', ROOT / 'laptop-profiles' / environment / 'values.yaml']:
        command += ['-f', str(path)]
    if enabled:
        command += ['--set', 'progressiveDelivery.enabled=true', '--set', 'progressiveDelivery.apiServerCIDR=172.18.0.2/32']
    return [item for item in yaml.safe_load_all(subprocess.check_output(command, text=True)) if item]


class ProgressiveManifests(unittest.TestCase):
    def test_image_policy_checks_all_profiles_with_progressive_delivery_enabled(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        from check_rendered_images import check_profile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'environments', root / 'environments')
            for profile in ['lab-profiles', 'laptop-profiles']:
                shutil.copytree(ROOT / profile, root / profile)
            for environment in ['dev', 'staging', 'production']:
                path = root / 'environments' / environment / 'values.yaml'
                values = yaml.safe_load(path.read_text())
                values['progressiveDelivery'] = {'enabled': True, 'apiServerCIDR': '172.18.0.2/32'}
                path.write_text(yaml.safe_dump(values))
                for profile in ['environments', 'lab-profiles', 'laptop-profiles']:
                    with self.subTest(environment=environment, profile=profile):
                        check_profile(root, profile + '/' + environment, environment)

    def test_disabled_by_default_in_every_environment(self):
        for environment in ['dev', 'staging', 'production']:
            with self.subTest(environment=environment):
                items = render(environment)
                self.assertFalse(any(item['kind'] == 'Rollout' for item in items))
                self.assertEqual(sum(item['kind'] == 'Deployment' for item in items), 4)

    def test_namespace_scoped_controller_and_fail_closed_checks(self):
        for environment in ['dev', 'staging', 'production']:
            with self.subTest(environment=environment):
                items = render(environment, True)
                self.assertFalse(any(item['kind'] in ['ClusterRole', 'ClusterRoleBinding'] for item in items))
                rollout = next(item for item in items if item['kind'] == 'Rollout')
                self.assertTrue(rollout['spec']['progressDeadlineAbort'])
                self.assertEqual(rollout['spec']['workloadRef']['scaleDown'], 'onsuccess')
                self.assertEqual(rollout['spec']['strategy']['blueGreen']['scaleDownDelayRevisionLimit'], 1)
                analyses = [item for item in items if item['kind'] == 'AnalysisTemplate']
                self.assertEqual(len(analyses), 2)
                for analysis in analyses:
                    metric = next(item for item in analysis['spec']['metrics'] if item['name'] == 'functional-checkout')
                    self.assertEqual(metric['failureLimit'], 0)
                    pod = metric['provider']['job']['spec']['template']['spec']
                    self.assertFalse(pod['automountServiceAccountToken'])
                    self.assertIn('@sha256:', pod['containers'][0]['image'])
                    self.assertEqual(metric['provider']['job']['spec']['backoffLimit'], 0)

    def test_generated_template_and_probe_copies_match_reviewed_source(self):
        folder = ROOT / 'platform/argo-rollouts'
        for environment in ['dev', 'staging', 'production']:
            target = ROOT / 'environments' / environment
            self.assertEqual((target / 'templates/progressive-frontend.yaml').read_bytes(), (folder / 'frontend.yaml.tpl').read_bytes())
            self.assertEqual((target / 'analysis/checkout-check.mjs').read_bytes(), (folder / 'checkout-check.mjs').read_bytes())
            generated = subprocess.check_output(['python3', str(folder / 'render-controller.py'), '--namespace', '{{ .Release.Namespace }}'], text=True)
            expected = '# Generated from locked Argo Rollouts namespace-install.yaml by render-controller.py\n{{- if (.Values.progressiveDelivery | default dict).enabled }}\n' + generated + '{{- end }}\n'
            self.assertEqual((target / 'templates/progressive-controller.yaml').read_text(), expected)

    def test_protected_policy_rejects_controller_and_analysis_mutations(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        from progressive_policy import checked_application_resources
        from release_config import ReleaseError
        items = render('dev', True)
        # Supply the flag through the normal values reader in an isolated root.
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'environments/dev'
            folder.mkdir(parents=True)
            (folder / 'values.yaml').write_text('progressiveDelivery:\n  enabled: true\n  apiServerCIDR: 172.18.0.2/32\n')
            with patch('progressive_policy.value_files', return_value=['values.yaml']):
                checked_application_resources(directory, 'dev', 'laptop', items)
                for kind, name, mutate in [
                    ('Deployment', 'argo-rollouts', lambda x:x['spec']['template']['spec']['containers'][0].update(image='unreviewed:latest')),
                    ('Role', 'argo-rollouts', lambda x:x['rules'].append({'apiGroups':['*'],'resources':['*'],'verbs':['*']})),
                    ('AnalysisTemplate', 'frontend-preview-check', lambda x:x['spec']['metrics'][1]['provider']['job']['spec']['template']['spec'].update(automountServiceAccountToken=True)),
                    ('ConfigMap', 'frontend-rollout-analysis', lambda x:x['data'].update({'checkout-check.mjs':'process.exit(0)'})),
                ]:
                    changed = copy.deepcopy(items)
                    mutate(next(x for x in changed if x['kind']==kind and x['metadata']['name']==name))
                    with self.subTest(kind=kind), self.assertRaises(ReleaseError):
                        checked_application_resources(directory, 'dev', 'laptop', changed)

    def test_custom_resource_schema_rejects_unknown_and_mistyped_fields(self):
        with tempfile.TemporaryDirectory(prefix='boutique-rollout-schemas-') as directory:
            subprocess.run(['python3', str(ROOT / 'platform/argo-rollouts/make-schemas.py'), directory], check=True)
            binary = os.environ.get('KUBECONFORM', 'kubeconform')
            resources = [item for item in render('staging', True) if item['kind'] in ['Rollout', 'AnalysisTemplate']]

            def validate(items):
                return subprocess.run([binary, '-strict', '-summary', '-schema-location', directory + '/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json'],
                                      input=yaml.safe_dump_all(items), text=True, capture_output=True)
            self.assertEqual(validate(resources).returncode, 0)
            resources[0]['spec']['unknownStrategy'] = True
            self.assertNotEqual(validate(resources).returncode, 0)
            resources[0]['spec'].pop('unknownStrategy')
            resources[0]['spec']['replicas'] = 'two'
            self.assertNotEqual(validate(resources).returncode, 0)


if __name__ == '__main__':
    unittest.main()
