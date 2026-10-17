"""Reusing a render must preserve image checks and avoid rendering it again."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_rendered_images import check_profile
from release_config import ReleaseError
from render import render


class RenderedValidationTests(unittest.TestCase):
    def test_saved_render_is_checked_without_rendering_application_again(self):
        for profile, parent in [('cloud', 'environments'),
                                ('laptop', 'laptop-profiles')]:
            with self.subTest(profile=profile):
                manifest = render(ROOT, 'dev', profile)
                with patch('check_rendered_images.render', side_effect=AssertionError('Duplicate render')):
                    self.assertEqual(check_profile(ROOT, parent + '/dev', 'dev', rendered=manifest),
                                     parent + '/dev')

    def test_saved_render_still_rejects_an_unselected_image(self):
        resources = list(yaml.safe_load_all(render(ROOT, 'dev', 'cloud')))
        deployment = next(item for item in resources if item and item['kind'] == 'Deployment'
                          and item['metadata']['name'] == 'frontend')
        deployment['spec']['template']['spec']['containers'][0]['image'] = 'unreviewed:latest'
        with self.assertRaisesRegex(ReleaseError, 'bypasses its Helm release selection'):
            check_profile(ROOT, 'environments/dev', 'dev', rendered=yaml.safe_dump_all(resources))

    def test_saved_render_requires_environment_and_profile(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_rendered_images.py'),
                                 '--rendered-file', 'unused.yaml'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('must be supplied together', result.stderr)


if __name__ == '__main__':
    unittest.main()
