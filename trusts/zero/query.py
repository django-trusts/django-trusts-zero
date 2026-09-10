"""Zero evaluation helpers on the composed AuthorizationPath seam.

``direct`` / ``group`` adapter gating, Django user flags, and
``auth.Permission`` resolution stay here as concrete-policy concerns.
Kernel ``compose`` / ``filter_authorized`` / ``is_authorized`` /
``authorized_scope_q`` do not know those nouns.

Resource-origin list and object checks (``ContentQuerySet.permitted``,
``TrustModelBackend`` object permissions) go through ``filter_authorized``
/ ``is_authorized`` after Zero gating. Create-under-trust and Trust-row
checks use scope-origin ``filter_authorized_scope`` / ``is_scope_authorized``
because ``Trust`` as Content is registered with the parent hop
(``resource_to_scope='trust'``), not identity.
"""

from django.db.models import Q, QuerySet

from trusts.path import AuthorizationPathError, compose, empty_grant_q
from trusts.runtime import (
    AuthorizationConfigError,
    authorized_q,
    authorized_scope_q,
    filter_authorized,
    is_authorized,
    principal_is_usable,
)


def is_active_principal(user):
    """Match ``User.has_perm``: anonymous and inactive principals are denied.

    Django ``PermissionsMixin.has_perm`` still short-circuits active
    superusers before backends run (including ``obj=None``). Object-level
    ``TrustModelBackend.has_perm`` and ``.permitted()`` evaluate the
    composed grant instead; they do not treat superuser as return-all.

    Missing ``is_active`` denies (``getattr(..., False)``). Kernel
    ``principal_is_usable`` treats a missing flag as usable and is
    consulted only after this Zero clause.
    """
    if user is None:
        return False
    if getattr(user, 'is_anonymous', False):
        return False
    if not getattr(user, 'is_authenticated', True):
        return False
    if not getattr(user, 'is_active', False):
        return False
    return principal_is_usable(user)


def _group_permission_queries_allowed():
    from trusts.zero import (
        supported_entity_contract,
        supported_group_contract,
        supported_permission_contract,
    )

    return (
        supported_entity_contract()
        and supported_group_contract()
        and supported_permission_contract()
    )


def enabled_trustee_adapter_names():
    """Installed adapter names after settings-based gating of built-ins.

    The frozen registry is the complete query-building source. Built-in
    ``direct`` / ``group`` adapters are omitted when their auth-model
    contract fails. Additional installed adapters stay in the set.
    """
    from trusts.zero import supported_entity_contract, supported_permission_contract
    from trusts.zero.models import DIRECT_TRUSTEE, GROUP_TRUSTEE, prepare_trustee_registry
    from trusts.trustee import Trustee

    prepare_trustee_registry()
    skip = set()
    if not (supported_entity_contract() and supported_permission_contract()):
        skip.add(DIRECT_TRUSTEE)
    if not _group_permission_queries_allowed():
        skip.add(GROUP_TRUSTEE)
    return tuple(
        adapter.name for adapter in Trustee.adapters()
        if adapter.name not in skip
    )


def require_configured_requester(user):
    """Fail closed unless ``user`` is an instance of the configured requester.

    Preserved 0.x façade: raises ``AuthorizationPathError``, not kernel
    ``AuthorizationConfigError``.
    """
    from trusts.zero.models import prepare_trustee_registry
    from trusts.trustee import Trustee

    prepare_trustee_registry()
    try:
        from trusts.runtime import _require_instance
        return _require_instance(
            user, Trustee.registry.requester_model(), 'requester',
        )
    except AuthorizationConfigError as exc:
        raise AuthorizationPathError(str(exc)) from exc


def require_configured_operation(operation):
    """Fail closed unless ``operation`` is an instance of the configured operation.

    Preserved 0.x façade: raises ``AuthorizationPathError``, not kernel
    ``AuthorizationConfigError``.
    """
    from trusts.zero.models import prepare_trustee_registry
    from trusts.trustee import Trustee

    prepare_trustee_registry()
    try:
        from trusts.runtime import _require_instance
        return _require_instance(
            operation, Trustee.registry.operation_model(), 'operation',
        )
    except AuthorizationConfigError as exc:
        raise AuthorizationPathError(str(exc)) from exc


