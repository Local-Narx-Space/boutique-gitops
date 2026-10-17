import copy
from pathlib import Path
import sys
import unittest
import subprocess
import tempfile
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from helm_release import approved_argo_source
from release_config import ReleaseError
from render import value_files


class ArgoSourceTests(unittest.TestCase):
    def source(self, environment, profile='laptop'):
        return {
            'repoURL': 'https://github.com/subhankar12-spec/boutique-gitops.git',
            'targetRevision': 'main', 'path': f'environments/{environment}',
            'helm': {'releaseName': f'boutique-{environment}',
                     'valueFiles': value_files(environment, profile)},
        }

    def test_all_active_environment_profiles(self):
        for environment in ('dev', 'staging', 'production'):
            for profile in ('cloud', 'laptop'):
                with self.subTest(environment=environment, profile=profile):
                    approved_argo_source(self.source(environment, profile), environment)

    def test_application_set_delegates_only_rollout_owned_fields_in_qa_and_prod(self):
        root=Path(__file__).resolve().parents[1]
        appset=yaml.safe_load((root/'applications/laptop-appset.yaml').read_text())
        # Helm executes the same Go text/template + Sprig loop used by ApplicationSet.
        patch=appset['spec']['templatePatch'].replace('.progressiveDelivery','.Values.progressiveDelivery').replace('.autoSync','.Values.autoSync')
        with tempfile.TemporaryDirectory() as folder:
            chart=Path(folder);(chart/'templates').mkdir()
            (chart/'Chart.yaml').write_text('apiVersion: v2\nname: appset-patch-check\nversion: 1.0.0\n')
            (chart/'templates/patch.yaml').write_text(patch)
            for element in appset['spec']['generators'][0]['list']['elements']:
                env=element['environment']
                enabled=env!='dev'
                self.assertEqual(element['progressiveDelivery'],enabled)
                profile=yaml.safe_load((root/f'laptop-profiles/{env}/values.yaml').read_text())['progressiveDelivery']
                self.assertEqual(profile['enabled'],enabled)
                self.assertEqual(profile.get('backendsEnabled',False),enabled)
                (chart/'values.yaml').write_text(yaml.safe_dump(element))
                rendered=yaml.safe_load(subprocess.check_output(['helm','template','patch',str(chart)],text=True))
                ignore=rendered['spec'].get('ignoreDifferences',[])
                self.assertEqual(len(ignore),12 if enabled else 0)
                for rule in ignore:
                    self.assertEqual(rule['jsonPointers'],['/spec/replicas'] if rule['kind']=='Deployment' else ['/spec/selector/rollouts-pod-template-hash'])

    def test_removed_profiles_are_rejected(self):
        for profile in ('lab', 'local'):
            with self.subTest(profile=profile), self.assertRaises(ReleaseError):
                value_files('dev', profile)

    def test_rejects_inline_overrides_and_unapproved_files(self):
        for environment in ('dev', 'staging', 'production'):
            for key, value in (
                ('values', 'frontend: {}'), ('valuesObject', {'frontend': {}}),
                ('parameters', [{'name': 'frontend.image.tag', 'value': 'latest'}]),
                ('fileParameters', [{'name': 'config', 'path': 'override.yaml'}]),
                ('valueFiles', value_files(environment, 'laptop') + ['override.yaml']),
                ('valueFiles', value_files('other', 'laptop')),
                ('valueFiles', list(reversed(value_files(environment, 'laptop')))),
            ):
                source = copy.deepcopy(self.source(environment))
                source['helm'][key] = value
                with self.subTest(environment=environment, key=key, value=value):
                    with self.assertRaises(ReleaseError):
                        approved_argo_source(source, environment)


if __name__ == '__main__':
    unittest.main()
