from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from trusts.zero import (
    ENTITY_MODEL_NAME, PERMISSION_MODEL_NAME, GROUP_MODEL_NAME,
    DEFAULT_SETTLOR, ALLOW_NULL_SETTLOR, ROOT_PK,
)
from trusts import utils
from trusts.zero.policy import permission_in_global_ceiling
from trusts.zero.query import ContentManager, TrustManager


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
        permission_conditions = (
            ('own', lambda u, p, o: u == o.settlor),
        )

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
