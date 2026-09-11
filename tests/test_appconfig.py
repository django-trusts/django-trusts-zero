"""Zero AppConfig identity on final core (no installed core AppConfig)."""

from django.apps import apps
from django.test import SimpleTestCase

from trusts.apps import (
    TrustsImplementationConfig,
    implementation_configs,
    implementation_for_class,
    implementation_for_path,
)
from trusts.zero.apps import CANONICAL_BACKEND_PATH, ZeroConfig, zero_config
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust


class ZeroAppConfigTests(SimpleTestCase):
    def test_name_is_package_path_and_label_is_historical(self):
        config = apps.get_app_config('trusts')
        self.assertIsInstance(config, ZeroConfig)
        self.assertEqual(config.name, 'trusts.zero')
        self.assertEqual(config.label, 'trusts')
        self.assertEqual(
            config.default_auto_field,
            'django.db.models.AutoField',
        )

    def test_zero_config_is_the_implementation_owner(self):
        self.assertTrue(issubclass(ZeroConfig, TrustsImplementationConfig))
        owners = implementation_configs()
        self.assertEqual(len(owners), 1)
        self.assertIs(owners[0], zero_config())
        self.assertIs(owners[0], apps.get_app_config('trusts'))
        self.assertEqual(
            owners[0].trusts_backend_paths, (CANONICAL_BACKEND_PATH,),
        )
        self.assertIs(
            implementation_for_path(CANONICAL_BACKEND_PATH), owners[0],
        )
        self.assertIs(
            implementation_for_class(TrustModelBackend), owners[0],
        )

    def test_core_ships_no_appconfig_or_kernel_config(self):
        import trusts.apps as trusts_apps

        self.assertFalse(hasattr(trusts_apps, 'kernel_config'))
        self.assertFalse(hasattr(trusts_apps, 'AppConfig'))
        with self.assertRaises(ImportError):
            from trusts.apps import kernel_config  # noqa: F401
        with self.assertRaises(ImportError):
            from trusts.apps import AppConfig  # noqa: F401
        self.assertIs(type(apps.get_app_config('trusts')), ZeroConfig)
        self.assertEqual(
            [type(config) for config in apps.get_app_configs() if config.label == 'trusts'],
            [ZeroConfig],
        )

    def test_exactly_one_trust_model_under_historical_label(self):
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

        self.assertEqual(Trust._meta.app_label, 'trusts')
        self.assertTrue(hasattr(trusts, '__file__'))
        self.assertFalse(trusts.__file__.endswith('trusts/zero/__init__.py'))
