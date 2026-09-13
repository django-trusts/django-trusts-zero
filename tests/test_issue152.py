"""#152 Z-docs: live Zero migrates.md is the executable 0.x route."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_TAG_URL = (
    'https://github.com/django-trusts/django-trusts/blob/'
    'migration-archive-pre-1.0/migrates.md'
)
ARCHIVE_SHA_URL = (
    'https://github.com/django-trusts/django-trusts/blob/'
    '7414886263faafb6edfb44c0c5fcf9fc8fa14e79/migrates.md'
)
PRE_CURATION_ZERO = '841004af49687c31c466ed03dbfd4f8ce9c7f153'
CORE_ARCHIVE_BYTES = 211222


class ZeroMigrationRouteTest(SimpleTestCase):
    def test_live_guide_is_executable_route_with_archive_links(self):
        text = (ROOT / 'migrates.md').read_text()
        self.assertIn(ARCHIVE_TAG_URL, text)
        self.assertIn(ARCHIVE_SHA_URL, text)
        self.assertIn(PRE_CURATION_ZERO, text)
        self.assertIn('executable route', text.lower())
        self.assertIn('trusts.zero.apps.ZeroConfig', text)
        self.assertIn('trusts.zero.backends.TrustModelBackend', text)
        self.assertIn('create_trust_root', text)
        self.assertIn('TrustUserPermission.objects.get_or_create', text)
        self.assertIn('grant_trustee', text)
        self.assertIn('handle.register_permission_condition', text)
        self.assertNotIn('# Issue #151 C1', text)
        self.assertNotIn('# Issue #8 recovery', text)
        self.assertNotIn('2.0.0.dev2', text)
        self.assertLess(len(text.encode('utf-8')), CORE_ARCHIVE_BYTES // 4)

    def test_guide_is_packaged(self):
        manifest = (ROOT / 'MANIFEST.in').read_text()
        self.assertIn('include migrates.md', manifest)
        self.assertTrue((ROOT / 'migrates.md').is_file())
