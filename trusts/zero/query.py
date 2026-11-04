"""Zero list/object adapters over public grants.

``ContentQuerySet``, ``ContentManager``, and ``TrustManager`` live here
so ``models.py`` stays declarative. Manager *attachment* remains on the
model classes.
"""

from django.db import models
from django.db.models import Exists, OuterRef, Q

from trusts.models import AuthorizedQuerySet, PermittedQuerySetMixin
from trusts.zero import (
    ROOT_PK,
    get_permission_model,
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
    Permission = get_permission_model()
    try:
        permission = resolve_content_permission(qs.model, perm)
    except Permission.DoesNotExist:
        return qs.none()
    return PermittedQuerySetMixin.permitted(
        qs, permission, user, conditions=((code,) if code else ()),
    )


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
        An unknown code returns an empty queryset.

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
        """Return Trust rows ``user`` holds ``perm_name`` on for Trust content.

        Row-administration semantics, restored from the historical direct
        ORM implementation (and adapted to the modern schema):

        - A Trust is included when ``user`` has the permission resolved
          for Trust content via a trustee grant **on that Trust row**, or
          via the TrustGroup local/global intersection on that row:
          a local ``TrustGroupPermission`` for the permission, group
          membership, and the permission in the group's global ceiling
          (``Group.permissions`` or a role's permissions). Role-derived
          permissions are the global ceiling, not a local assignment.
        - Only Trust content is answered. Any other content model
          returns an empty queryset: creating content under a Trust is
          not a question this method answers.
        - Parent-trust relations (``trust__trustees`` / ``trust__groups``)
          are not queried; the grant must be stored on the row itself.
        - Settlor identity is not a grant. Use ``has_perm(..., :own)``
          for settlor-only operations (not this queryset).
        - Inactive / anonymous principals yield an empty queryset.
        - ``exclude_root=True`` drops ``TRUSTS_ROOT_PK``.
        - ``filter_by_user_perm`` is unchanged (membership/trustee, no
          permission name).
        - A ``:condition`` suffix raises ``PermissionConditionError``.
          This API filters Trust rows by stored grants, so it does not
          compile V1 conditions (unlike ``ContentQuerySet.permitted``).
        """
        if 'group__user' in kwargs:
            raise TypeError('"%s" are invalid keyword arguments' % 'group__user')
        reject_queryable_condition(
            perm_name, 'Trust.objects.filter_by_user_content_perm'
        )
        if not (user is not None and user.is_authenticated and not user.is_anonymous and user.is_active):
            return self.none()
        if not supported_entity_contract() or not supported_permission_contract():
            return self.none()
        if not isinstance(content, type):
            content = content.__class__
        content = getattr(content._meta, 'concrete_model', content)
        if content is not self.model._meta.concrete_model:
            return self.none()
        permission = resolve_content_permission(content, perm_name)
        trustee_model = self.model._meta.get_field('trustees').related_model
        trust_group_model = self.model._meta.get_field('trustgroups').related_model
        trustee_grant = Exists(
            trustee_model.objects.filter(
                trust=OuterRef('pk'), entity=user, permission=permission,
            )
        )
        group_grant = Exists(
            trust_group_model.objects.filter(
                trust=OuterRef('pk'),
                group__user=user,
                trustgrouppermissions__permission=permission,
            ).filter(
                Q(group__permissions=permission)
                | Q(group__roles__permissions=permission)
            )
        )
        qs = self.filter(trustee_grant | group_grant, **kwargs)
        if exclude_root and ROOT_PK is not None:
            qs = qs.exclude(pk=ROOT_PK)
        return qs.distinct()
