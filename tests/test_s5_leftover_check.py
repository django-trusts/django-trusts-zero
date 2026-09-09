"""S5 leftover Content check registration (django-trusts#47 companion)."""

from django.core.checks.registry import registry as check_registry
from django.test import SimpleTestCase

from trusts.zero.checks import (
    _kernel_owns_adapter_rewalks,
    check_context_registry,
    check_trustee_registry,
    check_unresolved_content_registrations,
)


class LeftoverContentCheckRegistrationTests(SimpleTestCase):
    def test_kernel_plus_zero_registers_leftover_only(self):
        registered = check_registry.registered_checks
        if _kernel_owns_adapter_rewalks():
            self.assertIn(check_unresolved_content_registrations, registered)
            self.assertNotIn(check_context_registry, registered)
            self.assertNotIn(check_trustee_registry, registered)
        else:
            self.assertNotIn(check_unresolved_content_registrations, registered)
            self.assertIn(check_context_registry, registered)
            self.assertIn(check_trustee_registry, registered)
