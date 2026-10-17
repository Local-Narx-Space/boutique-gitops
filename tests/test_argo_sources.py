import copy
from pathlib import Path
import sys
import unittest

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
