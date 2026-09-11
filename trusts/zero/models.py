from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import signals, Q, options
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _

from trusts.zero import (
    ENTITY_MODEL_NAME, PERMISSION_MODEL_NAME, GROUP_MODEL_NAME,
    DEFAULT_SETTLOR, ALLOW_NULL_SETTLOR, ROOT_PK,
    get_permission_model,
    supported_entity_contract, supported_permission_contract,
)
from trusts import utils
from trusts.core import (
    ConditionLookup,
    TrustsConfigurationError,
    any_plan_records,
    filter_authorized_scopes,
)
from trusts.query import AuthorizedQuerySet, is_active_principal
from trusts.conditions import (
    Expr,
    PermissionConditionError,
    condition_refs,
    compile_expression_q,
    is_predicate,
)


options.DEFAULT_NAMES += ('roles', 'permission_conditions',
                          'content_roles', 'content_permission_conditions',
                          'auto_modeladmin',
    )


class PermissionConditionNotQueryable(ValueError):
    """Raised when a SQL list/create filter cannot compile a ``:condition``.

    Only a registered ``Expr`` compiles into the tree ``has_perm``
    evaluates. Callables stay object-only: ``permitted`` and
    ``filter_by_user_content_perm`` refuse them so they cannot silently
    over-grant the underlying permission.
    """


def permission_has_condition(perm):
    """True when ``perm`` is a string with a ``:condition`` suffix."""
    return isinstance(perm, str) and ':' in perm


def reject_queryable_condition(perm, api_name):
    if permission_has_condition(perm):
        raise PermissionConditionNotQueryable(
            '%s does not support permission conditions (%r). '
            'Create-under-trust filters Trust rows, not the content '
            'model the condition is registered on. Use the unconditioned '
            'permission for this queryset, or ContentQuerySet.permitted '
            'for V1 declarative conditions on content rows.' % (api_name, perm)
        )


def _condition_code(perm):
    if not isinstance(perm, str) or ':' not in perm:
        return ''
    if '.' in perm:
        try:
            return utils.parse_perm_code(perm)[3]
        except ValueError:
            pass
    return perm.split(':', 1)[1]


def legacy_permission_callbacks_allowed():
    """True only when ``TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS`` is set.

    Read at call time so ``override_settings`` works. Missing or False
    means registered callables are a system-check error and runtime
    fail-closed (the callback is never invoked).
    """
    return bool(getattr(
        django_settings, 'TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS', False
    ))


class _ConditionRecord(object):
    """Registered condition: an ``Expr`` tree or a legacy callable.

    ``model`` is retained so a ``class_prepared`` registration can be
    validated by the system check after all apps have loaded.
    """

    __slots__ = ('expr', 'func', 'model')

    def __init__(self, expr=None, func=None, model=None):
        self.expr = expr
        self.func = func
        self.model = model


_u, _p, _o = condition_refs()


def compile_registered_condition_q(model, perm, user):
    """Compile a ``:condition`` suffix to ``Q``, or raise fail-closed.

    Unregistered codes raise ``AttributeError`` (same as ``has_perm``).
    Callables raise ``PermissionConditionNotQueryable`` without being
    invoked. Registered ``Expr`` trees that are not valid V1 fail closed.
    """
    cond = _condition_code(perm)
    record = Content.get_permission_condition_record(model, cond)
    if record is None:
        raise AttributeError(
            'Permission condition code "%s" is not associate with model "%s_%s"' % (
                cond, model._meta.app_label, model._meta.model_name
            )
        )
    if record.expr is None:
        raise PermissionConditionNotQueryable(
            'ContentQuerySet.permitted does not support permission '
            'condition %r on %s. Register an Expr from condition_refs() '
            'to compile a V1 declarative expression. Callables remain '
            'object-only via has_perm; this queryset API refuses them so '
            'the underlying grant cannot be returned without the '
            'condition.' % (perm, model._meta.label)
        )
    return compile_expression_q(
        record.expr, model, user, perm.split(':', 1)[0]
    )


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


class ContentConditionLookup(ConditionLookup):
    """Zero-owned ``:condition`` overlay bound from ``ZeroConfig.ready()``."""

    def record_for(self, model, cond_code):
        return Content.get_permission_condition_record(model, cond_code)

    def compile_q(self, model, perm_string, user):
        return compile_registered_condition_q(model, perm_string, user)


def django_permission_filter(qs, perm, user):
    """Zero Django-permission codec over ``AuthorizedQuerySet.authorized``.

    Does not OR handles, does not call ``granted`` / ``Exists`` /
    ``.distinct()`` itself. Core owns that control flow.
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
        # C1 public grammar cannot express TGP yet. Do not copy a
        # private group compiler into Zero.
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
    create-under-Trust filter. On C1, TGP cannot register, so group
    parity uses the still-public C1 ``trust_grant_q`` (not copied).
    """
    from trusts.apps import kernel_config
    from trusts.query import trust_grant_q

    reject_queryable_condition(
        perm_name, 'Trust.objects.filter_by_user_content_perm'
    )
    if not is_active_principal(user):
        return manager.none()
    if not supported_entity_contract() or not supported_permission_contract():
        return manager.none()
    if not isinstance(content, type):
        content = content.__class__
    handles = kernel_config().configured_handles()
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
        ``django_permission_filter``; core ``.authorized`` sequences the
        plan.
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


