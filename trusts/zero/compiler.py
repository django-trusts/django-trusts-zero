"""Plan compiler that keeps one ``Group.permissions`` join.

Core applies a ``group=`` condition and the permission correlation as
separate filters. Django will not reuse a many-to-many join across
filters, so one local grant would match every permission on the group.
One combined filter shares that join. Records that are not explicit
``group=`` registrations stay on ``RelationPlan``.
"""

from functools import reduce
from operator import or_

from django.db.models import Exists, OuterRef, Q, QuerySet

from trusts.core import (
    PlanQueryCompiler,
    RelationPlan,
    TrustsConfigurationError,
    _BINDING_FIELDS,
    _as_q,
    _bind_terminal,
    _compile_predicate,
    _require_instance,
    _scope_prefix_lookups,
)


def shared_exists(record, *, terminal, target, **bindings):
    """``EXISTS`` of one root with bindings, condition, and correlation.

    The condition is AND-ed into the same ``filter()`` as the correlated
    lookup so Django reuses the compiler-owned ``Group.permissions`` join.
    """
    lookups = {
        getattr(record, _BINDING_FIELDS[role]): _bind_terminal(value, role)
        for role, value in bindings.items()
    }
    lookups[terminal] = OuterRef(target)
    condition = _compile_predicate(record.condition, record)
    query = Q(**lookups)
    if condition is not None:
        query = condition & query
    return Exists(record.root._default_manager.filter(query))


def _or_parts(parts):
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return reduce(or_, parts)


class ZeroPlanQueryCompiler(PlanQueryCompiler):
    """``PlanQueryCompiler`` with a shared join for explicit ``group=`` rows."""

    def complete_exists(self, plan, candidates, user, permission):
        return self._exists(plan, user, permission, grouped_only=False)

    def group_exists(self, plan, candidates, user, permission):
        return self._exists(plan, user, permission, grouped_only=True)

    def _exists(self, plan, user, permission, *, grouped_only):
        records = tuple(getattr(plan, 'records', None) or ())
        if grouped_only:
            records = tuple(
                record for record in records
                if getattr(record, 'via_group', False)
            )
        if not records:
            return None
        parts = []
        plain = []
        for record in records:
            if getattr(record, 'via_group', False) and record.along is None:
                parts.append(shared_exists(
                    record,
                    terminal=record.content_field,
                    target=record.content_target,
                    user=user,
                    permission=permission,
                ))
            else:
                plain.append(record)
        if plain:
            part = RelationPlan(
                records=tuple(plain),
                permission_model=getattr(plan, 'permission_model', None),
            ).content_exists(user, permission)
            if part is not None:
                parts.append(part)
        return _or_parts(parts)


def filter_authorized_scopes(queryset, user, permission, *, content, handles=None):
    """Prefix scope filter. Explicit ``group=`` rows share one permissions join.

    Same contract as core ``filter_authorized_scopes``. The core helper
    binds the permission and then applies the condition as a second
    filter, which splits ``Group.permissions``.
    """
    if not isinstance(queryset, QuerySet):
        raise TrustsConfigurationError(
            'filter_authorized_scopes requires a QuerySet, not %r.'
            % (queryset,)
        )
    if handles is None:
        from trusts.apps import _relationship_implementation_handles
        handles = _relationship_implementation_handles()
    user = _require_instance(user, 'user')
    permission = _require_instance(permission, 'permission')
    if not handles:
        return queryset.none()

    scope_model = queryset.model._meta.concrete_model
    parts = []
    for handle in handles:
        plan = handle.registry.plan_for(
            content, user=user, permission=permission,
        )
        for record in plan.records:
            for lookup, target_attname in _scope_prefix_lookups(
                record, scope_model,
            ):
                parts.append(shared_exists(
                    record,
                    terminal=lookup,
                    target=target_attname,
                    user=user,
                    permission=permission,
                ))
    granted_q = _or_parts(parts)
    if granted_q is None:
        return queryset.none()
    return queryset.filter(_as_q(granted_q)).distinct()
