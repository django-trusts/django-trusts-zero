"""Zero list/object adapters over core ``granted`` / ``filter_authorized_scopes``.

``ContentQuerySet``, ``ContentManager``, and ``TrustManager`` live here
so ``models.py`` stays declarative. Manager *attachment* remains on the
model classes.
"""

from django.db import models
from django.db.models import Model, Q

from trusts.core import (
    TrustsConfigurationError,
    any_plan_records,
    filter_authorized_scopes,
    granted,
)
from trusts.conditions import permission_has_condition
from trusts.query import AuthorizedQuerySet, is_active_principal
from trusts.zero import (
    ROOT_PK,
    supported_entity_contract,
    supported_permission_contract,
)
from trusts.zero.policy import (
    reject_queryable_condition,
    resolve_content_permission,
)


def compile_registered_condition_q(model, perm, user):
    """Compile a ``:condition`` suffix via the configured Zero handle.

    Records live on that handle's core registry. Unregistered codes
    raise ``AttributeError`` (same as ``has_perm``). Callables raise
    ``PermissionConditionNotQueryable`` without being invoked.
    """
    from trusts.zero.apps import CANONICAL_BACKEND_PATH, zero_config

    registry = zero_config().configured_backend(CANONICAL_BACKEND_PATH).registry
    return registry.compile_registered_condition_q(model, perm, user)


def django_permission_filter(qs, perm, user):
    """Zero Django-permission codec over ``AuthorizedQuerySet.authorized``.

    Does not OR handles, does not call ``granted`` / ``Exists`` /
    ``.distinct()`` itself. ``ContentQuerySet.authorized`` sequences
    Zero-owned handles.
    """
    condition_q = None
    if permission_has_condition(perm):
        condition_q = compile_registered_condition_q(qs.model, perm, user)
    if not is_active_principal(user):
        return qs.none()
    if not supported_entity_contract() or not supported_permission_contract():
        return qs.none()
    permission = resolve_content_permission(qs.model, perm)
    return qs.authorized(user, permission, extra_q=condition_q)


def filter_scope_rows(manager, user, content, perm_name, exclude_root=True, **kwargs):
    """Zero codec wrapper around public core ``filter_authorized_scopes``.

    Permission is resolved on ``content`` (``add_category``), not on the
    Trust manager model (``add_trust``). Both TGP ceiling alternatives
    are registered. Create-under-Trust is always the public core
    prefix projection (including same-model proper prefixes). Handles
    come from ``ZeroConfig``, never ``kernel_config()``.
    """
    from trusts.zero.apps import zero_config

    reject_queryable_condition(
        perm_name, 'Trust.objects.filter_by_user_content_perm'
    )
    if not is_active_principal(user):
        return manager.none()
    if not supported_entity_contract() or not supported_permission_contract():
        return manager.none()
    if not isinstance(content, type):
        content = content.__class__
    handles = zero_config().configured_handles()
    if not any_plan_records(handles, content):
        return manager.none()
    content = getattr(content._meta, 'concrete_model', content)
    permission = resolve_content_permission(content, perm_name)
    qs = filter_authorized_scopes(
        manager.filter(**kwargs), user, permission,
        content=content, handles=handles,
    )
    if exclude_root and ROOT_PK is not None:
        qs = qs.exclude(pk=ROOT_PK)
    return qs.distinct()


