"""Zero AppConfig identity on final core (no installed core AppConfig)."""

from django.apps import apps
from django.test import SimpleTestCase

from trusts.apps import TrustsConfigMixin
from trusts.zero.apps import ZeroConfig, zero_config
from tests.apps import ZERO_BACKEND, content_row
from trusts.backends import policy_document
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
        self.assertTrue(issubclass(ZeroConfig, TrustsConfigMixin))
        owner = zero_config()
        self.assertIs(owner, apps.get_app_config('trusts'))
        document = policy_document(backend=ZERO_BACKEND)
        self.assertEqual(document['schema_version'], 1)
        self.assertEqual(document['backends'][0]['path'], 'trusts.zero.apps.ZeroConfig')
        self.assertEqual(content_row(Trust, ZERO_BACKEND)['model'], 'trusts.Trust')

    def test_trusts_label_is_only_zeroconfig(self):
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
