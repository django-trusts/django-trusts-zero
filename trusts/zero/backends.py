"""Canonical historical Trusts backend owned by Zero.

This class is defined here. It is not an alias of
``trusts.backends.TrustModelBackend`` and must not share that object's
identity. ``ZeroConfig`` owns the exact path
``trusts.zero.backends.TrustModelBackend``.
"""

from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from trusts.backends import TrustModelBackendMixin
from trusts.query import historical_group_grant_exists


class HistoricalGroupQueryCompiler(object):
    """Complete proof: registered plan OR historical TrustGroup.

    Defined in Zero so Step III can delete the temporary core copy
    without moving Zero's registry identity.
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
    query_compiler = HistoricalGroupQueryCompiler()
