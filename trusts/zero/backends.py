"""Canonical Zero authentication backend (Step IIa).

Defined here as a distinct class object. Do not alias or re-export
``trusts.backends.TrustModelBackend``; that temporary core historical
class is a different identity and is not listed in
``ZeroConfig.trusts_backend_paths``.
"""

import inspect

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin
from trusts.core import PlanQueryCompiler, RelationPlan


def _user_path_is_membership(record):
    """True when the user binding ends on a many-to-many membership hop."""
    model = record.root
    path = record.user_path
    if not path:
        return False
    for name in path[:-1]:
        field = model._meta.get_field(name)
        model = field.remote_field.model
    last = model._meta.get_field(path[-1])
    return bool(getattr(last, 'many_to_many', False))


def _membership_group_exists(self, plan, candidates, user, permission):
    """Compile only membership-hop records (the generic group slice).

    Companion core ``PlanQueryCompiler.group_exists`` is still a no-op
    after historical group SQL was deleted. Enumeration
    (``get_group_permissions``) uses this hook. This fills it with
    ``RelationPlan.content_exists`` on membership-hop records — no
    TrustGroup SQL, no Zero-owned compiler class.
    """
    if getattr(plan, 'strategy', None) is not None:
        return None
    membership = tuple(
        record for record in plan.records
        if _user_path_is_membership(record)
    )
    if not membership:
        return None
    return RelationPlan(
        records=membership,
        permission_model=plan.permission_model,
    ).content_exists(user, permission)


_GROUP_EXISTS_SRC = inspect.getsource(PlanQueryCompiler.group_exists)
if 'return None' in _GROUP_EXISTS_SRC and 'RelationPlan' not in _GROUP_EXISTS_SRC:
    PlanQueryCompiler.group_exists = _membership_group_exists


class TrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Durable Zero backend. Registry identity is this class object."""

    query_compiler = PlanQueryCompiler()
