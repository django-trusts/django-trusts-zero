"""Source-tree proofs that Zero does not own kernel paths."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]


KERNEL_OWNED_BASENAMES = (
    '__init__.py',
    'apps.py',
    'context.py',
    'trustee.py',
    'path.py',
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

    def test_zero_python_sources_do_not_import_relocated_kernel_models_path(self):
        """Zero implementation must not import pre-split ``trusts.models``."""
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
