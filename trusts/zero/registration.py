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


def _join_public_path(*parts):
    """Compose a Django ``__`` path from non-empty segments."""
    return '__'.join(part for part in parts if part)


def _trust_reverse_name(model):
    """Dynamic reverse accessor from ``Trust`` onto ``model``."""
    return model._meta.get_field('trust').remote_field.get_accessor_name()


def _content_via_trust(prefix, model):
    """Public ``__`` path: grant prefix → Trust → reverse onto ``model``."""
    return _join_public_path(prefix, 'trust', _trust_reverse_name(model))


def _content_path(model, content_via, prefix=''):
    """Resolve a customizable ``content_via`` to a public path string."""
    via = content_via if content_via is not None else _content_via_trust
    path = via(prefix, model)
    if not isinstance(path, str):
        raise TypeError(
            'content_via must return a Django __ path string, not %r.'
            % (type(path).__name__,)
        )
    return path


def _require_handle(handle):
    from trusts.core import BackendHandle

    if not isinstance(handle, BackendHandle):
        raise TypeError(
            'Zero relation helpers require a BackendHandle, not %r.'
            % (type(handle).__name__,)
        )
    return handle


def register_zero_direct(handle, content_models, content_via=None):
    """TUP records for each content terminal."""
    from trusts.zero.models import TrustUserPermission

    handle = _require_handle(handle)
    for model in content_models:
        handle.register(
            TrustUserPermission,
            user='entity',
            permission='permission',
            content=_content_path(model, content_via),
        )


def register_zero_group(handle, content_models, content_via=None):
    """Two alternative TGP registrations on the same bindings.

    Local TrustGroupPermission grant AND the group's direct
    ``permissions`` ceiling, or the same local grant AND the
    ``roles.permissions`` ceiling. The plan ORs complete records.
    """
    from trusts.core import permission_in
    from trusts.zero.models import TrustGroupPermission

    handle = _require_handle(handle)
    for model in content_models:
        content = _content_path(model, content_via, prefix='trustgroup')
        # auth.Group reverse membership is related_query_name="user"
        # (Python accessor remains group.user_set). Core path validation
        # uses _meta.get_field, so the hop must be the query name.
        handle.register(
            TrustGroupPermission,
            user='trustgroup__group__user',
            permission='permission',
            content=content,
            condition=permission_in('trustgroup__group__permissions'),
        )
        handle.register(
            TrustGroupPermission,
            user='trustgroup__group__user',
            permission='permission',
            content=content,
            condition=permission_in('trustgroup__group__roles__permissions'),
        )


def register_zero_content(handle, model, content_via=None):
    """TUP plus both TGP alternatives for one content terminal."""
    register_zero_direct(handle, (model,), content_via=content_via)
    register_zero_group(handle, (model,), content_via=content_via)


def register_zero_relations(handle):
    """Idempotent package donation: Trust-as-content TUP + both TGP alternatives."""
    from trusts.zero.models import Trust

    handle = _require_handle(handle)
    store = handle.registry
    ids = getattr(store, '_zero_z1_relation_ids', None)
    if ids is store:
        return
    register_zero_content(handle, Trust)
    store._zero_z1_relation_ids = store


def donate_content_permission_conditions(handle_or_registry, model):
    """Walk ``Meta.permission_conditions`` onto a handle or registry.

    Application donation uses ``BackendHandle.register_permission_condition``
    in the pre-finalization ``ready()`` window. Isolated tests may pass
    an unfrozen ``TrustsRegistry()``. Abstract and proxy models are skipped.
    """
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = getattr(model._meta, 'permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        handle_or_registry.register_permission_condition(
            model, cond_code, condition,
        )


def donate_junction_content_permission_conditions(handle_or_registry, model):
    """Walk Junction ``Meta.content_permission_conditions`` onto a handle."""
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = getattr(model._meta, 'content_permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        handle_or_registry.register_permission_condition(
            model, cond_code, condition,
        )


def _condition_store(handle_or_registry):
    return getattr(handle_or_registry, 'registry', handle_or_registry)


def donate_installed_permission_conditions(handle_or_registry, apps_registry=None):
    """Donate every installed Content/Junction Meta declaration.

    Idempotent per underlying registry so repeated ``ZeroConfig.ready()``
    does not invoke builders again. ``Trust:own``, Content Meta, and
    Junction Meta each become one IR record on this handle.
    """
    from django.apps import apps as django_apps
    from trusts.zero.models import Content, Junction

    store = _condition_store(handle_or_registry)
    donated = getattr(store, '_zero_condition_donation_id', None)
    if donated is store:
        return
    apps = django_apps if apps_registry is None else apps_registry
    for model in apps.get_models():
        if issubclass(model, Junction):
            donate_junction_content_permission_conditions(
                handle_or_registry, model,
            )
        elif issubclass(model, Content):
            donate_content_permission_conditions(handle_or_registry, model)
    store._zero_condition_donation_id = store
