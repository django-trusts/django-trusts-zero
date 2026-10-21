"""Zero list/object adapters over Core's listed-backend grants.

``ContentQuerySet``, ``ContentManager``, and ``TrustManager`` live here
so ``models.py`` stays declarative. Manager *attachment* remains on the
model classes.
"""

from django.apps import apps as django_apps
from django.db import models
from django.db.models import Q

from trusts.apps import TrustsConfigMixin
from trusts.conditions import permission_condition_code, permission_has_condition
from trusts.decorators import filter_by_permitted_content
from trusts.models import AuthorizedQuerySet
from trusts.zero import (
    ROOT_PK,
    supported_entity_contract,
    supported_permission_contract,
)
from trusts.zero.policy import (
    reject_queryable_condition,
    resolve_content_permission,
)


def _built_catalogs():
    """Catalogs of installed mixin apps, in ``INSTALLED_APPS`` order."""
    found = []
    for config in django_apps.get_app_configs():
        if isinstance(config, TrustsConfigMixin) and config.catalog is not None:
            found.append(config.get_catalog())
    return found


def _catalog_records_content(model):
    """True when an installed catalog registered ``model`` as content."""
    concrete = getattr(model._meta, 'concrete_model', model)
    for catalog in _built_catalogs():
        for record in catalog.records:
            if record.content_model is model or record.content_model is concrete:
                return True
        for record in catalog.delegations:
            if record.content_model is model or record.content_model is concrete:
                return True
    return False


def _catalog_owning_condition(model, code):
    """Catalog that registered ``code`` on ``model``, if any."""
    for catalog in _built_catalogs():
        if catalog.get_permission_condition_record(model, code) is not None:
            return catalog
    return None


def compile_registered_condition_q(model, perm, user):
    """Compile a ``:condition`` suffix from the catalog that registered it.

    Unregistered codes raise ``AttributeError`` from the ``trusts``
    catalog, which is Zero's. Runtime ``has_perm`` treats a missing
    local name as a fail-closed non-match. Callables raise
    ``PermissionConditionNotQueryable`` without being invoked.
    """
    code = permission_condition_code(perm)
    catalog = _catalog_owning_condition(model, code)
    if catalog is None:
        catalog = django_apps.get_app_config('trusts').get_catalog()
    return catalog.compile_registered_condition_q(model, perm, user)


def django_permission_filter(qs, perm, user):
    """Zero Django-permission codec over ``AuthorizedQuerySet.authorized``.

    Does not OR backends, does not call ``granted`` / ``Exists`` /
    ``.distinct()`` itself. ``ContentQuerySet.authorized`` sequences
    Zero-owned backends.
    """
    condition_q = None
    if permission_has_condition(perm):
        condition_q = compile_registered_condition_q(qs.model, perm, user)
    if not (user is not None and user.is_authenticated and not user.is_anonymous and user.is_active):
        return qs.none()
    if not supported_entity_contract() or not supported_permission_contract():
        return qs.none()
    permission = resolve_content_permission(qs.model, perm)
    return qs.authorized(user, permission, extra_q=condition_q)


def filter_scope_rows(manager, user, content, perm_name, exclude_root=True, **kwargs):
    """Zero codec wrapper around public ``filter_by_permitted_content``.

    Permission is resolved on ``content`` (``add_category``), not on the
    Trust manager model (``add_trust``). The explicit ``auth.Group``
    path and the role ceiling are both registered. Create-under-Trust
    is the public prefix projection (including same-model proper
    prefixes). Listed backends are asked in order and their grants are
    OR'd. A catalog that did not register ``content`` contributes nothing.
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
    content = getattr(content._meta, 'concrete_model', content)
    if not _catalog_records_content(content):
        return manager.none()
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

        A ``:condition`` suffix compiles only when the registered value
        is an ``Expr``. Filtering is ``base relational grant AND
        condition`` in SQL (paginate the returned QuerySet). Callables
        raise ``PermissionConditionNotQueryable`` so they cannot
        over-grant.

        The entire Zero list algorithm is the Django-permission codec
        ``django_permission_filter``. ``.authorized`` asks every listed
        Trusts backend and ORs each catalog's grant.
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
