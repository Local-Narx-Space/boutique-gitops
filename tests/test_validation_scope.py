"""Only clean, release-only changes may skip unrelated manifests."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from release_config import validation_environments


class ValidationScopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Validation Test')
        self.git('config', 'user.email', 'validation@example.invalid')
        self.commit('README.md')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def commit(self, path):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('test\n')
        self.git('add', '--', path)
        self.git('commit', '-qm', 'Test change')

    def test_release_changes_scope_only_affected_environments(self):
        self.commit('environments/staging/releases.yaml')
        self.commit('environments/staging/Chart.yaml')
        self.commit('environments/staging/charts/boutique-frontend-0.1.0-' + 'a' * 40 + '.tgz')
        self.assertEqual(validation_environments(self.root, self.base), ('staging',))
        self.commit('environments/dev/releases.yaml')
        self.assertEqual(validation_environments(self.root, self.base), ('dev', 'staging'))

    def test_shared_and_unrecognized_changes_require_full_validation(self):
        for path in ['scripts/validate.sh', 'monitoring/values.yaml',
                     'environments/dev/templates/new.yaml', 'laptop-profiles/dev/values.yaml',
                     'environments/dev/charts/unknown.tgz', 'environments/dev/releases.yaml\nextra']:
            with self.subTest(path=path):
                self.git('reset', '--hard', self.base)
                self.commit('environments/staging/releases.yaml')
                self.commit(path)
                self.assertIsNone(validation_environments(self.root, self.base))

    def test_missing_base_empty_diff_and_dirty_checkout_require_full_validation(self):
        self.assertIsNone(validation_environments(self.root))
        self.assertIsNone(validation_environments(self.root, self.base))
        self.commit('environments/dev/releases.yaml')
        self.assertIsNone(validation_environments(self.root, 'missing-ref'))
        (self.root / 'untracked').write_text('not committed')
        self.assertIsNone(validation_environments(self.root, self.base))
        (self.root / 'untracked').unlink()
        (self.root / 'README.md').write_text('not committed')
        self.assertIsNone(validation_environments(self.root, self.base))

    def test_divergent_base_requires_full_validation(self):
        self.commit('environments/dev/releases.yaml')
        other = self.git('rev-parse', 'HEAD').strip()
        self.git('reset', '--hard', self.base)
        self.commit('environments/staging/releases.yaml')
        self.assertIsNone(validation_environments(self.root, other))


if __name__ == '__main__':
    unittest.main()
