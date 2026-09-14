"""Zero list/object adapters over core ``granted`` / ``filter_authorized_scopes``.

``ContentQuerySet``, ``ContentManager``, and ``TrustManager`` live here
so ``models.py`` stays declarative. Manager *attachment* remains on the
model classes.
"""

from django.db import models
from django.db.models import Model, Q

from trusts.core import (
    TrustsConfigurationError,
    any_plan_records,
    filter_authorized_scopes,
    granted,
)
from trusts.conditions import permission_has_condition
from trusts.query import AuthorizedQuerySet, is_active_principal
from trusts.zero import (
    ROOT_PK,
    supported_entity_contract,
    supported_permission_contract,
)
from trusts.zero.policy import (
    reject_queryable_condition,
    resolve_content_permission,
)


def compile_registered_condition_q(model, perm, user):
    """Compile a ``:condition`` suffix via the configured Zero backend.

    Records live on that backend's core registry. Unregistered codes
    raise ``AttributeError``. Runtime ``has_perm`` treats a missing
    local name as a fail-closed non-match. Callables raise
    ``PermissionConditionNotQueryable`` without being invoked.
    """
    from trusts.zero.apps import CANONICAL_BACKEND_PATH, zero_config

    registry = zero_config().configured_backend(CANONICAL_BACKEND_PATH).registry
    return registry.compile_registered_condition_q(model, perm, user)
