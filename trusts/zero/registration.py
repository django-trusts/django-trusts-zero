"""Zero relation registration, Meta option names, and condition donation.

Safe for phase-1 import: this module must not import Zero models at
module level. ``ZeroConfig`` / ``apps.py`` import it so Zero-only
``Meta`` option names exist before Django constructs host models.
"""

from django.db.models import options


ZERO_META_OPTION_NAMES = (
    'roles',
    'content_roles',
    'content_permission_conditions',
    'auto_modeladmin',
)


def register_zero_meta_option_names():
    """Idempotently add Zero-only names to ``options.DEFAULT_NAMES``.

    Generic ``permission_conditions`` is registered by core
    ``trusts.conditions``. Calling this more than once must not
    duplicate names.
    """
    extra = tuple(
        name for name in ZERO_META_OPTION_NAMES
        if name not in options.DEFAULT_NAMES
    )
    if extra:
        options.DEFAULT_NAMES += extra
    return extra


register_zero_meta_option_names()


def _content_via_trust(root_ref, model):
    """Map a grant/TrustGroup root through Zero ``Trust`` onto ``model``."""
    rev = model._meta.get_field('trust').remote_field.get_accessor_name()
    return getattr(root_ref.trust, rev)


def _content_ref(root_ref, model, content_via):
    via = content_via if content_via is not None else _content_via_trust
    return via(root_ref, model)


def register_zero_direct(registry, content_models, content_via=None):
    """TUP records for each content terminal."""
    from trusts.core import Ref
    from trusts.zero.models import TrustUserPermission

    j = Ref(TrustUserPermission)
    for model in content_models:
        registry.register(
            content=_content_ref(j, model, content_via),
            user=j.entity,
            permission=j.permission,
        )


def register_zero_group(registry, content_models, content_via=None):
    """Two alternative TGP registrations on the same bindings.

    Local TrustGroupPermission grant AND the group's direct
    ``permissions`` ceiling, or the same local grant AND the
    ``roles.permissions`` ceiling. The plan ORs complete records.
    """
    from trusts.core import Ref, permission_in
    from trusts.zero.models import TrustGroupPermission

    g = Ref(TrustGroupPermission)
    for model in content_models:
        content = _content_ref(g.trustgroup, model, content_via)
        user = g.trustgroup.group.user_set
        permission = g.permission
        registry.register(
            content=content,
            user=user,
            permission=permission,
            condition=permission_in(g.trustgroup.group.permissions),
        )
        registry.register(
            content=content,
            user=user,
            permission=permission,
            condition=permission_in(g.trustgroup.group.roles.permissions),
        )


def register_zero_content(registry, model, content_via=None):
    """TUP plus both TGP alternatives for one content terminal."""
    register_zero_direct(registry, (model,), content_via=content_via)
    register_zero_group(registry, (model,), content_via=content_via)


def register_zero_relations(registry):
    """Idempotent package donation: Trust-as-content TUP + both TGP alternatives."""
    from trusts.zero.models import Trust

    ids = getattr(registry, '_zero_z1_relation_ids', None)
    if ids is registry:
        return
    register_zero_content(registry, Trust)
    registry._zero_z1_relation_ids = registry


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
    from trusts.zero.models import Content, Junction

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