def compose_zero_path(resource_model, operation):
    """Compose process-wide maps with Zero-enabled adapter names.

    Returns ``None`` when no adapters remain after auth-model gating.
    Unregistered resources and mismatched terminals raise
    ``AuthorizationPathError``.
    """
    from trusts.zero.models import prepare_context_registry, prepare_trustee_registry

    prepare_context_registry()
    prepare_trustee_registry()
    names = enabled_trustee_adapter_names()
    if not names:
        return None
    return compose(resource_model, operation, names=names)


def filter_zero_granted(queryset, requester, operation):
    """SQL-filter ``queryset`` through the composed Zero path (one query)."""
    names = enabled_trustee_adapter_names()
    if not names:
        return queryset.none()
    try:
        return filter_authorized(queryset, requester, operation, names=names)
    except AuthorizationConfigError as exc:
        raise AuthorizationPathError(str(exc)) from exc


def row_is_zero_granted(obj, requester, operation):
    """One-query exists check through the composed Zero path."""
    names = enabled_trustee_adapter_names()
    if not names:
        return False
    try:
        return is_authorized(requester, operation, obj, names=names)
    except AuthorizationConfigError as exc:
        raise AuthorizationPathError(str(exc)) from exc


def queryset_is_zero_granted(queryset, requester, operation):
    """True when ``queryset`` is non-empty and every row is granted.

    Empty querysets deny (same as ``get_all_permissions`` on an empty
    content queryset). The ungranted remainder uses the same grant
    predicate as ``filter_zero_granted``.
    """
    if not isinstance(queryset, QuerySet):
        raise AuthorizationPathError(
            'queryset must be a QuerySet, not %r.' % (queryset,)
        )
    if not is_active_principal(requester):
        return False
    if not queryset.exists():
        return False
    names = enabled_trustee_adapter_names()
    if not names:
        return False
    try:
        granted = authorized_q(
            queryset.model, requester, operation, names=names,
        )
    except AuthorizationConfigError as exc:
        raise AuthorizationPathError(str(exc)) from exc
    return not queryset.exclude(granted).exists()


def scope_pks_from_resource(obj, path):
    """Primary keys of scopes reached by ``path.resource_to_scope``.

    Resource-origin lookup (the composed Context hop), not a Trust-origin
    reverse. Used by ``get_all_permissions`` enumeration only.
    """
    lookup = path.resource_to_scope
    if isinstance(obj, QuerySet):
        return tuple(
            pk for pk in obj.values_list(lookup, flat=True).distinct()
            if pk is not None
        )
    model = obj.__class__
    pk = model._default_manager.filter(pk=obj.pk).values_list(
        lookup, flat=True,
    ).first()
    if pk is None:
        return ()
    return (pk,)


def trust_grant_q(user, permission, trust_fk=''):
    """Q matching grants when the filtered row *is* the scope.

    ``trust_fk`` must be empty (scope-origin). Resource-origin Content
    filters must use ``filter_zero_granted`` / ``filter_authorized``.

    Requester and operation must be instances of the configured
    terminals; raw PKs and same-PK collisions of the wrong model fail
    closed as ``AuthorizationPathError``.
    """
    from trusts.zero.models import Trust, prepare_trustee_registry

    if trust_fk:
        raise AuthorizationPathError(
            'trust_grant_q is scope-origin; resource-origin Content '
            'filters must use filter_zero_granted, not trust_fk=%r.' % (
                trust_fk,
            )
        )
    require_configured_requester(user)
    require_configured_operation(permission)
    prepare_trustee_registry()
    if not is_active_principal(user):
        return empty_grant_q()
    names = enabled_trustee_adapter_names()
    if not names:
        return Q(pk__in=[])
    try:
        return authorized_scope_q(Trust, user, permission, names=names)
    except AuthorizationConfigError as exc:
        raise AuthorizationPathError(str(exc)) from exc
