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

    def test_readme_names_executable_zero_route(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("executable 0.x → Zero route", readme)
        rst = (ROOT / "docs" / "source" / "index.rst").read_text()
        self.assertIn("executable 0.x → Zero route", rst)
        self.assertIn("django-trusts/blob/dev/docs/source/index.rst", rst)


class ZeroMigratesRouteTest(SimpleTestCase):
    """#152 Z-docs-r1: live guide is the executable route plus archive URLs."""

    CORE_ARCHIVE_BYTES = 211222
    TAG_URL = (
        "https://github.com/django-trusts/django-trusts/blob/"
        "migration-archive-pre-1.0/migrates.md"
    )
    SHA_URL = (
        "https://github.com/django-trusts/django-trusts/blob/"
        "7414886263faafb6edfb44c0c5fcf9fc8fa14e79/migrates.md"
    )
    PRE_CURATION_ZERO = "841004af49687c31c466ed03dbfd4f8ce9c7f153"

    def test_live_guide_is_executable_route_with_archaeology(self):
        path = ROOT / "migrates.md"
        text = path.read_text()
        size = path.stat().st_size

        self.assertIn(self.TAG_URL, text)
        self.assertIn(self.SHA_URL, text)
        self.assertIn(self.PRE_CURATION_ZERO, text)
        self.assertIn("executable 0.x → Zero route", text)
        self.assertIn("'trusts.zero.apps.ZeroConfig'", text)
        self.assertIn("trusts.zero.backends.TrustModelBackend", text)
        self.assertIn("from trusts.zero.models import", text)
        self.assertIn("0001_initial", text)
        self.assertIn("0002_trustgroup", text)
        self.assertIn("django-trusts>=1.0.0.dev3,<2", text)
        self.assertIn("trusts.conditions._ir", text)
        self.assertIn("set_condition_lookup", text)
        self.assertIn("include('trusts.zero.urls')", text)
        self.assertIn("create_trust_root", text)
        self.assertIn("grandfather_trust_group_permissions", text)
        self.assertIn("update_roles_permissions", text)
        self.assertLess(
            size,
            self.CORE_ARCHIVE_BYTES // 2,
            "live migrates.md must stay far below the Core archive "
            "(%s bytes, got %s)" % (self.CORE_ARCHIVE_BYTES, size),
        )
        for banned in (
            "# Issue #151 C1",
            "# Issue #8 recovery",
            "2.0.0.dev2",
            "# Zero #151 Z2",
            "# Zero #18",
            "# Zero #16",
            "# Archived: unpublished internal staircase",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, text)

    def test_zero_tree_does_not_vendor_core_archive(self):
        manifest = (ROOT / "MANIFEST.in").read_text()
        self.assertIn("include migrates.md", manifest)
        vendored = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("migrates.md")
            if path.resolve() != (ROOT / "migrates.md").resolve()
            and "site-packages" not in path.as_posix()
            and "/.deps/" not in path.as_posix()
        ]
        self.assertEqual(vendored, [])

    def test_ready_example_resolves_owner_on_the_public_api(self):
        text = (ROOT / "migrates.md").read_text()
        heading = text.index("## Conditions (current rule)")
        fence_start = text.index("```python", heading)
        example = text[fence_start + len("```python") : text.index("```", fence_start + 9)]
        ready = example.split("def ready(self):", 1)[1]

        self.assertIn("from django.apps import AppConfig", example)
        self.assertIn("from trusts.apps import implementation_for_path", example)
        self.assertIn("from trusts.zero.apps import CANONICAL_BACKEND_PATH", example)
        self.assertIn(
            "owner = implementation_for_path(\n"
            "            CANONICAL_BACKEND_PATH, apps_registry=self.apps,",
            example,
        )
        self.assertIn("handle = owner.configured_backend(CANONICAL_BACKEND_PATH)", ready)
        self.assertIn("handle.register_permission_condition", ready)
        self.assertLess(
            ready.index("owner = implementation_for_path"),
            ready.index("owner.configured_backend"),
        )
        self.assertNotIn("set_condition_lookup", example)
        self.assertNotIn("conditions._ir", example)