class ContentQuerySet(AuthorizedQuerySet):
    def permitted(self, perm, user):
        """Content the user may access via trustee or group local/global grants.

        SQL-filtered (paginate the returned QuerySet). Empty for inactive
        or anonymous principals. Group-derived access requires the
        TrustGroup local/global intersection; role-derived permissions
        participate only as the group's global ceiling. List results match
        ``has_perm`` on the supported relational paths. Superuser
        short-circuit is not duplicated (Django ModelBackend).

        A ``:condition`` suffix compiles only when the registered value
        is an ``Expr``. Filtering is ``base relational grant AND
        condition`` in SQL (paginate the returned QuerySet). Callables
        raise ``PermissionConditionNotQueryable`` so they cannot
        over-grant.

        The entire Zero list algorithm is the Django-permission codec
        ``django_permission_filter``; ``.authorized`` sequences the
        plan through Zero-owned handles.
        """
        return django_permission_filter(self, perm, user)

    def authorized(self, user, permission, extra_q=None):
        """Sequence grants on Zero's owner handles, not ``kernel_config()``.

        Core ``AuthorizedQuerySet.authorized`` still consults the
        transitional kernel store. IIa list execution must resolve
        through ``ZeroConfig``.
        """
        from trusts.zero.apps import zero_config

        if not isinstance(permission, Model):
            raise TrustsConfigurationError(
                'permission must be a model instance, not %r.' % (permission,)
            )
        granted_q = granted(
            zero_config().configured_handles(),
            self, user, permission, kind='complete',
        )
        if granted_q is None:
            return self.none()
        if extra_q is not None:
            granted_q = granted_q & extra_q
        return self.filter(granted_q).distinct()


class ContentManager(models.Manager.from_queryset(ContentQuerySet)):
    def get_permission(self, perm):
        return resolve_content_permission(self.model, perm)


class TrustManager(ContentManager):
    def get_or_create_settlor_default(self, settlor, defaults={}, **kwargs):
        if 'trust' in kwargs:
            raise TypeError('"%s" are invalid keyword arguments' % 'trust')
        if settlor is None:
            raise ValueError('"settlor" must has a value.')
        if settlor.is_anonymous:
            # @TODO -- Handle anonymous settings
            raise ValueError('Anonymous is not yet supported.')

        try:
            return self.get(settlor=settlor, title='', **kwargs), False
        except self.model.DoesNotExist:
            params = {k: v for k, v in kwargs.items() if '__' not in k}
            params.update(defaults)
            params.update({'title': '', 'trust_id': ROOT_PK})
            trust = self.model(**params)
            trust.save()
            return trust, True

    def get_root(self):
        return self.get(pk=ROOT_PK)

    def filter_by_user_perm(self, user, **kwargs):
        if 'group__user' in kwargs:
            raise TypeError('"%s" are invalid keyword arguments' % 'group__user')

        return self.filter(Q(groups__user=user) | Q(trustees__entity=user), **kwargs)

    def filter_by_user_content_perm(self, user, content, perm_name, exclude_root=True, **kwargs):
        """Return Trusts under which ``user`` may exercise ``perm_name``.

        Create-under-trust semantics (verified, not inherited from #9):

        - A Trust is included when ``user`` has ``perm_name`` for ``content``
          via trustee grants or the TrustGroup local/global intersection
          **on that Trust row**. Role-derived permissions are the global
          ceiling, not a local assignment.
        - Parent-trust relations (``trust__trustees`` / ``trust__groups``)
          are not queried. ``#9`` did that accidentally.
        - Settlor identity is not a grant. Use ``has_perm(..., :own)`` for
          settlor-only operations (not this queryset).
        - This API filters Trust rows by grants, not by existing content
          rows. A Trust with no content yet can still be a create target.
        - Inactive / anonymous principals yield an empty queryset.
        - ``exclude_root=True`` drops ``TRUSTS_ROOT_PK`` (typical for
          organization content).
        - ``filter_by_user_perm`` is unchanged (membership/trustee, no
          permission name).
        - A ``:condition`` suffix raises ``PermissionConditionNotQueryable``.
          This API filters Trust rows, not content rows, so it does not
          compile V1 conditions (unlike ``ContentQuerySet.permitted``).
        """
        if 'group__user' in kwargs:
            raise TypeError('"%s" are invalid keyword arguments' % 'group__user')
        return filter_scope_rows(
            self, user, content, perm_name,
            exclude_root=exclude_root, **kwargs
        )
