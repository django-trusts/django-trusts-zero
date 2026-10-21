"""A second ``ready()`` does not register again."""

from django.apps import apps
from django.core.checks import run_checks
from django.test import SimpleTestCase

from tests.apps import TEST_BACKEND, ZERO_BACKEND, trust_rows
from trusts.errors import TrustsConfigurationError
from trusts.zero.apps import zero_config


class RecorderReadyTest(SimpleTestCase):
    def test_second_tests_ready_raises_and_keeps_the_policy(self):
        before = trust_rows('trusts_zero_tests.Category', backend=TEST_BACKEND)
        with self.assertRaises(TrustsConfigurationError):
            apps.get_app_config('trusts_zero_tests').ready()
        self.assertEqual(
            trust_rows('trusts_zero_tests.Category', backend=TEST_BACKEND),
            before,
        )

    def test_second_zero_ready_raises_and_keeps_the_policy(self):
        before = trust_rows('trusts.Trust', backend=ZERO_BACKEND)
        with self.assertRaises(TrustsConfigurationError):
            zero_config().ready()
        self.assertEqual(
            trust_rows('trusts.Trust', backend=ZERO_BACKEND),
            before,
        )

    def test_run_checks_has_no_e001(self):
        ids = [message.id for message in run_checks()]
        self.assertNotIn('trusts.E001', ids)
        self.assertTrue(trust_rows('trusts.Trust', backend=ZERO_BACKEND))
