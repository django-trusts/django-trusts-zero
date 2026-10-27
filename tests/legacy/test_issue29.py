"""Installed project check does not report a condition-expression error."""

from django.core.checks import run_checks
from django.test import SimpleTestCase


class InstalledCheckSmokeTest(SimpleTestCase):
    def test_run_checks_has_no_e001(self):
        ids = [message.id for message in run_checks()]
        self.assertNotIn('trusts.E001', ids)
