"""Zero Issue #9 Step IIa proofs.

These tests lock the IIa contract against Step I core (``1.0.0.dev2`` /
merge ``39f1f961``):

* ``ZeroConfig`` is the sole implementation owner
* mixin and ``ready()`` never call ``kernel_config()`` when the owner is
  present
* the old core backend path fails at startup
* the core floor belt rejects cores below ``1.0.0.dev2``
* the canonical Zero backend class is not the core historical class
"""

from __future__ import annotations

from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from trusts.apps import (
    TrustsImplementationConfig,
    implementation_configs,
    implementation_for_path,
)
from trusts.zero.apps import (
    CANONICAL_BACKEND,
    LEGACY_CORE_BACKEND,
    ZeroConfig,
    _require_step_i_core,
    zero_config,
)
from trusts.zero.backends import TrustModelBackend


class Issue9StepIIaProofs(SimpleTestCase):
    def test_zero_config_is_sole_implementation_owner(self):
        from trusts.apps import AppConfig as CoreAppConfig

        owners = implementation_configs()
        self.assertEqual(len(owners), 1)
        self.assertIsInstance(owners[0], ZeroConfig)
        self.assertIsInstance(owners[0], TrustsImplementationConfig)
        self.assertIs(owners[0], zero_config())
        self.assertNotIn('trusts_core', apps.app_configs)
        for config in apps.get_app_configs():
            self.assertFalse(type(config) is CoreAppConfig)

    def test_mixin_resolves_owner_without_kernel_config(self):
        def explode():
            raise AssertionError('kernel_config() must not run when an owner is present')

        with patch('trusts.apps.kernel_config', side_effect=explode):
            backend = TrustModelBackend()
            self.assertIs(backend._trusts_config(), zero_config())

    def test_ready_resolves_owner_without_kernel_config(self):
        def explode(*_args, **_kwargs):
            raise AssertionError('kernel_config() must not run from ZeroConfig.ready()')

        with patch('trusts.apps.kernel_config', side_effect=explode):
            owner = implementation_for_path(CANONICAL_BACKEND)
            self.assertIs(owner, zero_config())
            self.assertEqual(
                owner.configured_backend(CANONICAL_BACKEND).path,
                CANONICAL_BACKEND,
            )
            self.assertIs(
                type(owner.configured_backend(CANONICAL_BACKEND).compiler),
                TrustModelBackend.query_compiler.__class__,
            )

class Issue9StepIIaAuthorizationProofs(TestCase):
    def test_list_authorized_resolves_owner_without_kernel_config(self):
        from trusts.zero.models import Trust, TrustUserPermission

        call_command('create_trust_root')
        user = User.objects.create_user('iia-owner', 'iia@example.com', 'x')
        root = Trust.objects.get(pk=1)
        org = Trust(settlor=user, title='IIa Org', trust=root)
        org.save()
        child = Trust(settlor=user, title='IIa Child', trust=org)
        child.save()
        change = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(Trust),
            codename='change_trust',
        )
        TrustUserPermission(trust=org, entity=user, permission=change).save()

        def explode(*_args, **_kwargs):
            raise AssertionError('kernel_config() must not run from ContentQuerySet.authorized()')

        with patch('trusts.apps.kernel_config', side_effect=explode):
            backend = TrustModelBackend()
            self.assertTrue(backend.has_perm(user, 'trusts.change_trust', child))
            permitted = list(Trust.objects.permitted('change', user))
        self.assertIn(child, permitted)

    def test_old_backend_path_fails_at_startup(self):
        config = apps.get_app_config('trusts')
        with override_settings(AUTHENTICATION_BACKENDS=[LEGACY_CORE_BACKEND]):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                ZeroConfig.ready(config)
        message = str(ctx.exception)
        self.assertIn(CANONICAL_BACKEND, message)
        self.assertIn(LEGACY_CORE_BACKEND, message)

    def test_core_floor_belt_rejects_cores_below_dev2(self):
        with patch('importlib.metadata.version', return_value='1.0.0.dev1'):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                _require_step_i_core()
        self.assertIn('1.0.0.dev2', str(ctx.exception))
        self.assertIn('1.0.0.dev1', str(ctx.exception))

    def test_canonical_backend_is_not_core_historical_class(self):
        from trusts.backends import TrustModelBackend as CoreHistoricalBackend

        self.assertIsNot(TrustModelBackend, CoreHistoricalBackend)
        self.assertEqual(
            f'{TrustModelBackend.__module__}.{TrustModelBackend.__qualname__}',
            CANONICAL_BACKEND,
        )
        self.assertEqual(
            f'{CoreHistoricalBackend.__module__}.{CoreHistoricalBackend.__qualname__}',
            LEGACY_CORE_BACKEND,
        )
