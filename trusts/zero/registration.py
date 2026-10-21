"""Zero relation registration.

Safe for phase-1 import: this module must not import Zero models at
module level. Model classes are resolved from the app registry when a
helper runs, which is after Django has loaded models.
"""

from django.apps import apps as django_apps

from trusts.apps import Recorder


# One donation per recorder. A new recorder donates again; the same
# recorder does not.
_donated_relation_recorders = set()


def trust_settlor_owns(user, permission, obj):
    """``Trust:own`` builder: the principal is the settlor."""
    return user == obj.settlor


def register_zero_direct(recorder, content_models, content_via=None):
    """TUP records for each content terminal."""
    recorder = _require_recorder(recorder)
    trust_user_permission = django_apps.get_model('trusts', 'TrustUserPermission')
    for model in content_models:
        recorder.register(
            trust=trust_user_permission,
            user='entity',
            permission='permission',
            content=_content_path(model, content_via),
        )


def register_zero_group(recorder, content_models, content_via=None):
    """``auth.Group`` record plus the role ceiling. Two roots; the plan ORs them."""
    recorder = _require_recorder(recorder)
    trust_group = django_apps.get_model('trusts', 'TrustGroup')
    trust_group_permission = django_apps.get_model('trusts', 'TrustGroupPermission')
    for model in content_models:
        # auth.Group reverse membership is related_query_name="user"
        # (Python accessor remains group.user_set). Core path validation
        # uses _meta.get_field, so the hop must be the query name.
        # Do not append permissions; the compiler owns that hop.
        # .contains member is that compiler-owned permission path.
        recorder.register(
            trust=trust_group,
            user='group__user',
            content=_content_path(model, content_via),
            group='group',
            condition=lambda t: t.permissions.contains(t.group.permissions),
        )
        recorder.register(
            trust=trust_group_permission,
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
    trust = django_apps.get_model('trusts', 'Trust')
    register_zero_content(recorder, trust)
    _donated_relation_recorders.add(recorder)


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
