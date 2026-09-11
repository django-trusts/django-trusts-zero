from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Model, Q, options
from django.utils.translation import gettext_lazy as _

from trusts.zero import (
    ENTITY_MODEL_NAME, PERMISSION_MODEL_NAME, GROUP_MODEL_NAME,
    DEFAULT_SETTLOR, ALLOW_NULL_SETTLOR, ROOT_PK,
    get_permission_model,
    supported_entity_contract, supported_permission_contract,
)
from trusts import utils
from trusts.core import (
    TrustsConfigurationError,
    any_plan_records,
    filter_authorized_scopes,
)
from trusts.query import AuthorizedQuerySet, is_active_principal
from trusts.conditions import (
    PermissionConditionNotQueryable,
    condition_refs,
    permission_has_condition,
)


options.DEFAULT_NAMES += ('roles', 'permission_conditions',
                          'content_roles', 'content_permission_conditions',
                          'auto_modeladmin',
    )


def reject_queryable_condition(perm, api_name):
    if permission_has_condition(perm):
        raise PermissionConditionNotQueryable(
            '%s does not support permission conditions (%r). '
            'Create-under-trust filters Trust rows, not the content '
            'model the condition is registered on. Use the unconditioned '
            'permission for this queryset, or ContentQuerySet.permitted '
            'for V1 declarative conditions on content rows.' % (api_name, perm)
        )


_u, _p, _o = condition_refs()


def compile_registered_condition_q(model, perm, user):
    """Compile a ``:condition`` suffix via the configured Zero handle.

    Records live on that handle's core registry. Unregistered codes
    raise ``AttributeError`` (same as ``has_perm``). Callables raise
    ``PermissionConditionNotQueryable`` without being invoked.
    """
    from trusts.zero.apps import CANONICAL_BACKEND_PATH, zero_config

    registry = zero_config().configured_backend(CANONICAL_BACKEND_PATH).registry
    return registry.compile_registered_condition_q(model, perm, user)


def resolve_content_permission(model, perm):
    """Resolve ``perm`` on the configured permission model.

    Accepts a permission instance, a codename (``read_category``), a bare
    action (``read`` → ``read_<model>``), or a dotted code
    (``app.read_category``).

    Queryset list APIs must reject or compile ``:condition`` suffixes
    before using this helper to resolve the grant. This helper may still
    strip a leftover ``:condition`` when resolving a grant/revoke target;
    it must not be used alone to filter lists.
    """
    Permission = get_permission_model()
    if isinstance(perm, Permission):
        return perm

    app_label = model._meta.app_label
    model_name = model._meta.model_name
    perm = str(perm)
    if '.' in perm:
        try:
            applabel, modelname, action, _cond = utils.parse_perm_code(perm)
            perm = '%s_%s' % (action, modelname)
            app_label = applabel
            model_name = modelname
        except ValueError:
            app_label, perm = perm.split('.', 1)
    if ':' in perm:
        perm = perm.split(':', 1)[0]
    if not perm.endswith('_' + model_name) and '_' not in perm:
        perm = '%s_%s' % (perm, model_name)

    manager = Permission.objects
    if hasattr(manager, 'get_by_natural_key'):
        return manager.get_by_natural_key(perm, app_label.lower(), model_name)
    return manager.get(
        codename=perm,
        content_type__app_label=app_label.lower(),
        content_type__model=model_name,
    )


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


def _content_via_trust(root_ref, model):
    rev = model._meta.get_field('trust').remote_field.get_accessor_name()
    return getattr(root_ref.trust, rev)


def register_zero_direct(registry, content_models):
    """TUP records for each content terminal (C1 ``register()`` grammar)."""
    from trusts.core import Ref

    j = Ref(TrustUserPermission)
    for model in content_models:
        registry.register(
            content=_content_via_trust(j, model),
            user=j.entity,
            permission=j.permission,
        )


