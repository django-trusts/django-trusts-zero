from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]


class ZeroDocumentationSurfaceTest(SimpleTestCase):
    def test_rst_describes_current_zero_surface(self):
        rst = (ROOT / "docs" / "source" / "index.rst").read_text()

        forbidden = (
            "trust_grant_q",
            "historical_group_grant_exists",
            "HistoricalGroupQueryCompiler",
            "kernel_config",
            "from trusts.models import",
            "from trusts.backends import TrustModelBackend",
            "Content.grant",
            "Trust.associate_group",
            "TrustGroup.grant_permission",
            "948d666",
            "a0104be",
            "809d7c1",
            "31f9a586",
            "IIa",
            "C1",
            "Z1",
            "r7",
            "pair pin",
            "baton",
        )
        self.assertEqual([name for name in forbidden if name in rst], [])

        required = (
            "pip install django-trusts-zero",
            "trusts.zero.apps.ZeroConfig",
            "trusts.zero.backends.TrustModelBackend",
            "from trusts.zero.models import",
            "PlanQueryCompiler",
            "granted",
            "filter_authorized_scopes",
            "register_zero_content",
            "trusts.zero.urls",
            "2015--2026",
            "blob/dev/migrates.md",
            "django-trusts/blob/dev/docs/source/index.rst",
        )
        for name in required:
            with self.subTest(name=name):
                self.assertIn(name, rst)

    def test_sphinx_and_package_metadata_point_to_current_docs(self):
        conf = (ROOT / "docs" / "source" / "conf.py").read_text()
        self.assertIn('project = "django-trusts-zero"', conf)
        self.assertIn('author = "BeeDesk, Inc."', conf)
        self.assertIn('copyright = "2015-2026, BeeDesk, Inc."', conf)
        self.assertIn('version = "1.0.0.dev0"', conf)

        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertIn(
            'Documentation = "https://github.com/django-trusts/'
            'django-trusts-zero/blob/dev/docs/source/index.rst"',
            pyproject,
        )
        self.assertIn(
            'Core = "https://github.com/django-trusts/django-trusts"',
            pyproject,
        )
        self.assertIn(
            'Migration = "https://github.com/django-trusts/'
            'django-trusts-zero/blob/dev/migrates.md"',
            pyproject,
        )
        for stale in ("Issue 9", "Kernel =", "readthedocs.org", "blob/master/"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, pyproject)
