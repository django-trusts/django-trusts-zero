"""#9 Step IIa: Zero-owned AppConfig and canonical backend (2.0.0.dev2)."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from trusts.apps import (
    TrustsImplementationConfig,
    implementation_for_class,
    implementation_for_path,
    kernel_config,
)
from trusts.backends import TrustModelBackend as CoreHistoricalBackend
from trusts.backends import TrustModelBackendMixin
from trusts.zero.apps import (
    CANONICAL_BACKEND_PATH,
    DEPRECATED_CORE_BACKEND_PATH,
    FLOOR_MESSAGE,
    ZeroConfig,
    zero_config,
)
from trusts.zero.backends import (
    HistoricalGroupQueryCompiler,
    TrustModelBackend,
)
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
    def test_zero_backend_is_distinct_from_core_historical_class(self):
        self.assertIsNot(TrustModelBackend, CoreHistoricalBackend)
        self.assertTrue(issubclass(TrustModelBackend, TrustModelBackendMixin))
        self.assertTrue(issubclass(TrustModelBackend, object))
        self.assertIsInstance(
            TrustModelBackend.query_compiler, HistoricalGroupQueryCompiler,
        )
        core_compiler = type(CoreHistoricalBackend.query_compiler)
        self.assertIsNot(HistoricalGroupQueryCompiler, core_compiler)
        self.assertTrue(TrustModelBackend.query_compiler.historical_fallback)

    def test_canonical_path_resolves_only_through_zeroconfig(self):
        owner = implementation_for_path(CANONICAL_BACKEND_PATH)
        self.assertIs(type(owner), ZeroConfig)
        self.assertIs(owner, zero_config())
        self.assertIs(implementation_for_class(TrustModelBackend), owner)
        handle = owner.configured_backend(CANONICAL_BACKEND_PATH)
        self.assertEqual(handle.path, CANONICAL_BACKEND_PATH)
        self.assertIs(handle.registry, owner.registries[CANONICAL_BACKEND_PATH])

    def test_core_historical_class_is_not_zero_identity(self):
        from trusts.core import TrustsConfigurationError

        with self.assertRaises(TrustsConfigurationError):
            implementation_for_class(CoreHistoricalBackend)


class OwnerPresentNeverCallsKernelTests(SimpleTestCase):
    def test_zero_config_ready_does_not_call_kernel_config(self):
        owner = zero_config()
        with patch('trusts.apps.kernel_config') as kernel:
            owner.ready()
            kernel.assert_not_called()

    def test_mixin_owner_present_never_calls_kernel_config(self):
        backend = TrustModelBackend()
        with patch('trusts.apps.kernel_config') as kernel:
            config = backend._trusts_config()
            self.assertIs(type(config), ZeroConfig)
            self.assertIs(config, zero_config())
            kernel.assert_not_called()
            handle = backend._own_handle()
            self.assertEqual(handle.path, CANONICAL_BACKEND_PATH)

    def test_zero_config_helper_does_not_call_kernel_config(self):
        with patch('trusts.apps.kernel_config') as kernel:
            self.assertIs(type(zero_config()), ZeroConfig)
            kernel.assert_not_called()

    def test_live_kernel_config_is_absent(self):
        with self.assertRaises(LookupError):
            kernel_config()


class StartupBeltTests(SimpleTestCase):
    def test_missing_step_i_helper_is_improperly_configured(self):
        import trusts.zero.apps as zero_apps

        config = apps.get_app_config('trusts')
        with patch.object(zero_apps, 'TrustsImplementationConfig', None):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                config.ready()
        self.assertIn('1.0.0.dev2', str(ctx.exception))
        self.assertIn('TrustsImplementationConfig', str(ctx.exception))
        self.assertEqual(str(ctx.exception), FLOOR_MESSAGE)

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

    def test_has_perm_and_permitted_never_call_kernel_config(self):
        user = User.objects.get(pk=self.user.pk)
        child = Trust.objects.get(pk=self.child.pk)
        with patch('trusts.apps.kernel_config') as kernel:
            self.assertTrue(user.has_perm('trusts.change_trust', child))
            permitted = list(Trust.objects.permitted('change', user))
            self.assertIn(child, permitted)
            kernel.assert_not_called()

    def test_fixed_query_counts_for_object_and_list(self):
        user = User.objects.get(pk=self.user.pk)
        child = Trust.objects.get(pk=self.child.pk)
        with self.assertNumQueries(1):
            self.assertTrue(user.has_perm('trusts.change_trust', child))
        with self.assertNumQueries(2):
            list(Trust.objects.permitted('change', user))
