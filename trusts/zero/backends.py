"""Canonical Zero authentication backend (Step IIa).

Defined here as a distinct class object. Do not alias or re-export
``trusts.backends.TrustModelBackend``; that temporary core historical
class is a different identity and is not listed in
``ZeroConfig.trusts_backend_paths``.
"""

from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from trusts.backends import TrustModelBackendMixin
from trusts.query import historical_group_grant_exists


class HistoricalGroupQueryCompiler(object):
    """Zero-owned historical TrustGroup OR compiler.

    Distinct from the temporary core
    ``trusts.backends.HistoricalGroupQueryCompiler``. Uses the public
    kernel ``historical_group_grant_exists`` helper. ``historical_fallback``
    identifies this concrete compiler for mixin isolation.
    """

    historical_fallback = True

    def complete_exists(self, plan, candidates, user, permission):
        if getattr(plan, 'strategy', None) is not None:
            return plan.content_exists(user, permission)
        if not plan.records:
            return None
        return Q(plan.content_exists(user, permission)) | Q(
            historical_group_grant_exists(plan, user, permission)
        )

    def group_exists(self, plan, candidates, user, permission):
        if getattr(plan, 'strategy', None) is not None:
            return None
        if not plan.records:
            return None
        return Q(historical_group_grant_exists(plan, user, permission))


class TrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Durable Zero backend. Registry identity is this class object."""

    query_compiler = HistoricalGroupQueryCompiler()
