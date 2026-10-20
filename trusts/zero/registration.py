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

    Generic ``permission_conditions`` is registered by importing
    ``trusts.apps``. Calling this more than once must not duplicate names.
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


def _require_recorder(recorder):
    from trusts.backends import Recorder

    if not isinstance(recorder, Recorder):
        raise TypeError(
            'Zero relation helpers require a Recorder, not %r.'
            % (type(recorder).__name__,)
        )
    return recorder


# One donation per recorder. A new recorder donates again; the same
# recorder does not.
_donated_relation_recorders = set()
_donated_condition_recorders = set()


def register_zero_direct(recorder, content_models, content_via=None):
    """TUP records for each content terminal."""
    from trusts.zero.models import TrustUserPermission

    recorder = _require_recorder(recorder)
    for model in content_models:
        recorder.register(
            trust=TrustUserPermission,
            user='entity',
            permission='permission',
            content=_content_path(model, content_via),
        )


def register_zero_group(recorder, content_models, content_via=None):
    """Explicit ``auth.Group`` registration plus the role ceiling.

    ``TrustGroup`` uses ``group=`` ending at Django ``auth.Group``.
    The compiler appends ``Group.permissions``. The local-grant
    condition keeps a bare association from authorizing. ``TrustGroupPermission``
    stays an ordinary ``permission=`` path for ``roles.permissions``.
    Core rejects different terminal bindings on one root and content
    model, so these are two roots. The plan ORs complete records.
    The role path is not Django group enumeration.
    """
    from trusts.zero.models import TrustGroup, TrustGroupPermission

    recorder = _require_recorder(recorder)
    for model in content_models:
        # auth.Group reverse membership is related_query_name="user"
        # (Python accessor remains group.user_set). Core path validation
        # uses _meta.get_field, so the hop must be the query name.
        # Do not append permissions; the compiler owns that hop.
        # .contains member is that compiler-owned permission path.
        recorder.register(
            trust=TrustGroup,
            user='group__user',
            content=_content_path(model, content_via),
            group='group',
            condition=lambda t: t.permissions.contains(t.group.permissions),
        )
        recorder.register(
            trust=TrustGroupPermission,
            user='trustgroup__group__user',
            permission='permission',
            content=_content_path(model, content_via, prefix='trustgroup'),
            condition=lambda t: t.trustgroup.group.roles.permissions.contains(
                t.permission,
            ),
        )


def register_zero_content(recorder, model, content_via=None):
    """TUP, explicit ``auth.Group``, and the role ceiling for one terminal."""
    register_zero_direct(recorder, (model,), content_via=content_via)
    register_zero_group(recorder, (model,), content_via=content_via)


def register_zero_relations(recorder):
    """Idempotent package donation: Trust-as-content TUP, group, and role."""
    from trusts.zero.models import Trust

    recorder = _require_recorder(recorder)
    if recorder in _donated_relation_recorders:
        return
    register_zero_content(recorder, Trust)
    _donated_relation_recorders.add(recorder)


def donate_content_permission_conditions(recorder, model):
    """Walk ``Meta.permission_conditions`` onto a recorder.

    Application donation uses ``Recorder.add_named_filter`` before the
    catalog is built. Abstract and proxy models are skipped.
    """
    recorder = _require_recorder(recorder)
    if model._meta.proxy or model._meta.abstract:
        return
    # Django sets the option only when this model's Meta declares it.
    conditions = getattr(model._meta, 'permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        recorder.add_named_filter(model, cond_code, condition)


def donate_junction_content_permission_conditions(recorder, model):
    """Walk Junction ``Meta.content_permission_conditions`` onto a recorder."""
    recorder = _require_recorder(recorder)
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = getattr(model._meta, 'content_permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        recorder.add_named_filter(model, cond_code, condition)


def donate_installed_permission_conditions(recorder, apps_registry=None):
    """Donate every installed Content/Junction Meta declaration.

    Idempotent per recorder so repeated ``ZeroConfig.ready()`` does not
    record builders again. ``Trust:own``, Content Meta, and Junction Meta
    each become one condition on this recorder. The catalog build invokes
    each builder once.
    """
    from django.apps import apps as django_apps
    from trusts.zero.models import Content, Junction

    recorder = _require_recorder(recorder)
    if recorder in _donated_condition_recorders:
        return
    apps = django_apps if apps_registry is None else apps_registry
    for model in apps.get_models():
        if issubclass(model, Junction):
            donate_junction_content_permission_conditions(recorder, model)
        elif issubclass(model, Content):
            donate_content_permission_conditions(recorder, model)
    _donated_condition_recorders.add(recorder)
