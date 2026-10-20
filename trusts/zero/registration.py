"""Zero relation registration and condition donation."""

from django.apps import apps as django_apps

from trusts.backends import Recorder
from trusts.zero.models import (
    Content,
    Junction,
    Trust,
    TrustGroup,
    TrustGroupPermission,
    TrustUserPermission,
)


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
    recorder = _require_recorder(recorder)
    for model in content_models:
        recorder.register(
            trust=TrustUserPermission,
            user='entity',
            permission='permission',
            content=_content_path(model, content_via),
        )


def register_zero_group(recorder, content_models, content_via=None):
    """``auth.Group`` record plus the role ceiling. Two roots; the plan ORs them."""
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
    conditions = model._meta.original_attrs.get('permission_conditions', ())
    for cond_code, condition in conditions:
        recorder.add_named_filter(model, cond_code, condition)


def donate_junction_content_permission_conditions(recorder, model):
    """Walk Junction ``Meta.content_permission_conditions`` onto a recorder."""
    recorder = _require_recorder(recorder)
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = model._meta.original_attrs.get(
        'content_permission_conditions', (),
    )
    for cond_code, condition in conditions:
        recorder.add_named_filter(model, cond_code, condition)


def donate_installed_permission_conditions(recorder, apps_registry=None):
    """Donate every installed Content/Junction Meta declaration.

    Idempotent per recorder so repeated ``ZeroConfig.ready()`` does not
    record builders again. ``Trust:own``, Content Meta, and Junction Meta
    each become one condition on this recorder. The catalog build invokes
    each builder once.
    """
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
