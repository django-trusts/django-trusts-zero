"""Zero-owned AppConfig and canonical backend on django-trusts 1.0.0rc1."""

import os
import subprocess
import sys
from pathlib import Path

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from tests.apps import ZERO_BACKEND, content_row
from trusts.backends import TrustModelBackendMixin, policy_document
from trusts.errors import TrustsMixinRequired
from trusts.zero.apps import (
    CANONICAL_BACKEND_PATH,
    DEPRECATED_CORE_BACKEND_PATH,
    ZeroConfig,
    zero_config,
)
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust, TrustUserPermission


ROOT = Path(__file__).resolve().parents[1]
KERNEL = Path(os.environ.get('KERNEL_CHECKOUT', ROOT / '.deps' / 'django-trusts')).resolve()


STARTUP_PROBE = r'''
import os, sys
from pathlib import Path
root = Path(%r).resolve()
kernel = Path(%r).resolve()
sys.path.insert(0, str(kernel))
sys.path.append(str(root))
os.environ.pop("DJANGO_SETTINGS_MODULE", None)
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
settings.configure(
    SECRET_KEY="iia-startup",
    USE_TZ=True,
    DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "trusts.zero.apps.ZeroConfig",
    ],
    AUTHENTICATION_BACKENDS=%r,
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
import django
try:
    django.setup()
except ImproperlyConfigured as exc:
    print("improperly-configured", exc)
    raise SystemExit(0)
print("populate-succeeded")
raise SystemExit(1)
'''


class CanonicalBackendIdentityTests(SimpleTestCase):
    def test_zero_backend_is_the_canonical_mixin_subclass(self):
        self.assertTrue(issubclass(TrustModelBackend, TrustModelBackendMixin))
        document = policy_document(backend=ZERO_BACKEND)
        self.assertEqual(document['backends'][0]['path'], 'trusts.zero.apps.ZeroConfig')
        self.assertEqual(content_row(Trust, ZERO_BACKEND)['model'], 'trusts.Trust')

    def test_canonical_path_resolves_only_through_zeroconfig(self):
        owner = zero_config()
        self.assertIs(type(owner), ZeroConfig)
        document = policy_document(backend=CANONICAL_BACKEND_PATH)
        self.assertEqual(len(document['backends']), 1)
        self.assertEqual(document['backends'][0]['path'], 'trusts.zero.apps.ZeroConfig')

    def test_unconfigured_mixin_class_is_not_zero_identity(self):
        with self.assertRaises(TrustsMixinRequired):
            TrustModelBackendMixin()


class OwnerPresentOnFinalCoreTests(SimpleTestCase):
    def test_zero_config_helper_returns_installed_owner(self):
        self.assertIs(type(zero_config()), ZeroConfig)


class StartupBeltTests(SimpleTestCase):
    def test_old_backend_path_alone_fails_startup(self):
        result = subprocess.run(
            [
                sys.executable, '-c',
                STARTUP_PROBE % (
                    str(ROOT), str(KERNEL),
                    [DEPRECATED_CORE_BACKEND_PATH],
                ),
            ],
            cwd=str(ROOT),
            env={k: v for k, v in os.environ.items() if k != 'DJANGO_SETTINGS_MODULE'},
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            'old-path gate failed:\nstdout=%s\nstderr=%s' % (
                result.stdout, result.stderr,
            ),
        )
        self.assertIn('improperly-configured', result.stdout)
        self.assertIn(CANONICAL_BACKEND_PATH, result.stdout)
        self.assertIn(DEPRECATED_CORE_BACKEND_PATH, result.stdout)

    def test_both_backend_paths_fail_startup(self):
        result = subprocess.run(
            [
                sys.executable, '-c',
                STARTUP_PROBE % (
                    str(ROOT), str(KERNEL),
                    [CANONICAL_BACKEND_PATH, DEPRECATED_CORE_BACKEND_PATH],
                ),
            ],
            cwd=str(ROOT),
            env={k: v for k, v in os.environ.items() if k != 'DJANGO_SETTINGS_MODULE'},
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            'both-paths gate failed:\nstdout=%s\nstderr=%s' % (
                result.stdout, result.stderr,
            ),
        )
        self.assertIn('improperly-configured', result.stdout)
        self.assertIn(DEPRECATED_CORE_BACKEND_PATH, result.stdout)

    def test_missing_canonical_path_fails_startup(self):
        result = subprocess.run(
            [
                sys.executable, '-c',
                STARTUP_PROBE % (
                    str(ROOT), str(KERNEL),
                    ['django.contrib.auth.backends.ModelBackend'],
                ),
            ],
            cwd=str(ROOT),
            env={k: v for k, v in os.environ.items() if k != 'DJANGO_SETTINGS_MODULE'},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('improperly-configured', result.stdout)
        self.assertIn(CANONICAL_BACKEND_PATH, result.stdout)

    def test_canonical_settings_start(self):
        result = subprocess.run(
            [
                sys.executable, '-c',
                STARTUP_PROBE % (
                    str(ROOT), str(KERNEL),
                    [CANONICAL_BACKEND_PATH],
                ),
            ],
            cwd=str(ROOT),
            env={k: v for k, v in os.environ.items() if k != 'DJANGO_SETTINGS_MODULE'},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('populate-succeeded', result.stdout)


class AuthorizationThroughZeroBackendTests(TestCase):
    def setUp(self):
        call_command('create_trust_root')
        self.user = User.objects.create_user('daniel', 'daniel@example.com', 'pass')
        self.other = User.objects.create_user('other', 'other@example.com', 'pass')
        self.root = Trust.objects.get(pk=1)
        self.org = Trust(settlor=self.user, title='Org', trust=self.root)
        self.org.save()
        self.child = Trust(settlor=self.user, title='Child', trust=self.org)
        self.child.save()
        self.isolated = Trust(settlor=self.other, title='OtherOrg', trust=self.root)
        self.isolated.save()
        ct = ContentType.objects.get_for_model(Trust)
        from django.contrib.auth.models import Permission
        self.change = Permission.objects.get(content_type=ct, codename='change_trust')
        TrustUserPermission(
            trust=self.org, entity=self.user, permission=self.change,
        ).save()

    def test_has_perm_and_permitted_resolve_through_zero_owner(self):
        user = User.objects.get(pk=self.user.pk)
        child = Trust.objects.get(pk=self.child.pk)
        self.assertTrue(user.has_perm('trusts.change_trust', child))
        permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(child, permitted)

    def test_fixed_query_counts_for_object_and_list(self):
        user = User.objects.get(pk=self.user.pk)
        child = Trust.objects.get(pk=self.child.pk)
        with self.assertNumQueries(1):
            self.assertTrue(user.has_perm('trusts.change_trust', child))
        with self.assertNumQueries(2):
            list(Trust.objects.permitted('change', user))
