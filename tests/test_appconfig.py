"""Zero AppConfig identity: package path vs historical Django label."""

from django.apps import apps
from django.test import SimpleTestCase

from trusts.zero.apps import ZeroConfig


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

    def test_migrations_package_is_zero_owned(self):
        config = apps.get_app_config('trusts')
        self.assertEqual(config.name, 'trusts.zero')
        self.assertEqual(config.module.__name__, 'trusts.zero')
        import trusts.zero.migrations as migrations_pkg
        self.assertTrue(migrations_pkg.__file__.endswith('trusts/zero/migrations/__init__.py'))

    def test_kernel_package_is_not_the_django_app(self):
        """The kernel import package stays ``trusts``; the Django app is Zero."""
        import trusts
        from trusts.zero.models import Trust

        self.assertNotEqual(Trust._meta.app_label, 'trusts_kernel')
        self.assertEqual(Trust._meta.app_label, 'trusts')
        self.assertTrue(hasattr(trusts, '__file__'))
        # Zero must not ship or overwrite the kernel package init.
        self.assertFalse(trusts.__file__.endswith('trusts/zero/__init__.py'))