def _register_meta_permission_conditions(klass):
    """Walk ``Meta.permission_conditions`` onto the condition registry."""
    if hasattr(klass._meta, 'permission_conditions'):
        for permcond, condition in klass._meta.permission_conditions:
            Content.register_permission_condition(klass, permcond, condition)


def _register_junction_content_permission_conditions(klass):
    """Walk Junction ``Meta.content_permission_conditions``."""
    if hasattr(klass._meta, 'content_permission_conditions'):
        for permcond, condition in klass._meta.content_permission_conditions:
            Content.register_permission_condition(klass, permcond, condition)


class Content(ReadonlyFieldsMixin, models.Model):
    trust = models.ForeignKey('trusts.Trust', related_name='%(app_label)s_%(class)s_content',
                default=ROOT_PK, null=False, blank=False, on_delete=models.CASCADE)
    objects = ContentManager()
    _conditions = {}

    class Meta:
        abstract = True
        default_permissions = ('add', 'change', 'delete', 'read',)
        permission_conditions = ()
        auto_modeladmin = False

    @staticmethod
    def register_permission_condition(klass, cond_code, condition):
        """Register a ``:cond_code`` condition on ``klass``.

        Pass an ``Expr`` built from ``condition_refs()`` to opt into V1
        compile/evaluate. Pass a callable to keep the historical
        object-only ``has_perm`` path. Dispatch is by type: callables are
        never invoked with symbolic ``Ref`` arguments.

        Construction-time shape errors (bare non-predicate ``Expr``, a
        value that is neither ``Expr`` nor callable) still raise here.
        Model-aware semantic validation is reported by the registered
        Django system check as ``CheckMessage``s, not raised from this
        method, so ``SILENCED_SYSTEM_CHECKS`` can filter the diagnostic.
        """
        if isinstance(condition, Expr):
            if not is_predicate(condition):
                raise PermissionConditionError(
                    'Registered expression must be a V1 comparison '
                    '(==, != combined with & / |), not %r.' % (condition,)
                )
            record = _ConditionRecord(expr=condition, model=klass)
        elif callable(condition):
            record = _ConditionRecord(func=condition, model=klass)
        else:
            raise TypeError(
                'register_permission_condition expected an Expr or a '
                'callable, got %r.' % (type(condition).__name__,)
            )
        short_name = utils.get_short_model_name(klass)
        if short_name not in Content._conditions:
            Content._conditions[short_name] = {}
        Content._conditions[short_name][cond_code] = record

    @staticmethod
    def register_content(klass):
        """Register Meta ``permission_conditions`` for ``klass``.

        Content-terminal declaration is an explicit AppConfig ``Ref``
        contribution. This method does not publish a model→path map.
        """
        _register_meta_permission_conditions(klass)

    @staticmethod
    def get_permission_condition_record(klass, cond_code):
        short_name = utils.get_short_model_name(klass)
        if short_name in Content._conditions:
            if cond_code in Content._conditions[short_name]:
                return Content._conditions[short_name][cond_code]
        return None

    @staticmethod
    def get_permission_condition_func(klass, cond_code):
        record = Content.get_permission_condition_record(klass, cond_code)
        if record is None:
            return None
        return record.func

    @staticmethod
    def iter_permission_conditions():
        """Yield ``(model, cond_code, record)`` for every registration.

        Used by the system check after model loading. Identity comes from
        the record so ``class_prepared`` registrations remain validatable
        without importing extra application modules.
        """
        for codes in Content._conditions.values():
            for cond_code, record in codes.items():
                yield record.model, cond_code, record


def register_content_junction(sender, **kwargs):
    """``class_prepared`` condition walk. Does not write a content map.

    Connected before ``Trust`` so ``:own`` registers from this hook.
    ``Junction`` is resolved at call time because it is defined later.
    """
    if sender._meta.proxy or sender._meta.abstract:
        return
    junction = globals().get('Junction')
    if junction is not None and issubclass(sender, junction):
        junction.register_junction(sender)
    elif issubclass(sender, Content):
        Content.register_content(sender)
signals.class_prepared.connect(register_content_junction)


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

    @staticmethod
    def register_junction(klass, content_model=None):
        """Register Junction ``content_permission_conditions`` only.

        Content-terminal declaration is an explicit AppConfig ``Ref``
        contribution. This method does not publish a model→path map.
        ``content_model`` is unused and retained for call-site compatibility.
        """
        _register_junction_content_permission_conditions(klass)

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
