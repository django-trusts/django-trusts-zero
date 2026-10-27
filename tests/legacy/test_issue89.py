"""A second ``ready()`` does not register again.

Registration is logged at model import. The first policy question
freezes that log.
"""

from django.apps import apps
from django.core.checks import run_checks
from django.test import SimpleTestCase

from tests.apps import TEST_BACKEND, ZERO_BACKEND, trust_rows
from tests.backends import TestsBackend
from tests.models import Category
from trusts.errors import TrustsConfigurationError
from trusts.zero.apps import zero_config
from trusts.zero.backends import TrustModelBackend
from trusts.zero.models import Trust


class RegistryReadyTest(SimpleTestCase):
    def test_second_tests_ready_keeps_the_policy(self):
        before = trust_rows(Category, backend=TEST_BACKEND)
        apps.get_app_config('trusts_zero_tests').ready()
        self.assertEqual(trust_rows(Category, backend=TEST_BACKEND), before)
        with self.assertRaises(TrustsConfigurationError):
            TestsBackend().get_registry().add_named_filter(
                Category, 'late', lambda u, p, o: False,
            )
        self.assertEqual(trust_rows(Category, backend=TEST_BACKEND), before)

    def test_second_zero_ready_keeps_the_policy(self):
        before = trust_rows(Trust, backend=ZERO_BACKEND)
        zero_config().ready()
        self.assertEqual(trust_rows(Trust, backend=ZERO_BACKEND), before)
        with self.assertRaises(TrustsConfigurationError):
            TrustModelBackend().get_registry().add_named_filter(
                Trust, 'late', lambda u, p, o: u == o.settlor,
            )
        self.assertEqual(trust_rows(Trust, backend=ZERO_BACKEND), before)

    def test_run_checks_has_no_e001(self):
        ids = [message.id for message in run_checks()]
        self.assertNotIn('trusts.E001', ids)
        self.assertTrue(trust_rows('trusts.Trust', backend=ZERO_BACKEND))
