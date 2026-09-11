"""Zero IIa AppConfig and implementation-owner tests.

Zero owns ``trusts.zero.backends.TrustModelBackend`` through
``ZeroConfig``. Core's ``AppConfig`` is not installed. Host apps donate
through ``implementation_for_path``, never ``kernel_config()``.
"""

from __future__ import annotations

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from tests.models import Category, Ticket
from trusts.apps import TrustsImplementationConfig, implementation_for_path
from trusts.zero.apps import CANONICAL_BACKEND, ZeroConfig, zero_config
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Role, Trust, TrustGroup, TrustUserPermission


class ZeroAppConfigTests(SimpleTestCase):
    def test_zero_config_is_installed_implementation(self):
        config = apps.get_app_config('trusts')
        self.assertIsInstance(config, ZeroConfig)
        self.assertIsInstance(config, TrustsImplementationConfig)
        self.assertEqual(config.name, 'trusts.zero')
        self.assertEqual(config.label, 'trusts')
        self.assertEqual(config.verbose_name, 'Django Trusts Zero')
        self.assertEqual(config.default_auto_field, 'django.db.models.AutoField')
        self.assertEqual(
            config.trusts_backend_paths,
            (CANONICAL_BACKEND,),
        )

    def test_core_appconfig_is_not_installed(self):
        from trusts.apps import AppConfig as CoreAppConfig

        self.assertNotIn('trusts_core', apps.app_configs)
        for config in apps.get_app_configs():
            self.assertFalse(type(config) is CoreAppConfig)
            self.assertNotEqual(getattr(config, 'label', None), 'trusts_core')

    def test_zero_config_is_the_sole_implementation_owner(self):
        from trusts.apps import implementation_configs

        owners = implementation_configs()
        self.assertEqual(len(owners), 1)
        self.assertIsInstance(owners[0], ZeroConfig)
        self.assertIs(implementation_for_path(CANONICAL_BACKEND), owners[0])

    def test_kernel_config_is_not_the_implementation_owner(self):
        from trusts.apps import kernel_config

        with self.assertRaises(LookupError):
            kernel_config()

    def test_zero_config_helper_returns_installed_owner(self):
        self.assertIs(zero_config(), apps.get_app_config('trusts'))

    def test_zero_models_are_registered_under_label_trusts(self):
        for model in (Trust, Role, TrustGroup, TrustUserPermission):
            self.assertEqual(model._meta.app_label, 'trusts')
            self.assertIs(apps.get_model('trusts', model.__name__), model)

    def test_zero_models_are_not_registered_under_trusts_core(self):
        with self.assertRaises(LookupError):
            apps.get_model('trusts_core', 'Role')

    def test_zero_config_exposes_runtime_registries(self):
        config = zero_config()
        self.assertIn(CANONICAL_BACKEND, config.registries)
        registry = config.registries[CANONICAL_BACKEND]
        self.assertTrue(hasattr(registry, 'register'))
        self.assertTrue(hasattr(registry, 'records'))

    def test_canonical_backend_class_is_not_core_historical_class(self):
        from trusts.backends import TrustModelBackend as CoreHistoricalBackend

        self.assertIsNot(TrustModelBackend, CoreHistoricalBackend)
        self.assertEqual(
            f'{TrustModelBackend.__module__}.{TrustModelBackend.__qualname__}',
            CANONICAL_BACKEND,
        )

    def test_exactly_one_trust_model_under_historical_label(self):
        from trusts.zero.models import Trust

        trusts = [m for m in apps.get_models() if m.__name__ == 'Trust']
        self.assertEqual(len(trusts), 1)
        self.assertIs(trusts[0], Trust)
        self.assertEqual(Trust._meta.app_label, 'trusts')
        self.assertIs(apps.get_model('trusts', 'Trust'), Trust)

    def test_migrations_package_is_zero_owned(self):
        config = apps.get_app_config('trusts')
        self.assertEqual(config.module.__name__, 'trusts.zero')
        import trusts.zero.migrations as migrations_pkg
        self.assertTrue(
            migrations_pkg.__file__.endswith('trusts/zero/migrations/__init__.py')
        )

    def test_kernel_package_is_not_the_django_app(self):
        import trusts
        from trusts.zero.models import Trust

        self.assertEqual(Trust._meta.app_label, 'trusts')
        self.assertTrue(hasattr(trusts, '__file__'))
        self.assertFalse(trusts.__file__.endswith('trusts/zero/__init__.py'))


class ZeroStartupGateTests(SimpleTestCase):
    def test_old_core_backend_path_is_rejected(self):
        config = apps.get_app_config('trusts')
        with override_settings(
            AUTHENTICATION_BACKENDS=['trusts.backends.TrustModelBackend'],
        ):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                ZeroConfig.ready(config)
        self.assertIn('trusts.zero.backends.TrustModelBackend', str(ctx.exception))
        self.assertIn('trusts.backends.TrustModelBackend', str(ctx.exception))


class ZeroHostDonationTests(TestCase):
    def test_host_app_donates_through_implementation_for_path(self):
        owner = implementation_for_path(CANONICAL_BACKEND)
        self.assertIsInstance(owner, ZeroConfig)
        handle = owner.configured_backend(CANONICAL_BACKEND)
        content_models = {
            row.content_model
            for row in handle.registry.records_for_root(TrustUserPermission)
        }
        self.assertIn(Category, content_models)
        self.assertIn(Ticket, content_models)
        self.assertIn(Trust, content_models)