def register_zero_group(registry, content_models):
    """TGP records when C1 public ``register()`` accepts the membership hop.

    Merged C1 user paths are still one direct single-valued hop, so
    ``g.trustgroup.group.user_set`` raises ``TrustsConfigurationError``.
    That is recorded, not widened here. Group list/object grants on C1
    still flow through ``HistoricalGroupQueryCompiler``.
    """
    from trusts.core import Ref

    g = Ref(TrustGroupPermission)
    try:
        user_ref = g.trustgroup.group.user_set
    except Exception as exc:
        raise TrustsConfigurationError(
            'TGP user membership hop is not expressible on this kernel: %s'
            % (exc,)
        ) from exc
    for model in content_models:
        registry.register(
            content=_content_via_trust(g.trustgroup, model),
            user=user_ref,
            permission=g.permission,
        )


def register_zero_relations(registry):
    """Idempotent package donation: Trust-as-content TUP, then TGP if expressible."""
    ids = getattr(registry, '_zero_z1_relation_ids', None)
    if ids is registry:
        return
    register_zero_direct(registry, (Trust,))
    try:
        register_zero_group(registry, (Trust,))
    except TrustsConfigurationError:
        # Public register() grammar cannot express TGP user membership
        # yet. Group list/object grants continue through Zero's
        # HistoricalGroupQueryCompiler. Do not call kernel_config().
        pass
    registry._zero_z1_relation_ids = registry


def _has_tgp_records(handles):
    for handle in handles:
        for record in handle.registry.records:
            if record.root is TrustGroupPermission:
                return True
    return False


def filter_scope_rows(manager, user, content, perm_name, exclude_root=True, **kwargs):
    """Zero codec wrapper around ``filter_authorized_scopes``.

    Permission is resolved on ``content`` (``add_category``), not on the
    Trust manager model (``add_trust``).

    When TGP records exist, the generic prefix projection is the whole
    create-under-Trust filter. When TGP cannot register, group parity
    uses the public ``trust_grant_q`` (not copied). Handles come from
    ``ZeroConfig``, never ``kernel_config()``.
    """
    from trusts.query import trust_grant_q
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
    if _has_tgp_records(handles):
        qs = filter_authorized_scopes(
            manager.filter(**kwargs), user, permission,
            content=content, handles=handles,
        )
    else:
        qs = manager.filter(trust_grant_q(user, permission), **kwargs)
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
        from trusts.core import TrustsConfigurationError, granted
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
        except Trust.DoesNotExist:
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


class ReadonlyFieldsMixin(object):
    def _readonly_attname(self, field_name):
        try:
            return self._meta.get_field(field_name).attname
        except Exception:
            return field_name

    def __init__(self, *args, **kwargs):
        super(ReadonlyFieldsMixin, self).__init__(*args, **kwargs)

        if hasattr(self, '_readonly_fields'):
            # Snapshot column values from __dict__. getattr() on a ForeignKey
            # in Django 6.1 fetch-mode would load the related object and recurse
            # on Trust.trust (the self-referential root).
            self._state.init_fields = {}
            for field in self._readonly_fields:
                attname = self._readonly_attname(field)
                if attname in self.__dict__:
                    self._state.init_fields[field] = self.__dict__[attname]

    def clean(self):
        super(ReadonlyFieldsMixin, self).clean()

        if hasattr(self, '_readonly_fields') and hasattr(self._state, 'init_fields'):
            for field in self._readonly_fields:
                if field in self._state.init_fields:
                    saved_value = self._state.init_fields[field]
                    attname = self._readonly_attname(field)
                    if saved_value != self.__dict__.get(attname, getattr(self, attname)):
                        raise ValidationError('Field "%s" is readonly.' % 'trust')


class Content(ReadonlyFieldsMixin, models.Model):
    trust = models.ForeignKey('trusts.Trust', related_name='%(app_label)s_%(class)s_content',
                default=ROOT_PK, null=False, blank=False, on_delete=models.CASCADE)
    objects = ContentManager()

    class Meta:
        abstract = True
        default_permissions = ('add', 'change', 'delete', 'read',)
        permission_conditions = ()
        auto_modeladmin = False


