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

    ``permission_conditions`` is not a Meta option. Named filters are
    ``recorder.add_named_filter`` in ``AppConfig.ready``. Calling this
    more than once must not duplicate names.
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


def trust_settlor_owns(user, permission, obj):
    """``Trust:own`` builder: the principal is the settlor."""
    return user == obj.settlor


def _require_backend(backend):
    """Registration target: an app ``Recorder`` or an unfrozen ``Compiler``.

    Both expose ``register`` and ``add_named_filter``. A model class or
    a plain object does not.
    """
    register = getattr(type(backend), 'register', None)
    named = getattr(type(backend), 'add_named_filter', None)
    if not callable(register) or not callable(named):
        raise TypeError(
            'Zero relation helpers require a Trusts recorder, not %r.'
            % (type(backend).__name__,)
        )
    return backend


# Identity of the recorder or compiler that already received Trust
# relations or junction named filters. A second call does not register
# again. Recorder and Compiler are compared by identity.
_donated_relation_backends = set()
_donated_condition_backends = set()


def register_zero_direct(backend, content_models, content_via=None):
    """TUP records for each content terminal."""
    # Deferred import: trusts.zero.models. registration is imported from
    # the app config module during populate, before models can load.
    from trusts.zero.models import TrustUserPermission

    backend = _require_backend(backend)
    for model in content_models:
        backend.register(
            trust=TrustUserPermission,
            user='entity',
            permission='permission',
            content=_content_path(model, content_via),
        )


def register_zero_group(backend, content_models, content_via=None):
    """Explicit ``auth.Group`` registration plus the role ceiling.

    ``TrustGroup`` uses ``group=`` ending at Django ``auth.Group``.
    The compiler appends ``Group.permissions``. The local-grant
    condition keeps a bare association from authorizing. ``TrustGroupPermission``
    stays an ordinary ``permission=`` path for ``roles.permissions``.
    Core rejects different terminal bindings on one root and content
    model, so these are two roots. The plan ORs complete records.
    The role path is not Django group enumeration.
    """
    # Deferred import: trusts.zero.models. See register_zero_direct.
    from trusts.zero.models import TrustGroup, TrustGroupPermission

    backend = _require_backend(backend)
    for model in content_models:
        # auth.Group reverse membership is related_query_name="user"
        # (Python accessor remains group.user_set). Core path validation
        # uses _meta.get_field, so the hop must be the query name.
        # Do not append permissions; the compiler owns that hop.
        # .contains member is that compiler-owned permission path.
        backend.register(
            trust=TrustGroup,
            user='group__user',
            content=_content_path(model, content_via),
            group='group',
            condition=lambda t: t.permissions.contains(t.group.permissions),
        )
        backend.register(
            trust=TrustGroupPermission,
            user='trustgroup__group__user',
            permission='permission',
            content=_content_path(model, content_via, prefix='trustgroup'),
            condition=lambda t: t.trustgroup.group.roles.permissions.contains(
                t.permission,
            ),
        )


def register_zero_content(backend, model, content_via=None):
    """TUP, explicit ``auth.Group``, and the role ceiling for one terminal."""
    register_zero_direct(backend, (model,), content_via=content_via)
    register_zero_group(backend, (model,), content_via=content_via)


def register_zero_relations(backend):
    """Idempotent package donation: Trust-as-content TUP, group, and role."""
    # Deferred import: trusts.zero.models. See register_zero_direct.
    from trusts.zero.models import Trust

    backend = _require_backend(backend)
    if backend in _donated_relation_backends:
        return
    register_zero_content(backend, Trust)
    _donated_relation_backends.add(backend)


def donate_content_permission_conditions(backend, model):
    """No-op. ``Meta.permission_conditions`` is not a Meta option.

    Call ``recorder.add_named_filter(model, code, predicate)`` from the
    hosting app's ``ready`` before ``TrustsConfigMixin.ready`` freezes
    the recorder. Abstract and proxy models are still ignored so older
    callers that pass them do not raise.
    """
    backend = _require_backend(backend)
    if model._meta.proxy or model._meta.abstract:
        return
    return None


def donate_junction_content_permission_conditions(backend, model):
    """Walk Junction ``Meta.content_permission_conditions`` onto a backend."""
    backend = _require_backend(backend)
    if model._meta.proxy or model._meta.abstract:
        return
    conditions = getattr(model._meta, 'content_permission_conditions', ()) or ()
    for cond_code, condition in conditions:
        backend.add_named_filter(model, cond_code, predicate=condition)


def donate_installed_permission_conditions(backend, apps_registry=None):
    """Donate installed Junction ``Meta.content_permission_conditions``.

    Idempotent per recorder. Content named filters are not read from
    ``Meta``; the hosting app calls ``add_named_filter`` in ``ready``.
    """
    # Deferred import: django.apps, Junction. This module loads during
    # app-config import, before the registry can resolve models.
    # Callers run from ready() or tests.
    from django.apps import apps as django_apps
    from trusts.zero.models import Junction

    backend = _require_backend(backend)
    if backend in _donated_condition_backends:
        return
    apps = django_apps if apps_registry is None else apps_registry
    for model in apps.get_models():
        if issubclass(model, Junction):
            donate_junction_content_permission_conditions(backend, model)
    _donated_condition_backends.add(backend)
