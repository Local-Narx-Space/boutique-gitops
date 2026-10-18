"""Autoscaling must target the serving controller and remain tightly bounded."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_rendered_images import check_profile, check_autoscaling
from render import render
from release_config import ReleaseError


class FrontendAutoscaling(unittest.TestCase):
    def test_only_qa_and_prod_laptop_frontend_autoscale(self):
        for environment in ('dev', 'staging', 'production'):
            for profile in ('cloud', 'laptop'):
                with self.subTest(environment=environment, profile=profile):
                    rendered = render(ROOT, environment, profile)
                    resources = [x for x in yaml.safe_load_all(rendered) if x]
                    hpas = [x for x in resources if x['kind'] == 'HorizontalPodAutoscaler']
                    enabled = profile == 'laptop' and environment != 'dev'
                    self.assertEqual(len(hpas), int(enabled))
                    check_profile(ROOT, ('laptop-profiles' if profile == 'laptop' else 'environments') + '/' + environment,
                                  environment, rendered=rendered)
                    if enabled:
                        spec = hpas[0]['spec']
                        self.assertEqual(spec['scaleTargetRef'], {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Rollout', 'name': 'frontend'})
                        self.assertEqual((spec['minReplicas'], spec['maxReplicas']), (2, 3))
                        self.assertEqual(spec['behavior']['scaleDown']['stabilizationWindowSeconds'], 300)

    def test_wrong_target_unbounded_scale_and_extra_autoscaler_are_rejected(self):
        resources = [x for x in yaml.safe_load_all(render(ROOT, 'production', 'laptop')) if x]
        for mutation in ('target', 'bound', 'extra'):
            changed = copy.deepcopy(resources)
            hpa = next(x for x in changed if x['kind'] == 'HorizontalPodAutoscaler')
            if mutation == 'target': hpa['spec']['scaleTargetRef']['kind'] = 'Deployment'
            if mutation == 'bound': hpa['spec']['maxReplicas'] = 100
            if mutation == 'extra':
                extra = copy.deepcopy(hpa); extra['metadata']['name'] = 'orders'; changed.append(extra)
            with self.subTest(mutation=mutation), self.assertRaises(ReleaseError):
                check_autoscaling(ROOT, 'production', 'laptop', changed)

    def test_metrics_server_verifies_kubelets_unless_laptop_override_is_selected(self):
        folder = ROOT / 'platform/metrics-server'
        lock = json.loads((folder / 'release-lock.json').read_text())
        for laptop in (False, True):
            command = ['helm', 'template', 'metrics', str(folder), '-n', 'kube-system']
            if laptop: command += ['-f', str(folder / 'values-laptop.yaml')]
            resources = [x for x in yaml.safe_load_all(subprocess.check_output(command, text=True)) if x]
            pod = next(x for x in resources if x['kind'] == 'Deployment')['spec']['template']['spec']
            container = pod['containers'][0]
            self.assertEqual(container['image'], lock['image'])
            self.assertIn('@sha256:', container['image'])
            self.assertEqual('--kubelet-insecure-tls' in container['args'], laptop)
            for resource in resources:
                if resource['kind'] == 'ClusterRole':
                    self.assertFalse(any('secrets' in rule.get('resources', []) for rule in resource['rules']))


if __name__ == '__main__':
    unittest.main()