class Trust(Content):
    title = models.CharField(max_length=40, null=False, blank=False, verbose_name=_('title'))
    settlor = models.ForeignKey(ENTITY_MODEL_NAME, default=DEFAULT_SETTLOR, null=ALLOW_NULL_SETTLOR, blank=False,
                on_delete=models.CASCADE)
    groups = models.ManyToManyField(GROUP_MODEL_NAME, related_name='trusts',
                through='trusts.TrustGroup',
                verbose_name=_('groups'),
                help_text=_('Groups associated with this trust. Association '
                            'alone grants nothing; a permission applies only '
                            'when it is in both the group\'s global ceiling '
                            'and this trust\'s local TrustGroup grants.'),
    )
    _readonly_fields = ('trust', 'settlor',)

    objects = TrustManager()

    class Meta:
        unique_together = ('settlor', 'title')
        default_permissions = ('add', 'change', 'delete', 'read',)
        permission_conditions = (('own', _u == _o.settlor), )

    def __str__(self):
        settlor_str = ' of %s' % str(self.settlor) if self.settlor is not None else ''
        return 'Trust[%s]: "%s"' % (self.id, self.title)


class Role(models.Model):
    name = models.CharField(max_length=80, null=False, blank=False, unique=True,
                help_text=_('The name of the role. Corresponds to the key of model\'s trusts option.'))
    groups = models.ManyToManyField(GROUP_MODEL_NAME, related_name='roles', blank=False,
                verbose_name=_('groups')
            )
    permissions = models.ManyToManyField(PERMISSION_MODEL_NAME,
                through='trusts.RolePermission',
                related_name='roles', blank=False,
                verbose_name=_('permissions')
            )

    class Meta:
        pass


class RolePermission(models.Model):
    role = models.ForeignKey('trusts.Role', related_name='rolepermissions', null=False, blank=False,
                on_delete=models.CASCADE)
    permission = models.ForeignKey(PERMISSION_MODEL_NAME, related_name='rolepermissions', null=False, blank=False,
                on_delete=models.CASCADE)
    managed = models.BooleanField(null=False, blank=False, default=False)

    class Meta:
        unique_together = ('role', 'permission')


class TrustUserPermission(models.Model):
    trust = models.ForeignKey('trusts.Trust', related_name='trustees', null=False, blank=False,
                on_delete=models.CASCADE)
    entity = models.ForeignKey(ENTITY_MODEL_NAME, related_name='trustpermissions', null=False, blank=False,
                on_delete=models.CASCADE)
    permission = models.ForeignKey(PERMISSION_MODEL_NAME, related_name='trustentities', null=False, blank=False,
                on_delete=models.CASCADE)

    class Meta:
        unique_together = ('trust', 'entity', 'permission')


def get_group_global_ceiling(group):
    """Permissions the group may exercise anywhere: Group.permissions ∪ roles.

    Role assignments are global ceiling only. They are not per-Trust grants.
    Custom group models must expose a ``permissions`` M2M to
    ``TRUSTS_PERMISSION_MODEL`` and a ``user`` related-query name for
    membership (the same conventions as ``auth.Group``).
    """
    Permission = get_permission_model()
    return Permission.objects.filter(
        Q(group=group) | Q(roles__groups=group)
    ).distinct()


def permission_in_global_ceiling(group, permission):
    if group is None or permission is None:
        return False
    return get_group_global_ceiling(group).filter(pk=permission.pk).exists()


class TrustGroupManager(models.Manager):
    def associate(self, trust, group):
        obj, _created = self.get_or_create(trust=trust, group=group)
        return obj


class TrustGroup(models.Model):
    """Through model for ``Trust.groups`` plus per-trust local grants.

    Association without local permissions grants nothing. Effective access
    still requires group membership and the group's global ceiling.
    """
    trust = models.ForeignKey('trusts.Trust', related_name='trustgroups', null=False, blank=False,
                on_delete=models.CASCADE)
    group = models.ForeignKey(GROUP_MODEL_NAME, related_name='trustgroups', null=False, blank=False,
                on_delete=models.CASCADE)
    permissions = models.ManyToManyField(PERMISSION_MODEL_NAME,
                through='trusts.TrustGroupPermission',
                related_name='granted_trustgroups', blank=True,
                verbose_name=_('permissions'))

    objects = TrustGroupManager()

    class Meta:
        db_table = 'trusts_trust_groups'
        unique_together = ('trust', 'group')

    def __str__(self):
        return 'TrustGroup[%s]: trust=%s group=%s' % (self.pk, self.trust_id, self.group_id)


class TrustGroupPermissionQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        for obj in objs:
            obj.full_clean()
        return super(TrustGroupPermissionQuerySet, self).bulk_create(objs, **kwargs)


class TrustGroupPermission(models.Model):
    """Local permission tuple on a TrustGroup. Must stay inside the ceiling."""
    trustgroup = models.ForeignKey('trusts.TrustGroup', related_name='trustgrouppermissions',
                null=False, blank=False, on_delete=models.CASCADE)
    permission = models.ForeignKey(PERMISSION_MODEL_NAME, related_name='trustgrouppermissions',
                null=False, blank=False, on_delete=models.CASCADE)

    objects = TrustGroupPermissionQuerySet.as_manager()

    class Meta:
        unique_together = ('trustgroup', 'permission')

    def __str__(self):
        return 'TrustGroupPermission[%s]: trustgroup=%s permission=%s' % (
            self.pk, self.trustgroup_id, self.permission_id
        )

    def clean(self):
        super(TrustGroupPermission, self).clean()
        if not self.trustgroup_id or not self.permission_id:
            raise ValidationError(
                'TrustGroupPermission requires trustgroup and permission.',
                code='incomplete_trustgroup_permission',
            )
        if not permission_in_global_ceiling(self.trustgroup.group, self.permission):
            raise ValidationError(
                'Permission "%s" is outside the global ceiling of group "%s".' % (
                    self.permission, self.trustgroup.group
                ),
                code='local_grant_outside_ceiling',
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super(TrustGroupPermission, self).save(*args, **kwargs)


class Junction(ReadonlyFieldsMixin, models.Model):
    trust = models.ForeignKey('trusts.Trust', related_name='%(app_label)s_%(class)s',
                default=ROOT_PK, null=False, blank=False, on_delete=models.CASCADE)
    _readonly_fields = ('trust',)

    class Meta:
        abstract = True
        default_permissions = ()
        content_permission_conditions = ()
        unique_together = ('content', )

    @classmethod
    def get_content_model(cls):
        # introspect for the content model class with the easy case
        content_model_fields = [f for f in cls._meta.fields if f.remote_field is not None and f.name != 'trust']
        if len(content_model_fields) == 1:
            return content_model_fields[0].remote_field.model
        raise NotImplementedError('Juctnion\'s classmethod "get_content_model" is not implemented.')

    @classmethod
    def get_fieldlookup(cls):
        return '%s__content' % utils.get_short_model_name_lower(cls).replace('.', '_')


def donate_content_permission_conditions(registry, model):
    """Walk ``Meta.permission_conditions`` onto a core handle registry.

    Model-specific collection only. Does not keep a Zero-owned store.
    Abstract and proxy models are skipped.
    """
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = getattr(model._meta, 'permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        registry.register_permission_condition(model, cond_code, condition)


def donate_junction_content_permission_conditions(registry, model):
    """Walk Junction ``Meta.content_permission_conditions`` onto ``registry``."""
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = getattr(model._meta, 'content_permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        registry.register_permission_condition(model, cond_code, condition)


def donate_installed_permission_conditions(registry, apps_registry=None):
    """Donate every installed Content/Junction Meta declaration.

    Idempotent per registry instance so repeated ``ZeroConfig.ready()``
    does not create a second source of truth. ``Trust:own``, Content
    Meta, and Junction Meta each become one record on this handle.
    """
    from django.apps import apps as django_apps

    donated = getattr(registry, '_zero_condition_donation_id', None)
    if donated is registry:
        return
    apps = django_apps if apps_registry is None else apps_registry
    for model in apps.get_models():
        if issubclass(model, Junction):
            donate_junction_content_permission_conditions(registry, model)
        elif issubclass(model, Content):
            donate_content_permission_conditions(registry, model)
    registry._zero_condition_donation_id = registry
