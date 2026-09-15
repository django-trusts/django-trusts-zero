"""Zero write-time policy and Django permission-string codec.

Write-time group ceiling helpers are stored-fact checks for
``TrustGroupPermission.clean`` and grandfathering. They are not a
query compiler.

``resolve_content_permission`` / ``reject_queryable_condition`` are the
Zero Django-permission codec. Generic core and GH take permission
instances.
"""

from django.db.models import Q

from trusts import utils
from trusts.conditions import (
    PermissionConditionNotQueryable,
    permission_has_condition,
)
from trusts.zero import get_permission_model


def reject_queryable_condition(perm, api_name):
    if permission_has_condition(perm):
        raise PermissionConditionNotQueryable(
            '%s does not support permission conditions (%r). '
            'Create-under-trust filters Trust rows, not the content '
            'model the condition is registered on. Use the unconditioned '
            'permission for this queryset, or ContentQuerySet.permitted '
            'for V1 declarative conditions on content rows.' % (api_name, perm)
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
