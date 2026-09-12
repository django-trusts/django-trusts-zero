"""Canonical Zero authentication backend (Step IIa).

Defined here as a distinct class object. Do not alias or re-export
``trusts.backends.TrustModelBackend``; that temporary core historical
class is a different identity and is not listed in
``ZeroConfig.trusts_backend_paths``.
"""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin
from trusts.core import PlanQueryCompiler


class TrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Durable Zero backend. Registry identity is this class object."""

    query_compiler = PlanQueryCompiler()
