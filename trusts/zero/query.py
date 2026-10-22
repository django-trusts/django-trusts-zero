"""Zero list/object adapters over public grants.

``ContentQuerySet``, ``ContentManager``, and ``TrustManager`` live here
so ``models.py`` stays declarative. Manager *attachment* remains on the
model classes.
"""

from django.db import models
from django.db.models import Q

from trusts.decorators import filter_by_permitted_content
from trusts.models import AuthorizedQuerySet, PermittedQuerySetMixin
from trusts.zero import (
    ROOT_PK,
    supported_entity_contract,
    supported_permission_contract,
)
from trusts.zero.policy import (
    _condition_suffix,
    reject_queryable_condition,
    resolve_content_permission,
)


def django_permission_filter(qs, perm, user):
    """Zero Django-permission codec over ``PermittedQuerySetMixin.permitted``.

    The permission string is resolved on ``qs.model``. A ``:code`` suffix
    is the ``conditions`` tuple. Listed backends resolve that name and
    fail closed.
    """
    if not (user is not None and user.is_authenticated and not user.is_anonymous and user.is_active):
        return qs.none()
    if not supported_entity_contract() or not supported_permission_contract():
        return qs.none()
    code = _condition_suffix(perm)
    permission = resolve_content_permission(qs.model, perm)
    return PermittedQuerySetMixin.permitted(
        qs, permission, user, conditions=((code,) if code else ()),
    )


def filter_scope_rows(manager, user, content, perm_name, exclude_root=True, **kwargs):
    """Zero codec wrapper around ``filter_by_permitted_content``.

    Permission is resolved on ``content`` (``add_category``), not on the
    Trust manager model (``add_trust``). The explicit ``auth.Group``
    path and the role ceiling are both registered. Create-under-Trust
    is the public prefix projection (including same-model proper prefixes).
    """
    reject_queryable_condition(
        perm_name, 'Trust.objects.filter_by_user_content_perm'
    )
    if not (user is not None and user.is_authenticated and not user.is_anonymous and user.is_active):
        return manager.none()
    if not supported_entity_contract() or not supported_permission_contract():
        return manager.none()
    if not isinstance(content, type):
        content = content.__class__
    content = content._meta.concrete_model
    permission = resolve_content_permission(content, perm_name)
    qs = filter_by_permitted_content(
        manager.filter(**kwargs), user, permission, content=content,
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

        A ``:condition`` suffix is passed as ``conditions=(code,)``.
        Filtering is the public permitted grant: relational rows AND
        the named filter, in SQL (paginate the returned QuerySet).
        An unknown code raises ``TrustsConfigurationError``.

        The list algorithm is ``django_permission_filter``.
        """
        return django_permission_filter(self, perm, user)


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
        - A ``:condition`` suffix raises ``PermissionConditionError``.
          This API filters Trust rows, not content rows, so it does not
          apply V1 conditions (unlike ``ContentQuerySet.permitted``).
        """
        if 'group__user' in kwargs:
            raise TypeError('"%s" are invalid keyword arguments' % 'group__user')
        return filter_scope_rows(
            self, user, content, perm_name,
            exclude_root=exclude_root, **kwargs
        )
