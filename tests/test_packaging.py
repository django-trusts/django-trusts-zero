"""Source-tree proofs that Zero does not own kernel paths or copy compilers."""

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
        self.assertIn('class HistoricalGroupQueryCompiler', backends)
        self.assertIn('class TrustModelBackend', backends)
        self.assertNotIn('from trusts.backends import TrustModelBackend\n', backends)
        self.assertNotIn('TrustModelBackend = ', backends)


class ZeroPublishMetadataTests(SimpleTestCase):
    def test_pyproject_requires_core_dev3_floor(self):
        text = (ROOT / 'pyproject.toml').read_text()
        self.assertIn('name = "django-trusts-zero"', text)
        self.assertIn('version = "1.0.0.dev0"', text)
        self.assertIn('"django-trusts>=1.0.0.dev3,<2"', text)
        self.assertIn('"Django>=6.1,<6.2"', text)
        req = (ROOT / 'requirements.txt').read_text()
        self.assertIn('11058641b533e0f8489598e0b1f5cbe5d42a81db', req)
        ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
        self.assertIn(
            'COMPANION_KERNEL_SHA: 11058641b533e0f8489598e0b1f5cbe5d42a81db',
            ci,
        )
