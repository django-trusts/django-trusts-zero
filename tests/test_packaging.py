"""Source-tree proofs that Zero does not own kernel paths or copy compilers."""

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]


KERNEL_OWNED_BASENAMES = (
    '__init__.py',
    'apps.py',
    'core.py',
    'query.py',
    'conditions.py',
    'models.py',
    'backends.py',
    'admin.py',
)


class ZeroSourceLayoutTests(SimpleTestCase):
    def test_repo_does_not_ship_kernel_owned_trusts_init(self):
        trusts_dir = ROOT / 'trusts'
        self.assertTrue((trusts_dir / 'zero' / '__init__.py').is_file())
        self.assertFalse(
            (trusts_dir / '__init__.py').exists(),
            'Zero must not ship trusts/__init__.py (kernel RECORD / uninstall ownership)',
        )

    def test_zero_package_does_not_duplicate_kernel_module_names_at_trusts_root(self):
        trusts_dir = ROOT / 'trusts'
        for name in KERNEL_OWNED_BASENAMES:
            self.assertFalse(
                (trusts_dir / name).exists(),
                'Zero must not ship kernel-owned path trusts/%s' % name,
            )

    def test_zero_python_sources_do_not_import_pre_split_kernel_models(self):
        offenders = []
        for path in (ROOT / 'trusts' / 'zero').rglob('*.py'):
            text = path.read_text()
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if 'from trusts.models' in stripped or stripped == 'import trusts.models':
                    offenders.append('%s: %s' % (path.relative_to(ROOT), stripped))
        self.assertEqual(offenders, [])

    def test_zero_does_not_copy_generic_authorization_control_flow(self):
        """No local granted/compose/filter_authorized. Compiler lives in backends."""
        banned = (
            'def granted(',
            'def compose(',
            'def filter_authorized(',
            'from trusts.path import',
            'from trusts.runtime import',
            'from trusts.context import',
            'from trusts.trustee import',
            'def grant(self, perm, user)',
            'def associate_group(self, group)',
            'def grant_group_permission(',
            'def grant_permission(self, permission)',
        )
        offenders = []
        for path in (ROOT / 'trusts' / 'zero').rglob('*.py'):
            if path.name == 'backends.py':
                continue
            text = path.read_text()
            for needle in banned:
                if needle in text:
                    offenders.append('%s: %s' % (path.relative_to(ROOT), needle))
            if 'class HistoricalGroupQueryCompiler' in text:
                offenders.append(
                    '%s: class HistoricalGroupQueryCompiler' % path.relative_to(ROOT)
                )
        self.assertEqual(offenders, [])
        backends = (ROOT / 'trusts' / 'zero' / 'backends.py').read_text()
        self.assertNotIn('class HistoricalGroupQueryCompiler', backends)
        self.assertIn('PlanQueryCompiler', backends)
        self.assertIn('class TrustModelBackend', backends)
        self.assertNotIn('from trusts.backends import TrustModelBackend\n', backends)
        self.assertNotIn('TrustModelBackend = ', backends)

    def test_no_test_modules_under_installable_zero_package(self):
        zero_dir = ROOT / 'trusts' / 'zero'
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in zero_dir.rglob('*.py')
            if path.name == 'tests.py' or path.name.startswith('test_')
            or path.parent.name in {'tests', 'test'}
        ]
        self.assertEqual(offenders, [])
        self.assertIsNone(importlib.util.find_spec('trusts.zero.tests'))
        # Core still ships trusts/tests.py until STAGE 2. Pair CI puts
        # KERNEL_CHECKOUT on sys.path, so find_spec('trusts.tests') may
        # resolve to the paired core module. Assert only that this Zero
        # tree does not ship it.
        spec = importlib.util.find_spec('trusts.tests')
        if spec is not None:
            origin = spec.origin or ''
            self.assertFalse(
                origin.startswith(str(ROOT / 'trusts')),
                'Zero must not ship trusts.tests; found %s' % origin,
            )
        self.assertTrue((ROOT / 'tests' / 'legacy' / 'test_historical.py').is_file())
        self.assertFalse((ROOT / 'trusts' / 'tests.py').exists())
        self.assertFalse((ROOT / 'trusts' / 'zero' / 'tests.py').exists())


class ZeroPublishMetadataTests(SimpleTestCase):
    def test_pyproject_requires_final_core_floor(self):
        text = (ROOT / 'pyproject.toml').read_text()
        self.assertIn('name = "django-trusts-zero"', text)
        self.assertIn('version = "1.0.0.dev0"', text)
        self.assertIn('"django-trusts>=1.0.0.dev3,<2"', text)
        self.assertIn('"Django>=6.1,<6.2"', text)
        self.assertIn('readme = "README.md"', text)
        self.assertNotIn('readme = "DEV.md"', text)
        self.assertIn('license = "BSD-2-Clause"', text)
        req = (ROOT / 'requirements.txt').read_text()
        self.assertIn('a0104be138f5fbcc7d74ce1fce8054c3e1e89634', req)
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
        self.assertIn(
            'COMPANION_KERNEL_SHA: a0104be138f5fbcc7d74ce1fce8054c3e1e89634',
            ci,
        )

    def test_license_notice_is_beedesk_2015_2026(self):
        text = (ROOT / 'LICENSE').read_text()
        self.assertIn('Copyright (c) 2015-2026, BeeDesk, Inc.', text)
        self.assertNotIn('and contributors', text.split('THIS SOFTWARE')[0])
        self.assertIn('BSD-2-Clause', (ROOT / 'pyproject.toml').read_text())

    def test_user_readme_is_not_internal_status(self):
        readme = (ROOT / 'README.md').read_text()
        forbidden = (
            'IIa',
            'Step I',
            'Step II',
            'Step III',
            'C1',
            'C2',
            'Z1',
            'pair pin',
            'baton',
            '2.0.0.dev',
            '1.0.0.dev2',
            '1.0.0.dev3',
            '11058641',
            '39f1f961',
            '94e0fa1',
            'code budget',
            'kernel_config',
        )
        offenders = [needle for needle in forbidden if needle in readme]
        self.assertEqual(offenders, [])
        self.assertIn('pip install django-trusts-zero', readme)
        self.assertIn(
            'from trusts.zero.models import Trust, Content, Junction, TrustUserPermission',
            readme,
        )
        self.assertIn('from trusts.zero.backends import TrustModelBackend', readme)
        self.assertIn("'trusts.zero.apps.ZeroConfig'", readme)
        self.assertIn("'trusts.zero.backends.TrustModelBackend'", readme)
        self.assertIn("Do **not** add `'trusts'` to `INSTALLED_APPS`", readme)
        self.assertIn('migrates.md', readme)
        dev = (ROOT / 'DEV.md').read_text()
        self.assertIn('internal', dev[:800].lower())
        self.assertIn('transitional', dev[:800].lower())

    def test_readme_examples_match_verified_settings(self):
        settings_text = (ROOT / 'tests' / 'settings.py').read_text()
        self.assertIn("'trusts.zero.apps.ZeroConfig'", settings_text)
        self.assertIn("'trusts.zero.backends.TrustModelBackend'", settings_text)
        self.assertNotIn("'trusts',", settings_text.replace("'trusts.zero", ''))
