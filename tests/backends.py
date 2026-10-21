"""Test-app authentication backend.

The catalog belongs to ``TestsConfig``. Do not borrow Zero's recorder.
"""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin


class TestsBackend(TrustModelBackendMixin, ModelBackend):
    """Listed backend for ``trusts_zero_tests`` registrations."""
