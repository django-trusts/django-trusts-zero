# migrates.md — django-trusts-zero 1.0.0.dev0

This file is the mechanical checklist for moving a django-trusts 0.x
project onto `django-trusts-zero`. Stored schema and authorization
**data** stay compatible. Public **imports and settings** change.

Unrelated to Zero Trust network architecture.

Do **not** install a core Django app, call `kernel_config()`, list
`trusts.backends.TrustModelBackend`, or plan a later `dev4` cleanup.
Those surfaces are gone on the supported core library.

## Companion (current)

| Item | Value |
| --- | --- |
| Authoritative Zero metadata | this repo `pyproject.toml` (`1.0.0.dev0` + `django-trusts>=1.0.0.dev3,<2`) |
| Paired core #18/#120 | [django-trusts#121](https://github.com/django-trusts/django-trusts/pull/121) head [`a0104be138f5fbcc7d74ce1fce8054c3e1e89634`](https://github.com/django-trusts/django-trusts/commit/a0104be138f5fbcc7d74ce1fce8054c3e1e89634) |
| Previous merged core floor | [django-trusts#119](https://github.com/django-trusts/django-trusts/pull/119) merge [`6c705e284d37b10b7c29196a9ece88996273758e`](https://github.com/django-trusts/django-trusts/commit/6c705e284d37b10b7c29196a9ece88996273758e) |
| Zero #18 baseline | [`73b74b4213f6040f0e71c4c46d7a509804975672`](https://github.com/django-trusts/django-trusts-zero/commit/73b74b4213f6040f0e71c4c46d7a509804975672) |

# Zero #18: declarative models + receive core #120 UI

This is the Zero half of
[django-trusts-zero #18](https://github.com/django-trusts/django-trusts-zero/issues/18),
paired with [django-trusts#120](https://github.com/django-trusts/django-trusts/issues/120)
/ [django-trusts#121](https://github.com/django-trusts/django-trusts/pull/121).
Package version stays **1.0.0.dev0**. No model, field, table,
migration-loader key, content type, permission row, app label, or
authorization-semantic change. Group ceiling / reachability / condition
/ create-under-Trust stay the same; only the representation moves.

Core #120 stays open until this pair merges.

## Old → new imports

```python
# Old (trusts.zero.models / core leftovers)
from trusts.zero.models import (
    compile_registered_condition_q,
    django_permission_filter,
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
    filter_scope_rows,
    get_group_global_ceiling,
    permission_in_global_ceiling,
    register_zero_direct,
    register_zero_group,
    register_zero_relations,
    reject_queryable_condition,
    resolve_content_permission,
    ContentQuerySet, ContentManager, TrustManager,
    PermissionConditionNotQueryable,
)
from trusts.zero.backends import HistoricalGroupQueryCompiler
from trusts.authorization import AuthorizationDenied, has_trust_row_perm
from trusts.views import NewTeamView, TeamView, newteam, team
from trusts.urls import urlpatterns
from trusts.admin import register_auto_modeladmins
from django.urls import include, path
urlpatterns = [path('', include('trusts.urls'))]

# New
from trusts.zero.registration import (
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
    register_zero_content,
    register_zero_direct,
    register_zero_group,
    register_zero_relations,
)
from trusts.zero.query import (
    ContentQuerySet, ContentManager, TrustManager,
    compile_registered_condition_q,
    django_permission_filter,
    filter_scope_rows,
)
from trusts.zero.policy import (
    get_group_global_ceiling,
    permission_in_global_ceiling,
    reject_queryable_condition,
    resolve_content_permission,
)
from trusts.conditions import PermissionConditionNotQueryable
from trusts.core import PlanQueryCompiler
from trusts.zero.authorization import AuthorizationDenied, has_trust_row_perm
from trusts.zero.views import NewTeamView, TeamView, newteam, team
from trusts.zero.admin import register_auto_modeladmins
from django.urls import include, path
urlpatterns = [path('', include('trusts.zero.urls'))]
# HistoricalGroupQueryCompiler: removed; use PlanQueryCompiler
# Template overrides: auth/group_{detail,form}.html
#   → trusts_zero/team_{detail,form}.html
```

Supported model imports (`Trust`, `Content`, `Junction`, `Role`,
`TrustUserPermission`, `TrustGroup`, `TrustGroupPermission`,
`ReadonlyFieldsMixin`) stay on `trusts.zero.models`. URL namespace
`app_name = 'trusts'` is unchanged (`trusts:team_create`,
`trusts:team_detail`); only the include path changes.

`has_trust_row_perm` now uses `Trust.objects.filter_by_user_content_perm`
/ public core `filter_authorized_scopes`. Trust-as-content is
self-referential; core includes proper prefixes of the terminal model
(terminal-only same-model still `none()`). There is no Zero wrapper and
no `trust_grant_q` fallback. Group enumeration uses core
`PlanQueryCompiler.group_exists` on membership-hop records (no Zero
import-time patch, no historical group SQL).

Zero-only `Meta` option names (`roles`, `content_roles`,
`content_permission_conditions`, `auto_modeladmin`) are registered when
`trusts.zero.apps` is imported, not in `ZeroConfig.ready()` and not by
importing `trusts.zero.models`. Generic `permission_conditions` is
registered by core `trusts.conditions`.

## Removed (no alias)

| Name | Note |
| --- | --- |
| `_has_tgp_records` | Internal. Create-under-Trust always uses `filter_authorized_scopes`. |
| `_content_via_trust` | Internal to `trusts.zero.registration`. |
| `HistoricalGroupQueryCompiler` / `historical_fallback` | Deleted. Isolation is records present vs absent. |
| `trusts.zero.models.PermissionConditionNotQueryable` | Import `trusts.conditions.PermissionConditionNotQueryable`. |
| core `trusts.authorization` / `trusts.views` / `trusts.urls` / `trusts.admin` | Zero owns these concrete surfaces. |
| core `trust_grant_q` / `historical_group_grant_exists` / `group_local_grant_exists` / `permission_granted_via_group_exists` | Deleted on the core half. Use registered plans + `granted` / `filter_authorized_scopes`. |

## Host AppConfig note

Hosts that previously donated only TUP and relied on
`HistoricalGroupQueryCompiler` must call `register_zero_content(registry, Model)`
(TUP + both TGP alternatives) for each terminal. `register_zero_relations`
still donates Trust-as-content only.

## Migration-bot search list

```text
from trusts.zero.models import compile_registered_condition_q
from trusts.zero.models import django_permission_filter
from trusts.zero.models import donate_
from trusts.zero.models import filter_scope_rows
from trusts.zero.models import get_group_global_ceiling
from trusts.zero.models import permission_in_global_ceiling
from trusts.zero.models import register_zero_
from trusts.zero.models import reject_queryable_condition
from trusts.zero.models import resolve_content_permission
from trusts.zero.models import ContentQuerySet
from trusts.zero.models import ContentManager
from trusts.zero.models import TrustManager
from trusts.zero.models import PermissionConditionNotQueryable
from trusts.zero.backends import HistoricalGroupQueryCompiler
from trusts.authorization import
from trusts.views import
from trusts.urls import
from trusts.admin import
include('trusts.urls')
auth/group_detail.html
auth/group_form.html
historical_fallback
historical_group_grant_exists
group_local_grant_exists
permission_granted_via_group_exists
_record_group_grant_exists
_trust_group_model
trust_grant_q
_has_tgp_records
```

Unchanged public calls: `User.has_perm`,
`ContentQuerySet.permitted(perm, user)`,
`Trust.objects.filter_by_user_content_perm(...)`,
`Meta.permission_conditions` / `content_permission_conditions` /
`Trust:own`, `TrustGroupPermission.clean` fail-closed, create-under-Trust
resolving the **content** permission (`add_category`, not `add_trust`).

Earlier unpublished Zero snapshots used `2.0.0.dev0` / `dev1` / `dev2`.
They are not a public compatibility line and are not a downgrade path.

## Public old / new

| Surface | Old (django-trusts 0.x) | New (`django-trusts-zero==1.0.0.dev0`) |
| --- | --- | --- |
| Distribution | `django-trusts` (library + concrete models) | `django-trusts` (library) + `django-trusts-zero` |
| `INSTALLED_APPS` | `'trusts'` | **`'trusts.zero.apps.ZeroConfig'` only**. Do not add `'trusts'`. |
| Backend settings | `'trusts.backends.TrustModelBackend'` | `'trusts.zero.backends.TrustModelBackend'` |
| Backend import | `from trusts.backends import TrustModelBackend` | `from trusts.zero.backends import TrustModelBackend` |
| Models | `from trusts.models import Trust, Content, Junction` | `from trusts.zero.models import Trust, Content, Junction` |
| Settings constants | `from trusts import ENTITY_MODEL_NAME, ROOT_PK, …` | `from trusts.zero import ENTITY_MODEL_NAME, ROOT_PK, …` |
| Owner / registry | historical monolithic app | `ZeroConfig(TrustsImplementationConfig)` + `implementation_for_path` / `zero_config()` |
| Core `AppConfig` / `kernel_config()` | existed on older trees | **removed**. Do not import or call them. |
| Django app label | `trusts` | **`trusts`** (unchanged, owned by `ZeroConfig`) |
| Migration names | `0001_initial`, `0002_trustgroup` | **unchanged** loader keys `trusts.0001_initial` / `trusts.0002_trustgroup` |
| Tables / content types / permissions | `trusts_trust`, `trusts \| trust`, … | **unchanged** |

### Startup and failure behavior

| Situation | Result on this revision |
| --- | --- |
| Canonical settings (`ZeroConfig` + Zero backend path) | Starts. No core `AppConfig`. Exactly one implementation owner (`ZeroConfig`). |
| `'trusts'` in `INSTALLED_APPS` | Unsupported. Core is a library and ships no Django app. |
| `AUTHENTICATION_BACKENDS = ['trusts.backends.TrustModelBackend']` | **`ImproperlyConfigured`** naming `trusts.zero.backends.TrustModelBackend`. No forwarding. |
| Both backend paths listed | **`ImproperlyConfigured`** (old path is not Zero identity) |
| Canonical path missing | **`ImproperlyConfigured`** from `ZeroConfig.ready()` |
| Core below `1.0.0.dev3` | **Metadata refuse** (`Requires-Dist: django-trusts>=1.0.0.dev3,<2`) and **startup belt** `ImproperlyConfigured` if `TrustsImplementationConfig` is missing |

Do **not** add transparent core-path forwarding or make the old backend
path succeed.

## Migration identity (unchanged)

Loader keys remain `('trusts', '0001_initial')` / `('trusts', '0002_trustgroup')`
because `ZeroConfig.label = 'trusts'`. No `MIGRATION_MODULES`. No `0003`.
`0002` still `dependencies = [('trusts', '0001_initial')]` and
`database_operations=[]`.

Already-applied 0.x databases keep matching `django_migrations` rows.
`python -m django migrate --plan` has no Trusts operations on an
already-current database. `makemigrations trusts --check` is quiet.

## Migration-bot checklist

Search application code and settings for:

```text
INSTALLED_APPS.*trusts
AUTHENTICATION_BACKENDS.*trusts.backends
from trusts.backends import TrustModelBackend
from trusts.apps import kernel_config
from trusts.apps import AppConfig
from trusts.models import
from trusts import ENTITY_MODEL_NAME
from trusts import ROOT_PK
.content.grant(
.content.revoke(
.associate_group(
.grant_group_permission(
.revoke_group_permission(
.set_group_permissions(
.grant_permission(
.set_permissions(
```

Then:

- [ ] Install `django-trusts-zero` (it pulls `django-trusts` 1.x). Do not add `'trusts'` to `INSTALLED_APPS`.
- [ ] Set `INSTALLED_APPS` to `'trusts.zero.apps.ZeroConfig'` (plus Django contrib).
- [ ] Set `AUTHENTICATION_BACKENDS` to `'trusts.zero.backends.TrustModelBackend'`. Remove `'trusts.backends.TrustModelBackend'`.
- [ ] Replace `from trusts.backends import TrustModelBackend` with `from trusts.zero.backends import TrustModelBackend`.
- [ ] Replace `from trusts.models import …` with `from trusts.zero.models import …`.
- [ ] Move settings constants used by migrations/commands to `trusts.zero`.
- [ ] Delete any `kernel_config()` or core `AppConfig` usage. Those names are not on the supported core library.
- [ ] Confirm startup: canonical settings succeed; old backend path raises `ImproperlyConfigured`.
- [ ] Confirm no installed core `AppConfig` and exactly one implementation owner.
- [ ] `python -m django migrate --plan` — no Trusts operations on an already-current database.
- [ ] `python -m django makemigrations trusts --check` — quiet.
- [ ] Confirm `ContentType` natural keys `trusts | trust` (and siblings) and `COUNT(*)` on every Trusts table are unchanged.
- [ ] Confirm model labels, migration keys, permissions, and representative rows are unchanged.
- [ ] Confirm object/list authorization, fail-closed anonymous/inactive/undeclared cases, and fixed query counts.
- [ ] Confirm `pip` rejects `django-trusts==1.0.0.dev2` against this wheel (`>=1.0.0.dev3,<2`).
- [ ] Confirm `pip uninstall django-trusts-zero` does not delete `trusts/__init__.py`.
- [ ] Confirm uninstalling core makes `trusts.zero.backends` unusable.
- [ ] Replace `Content.grant`/`revoke`, `Trust.associate_group`/`grant_group_permission`/`revoke_group_permission`/`set_group_permissions`, and `TrustGroup.grant_permission`/`revoke_permission`/`set_permissions` with the ORM snippets in the archived section below. Do not restore those methods.
- [ ] Keep ceiling writes on `TrustGroupPermission` (`.full_clean()` / `save` / `bulk_create`); do not bypass `local_grant_outside_ceiling`.
- [ ] `filter_by_user_content_perm(user, ContentModel, 'add')` must keep authorizing the **content** permission (e.g. `add_category`), not `add_trust`.

## Write conveniences (direct ORM)

Write conveniences are gone. Actor gating stays application code after
a read/guard. `TrustGroupPermission.clean` / `save` / `bulk_create`
still reject local grants outside the group's global ceiling.

```python
perm = Receipt.objects.get_permission('read')

TrustUserPermission.objects.get_or_create(
    trust=receipt.trust, entity=trustee, permission=perm)
TrustUserPermission.objects.filter(
    trust=receipt.trust, entity=trustee, permission=perm).delete()

trust.groups.add(accountants)
trust.groups.remove(accountants)

tg, _ = TrustGroup.objects.get_or_create(trust=trust, group=accountants)
TrustGroupPermission.objects.get_or_create(trustgroup=tg, permission=perm)
TrustGroupPermission.objects.filter(trustgroup=tg, permission=perm).delete()

accountants.user_set.add(user)
accountants.permissions.add(perm)  # global ceiling
```

Create-under-Trust: `Trust.objects.filter_by_user_content_perm(user, Category, 'add')` must resolve `add_category`, not `add_trust`. A trustee grant of `add_trust` alone is insufficient.

# Zero #16: donate conditions to the core handle registry

This record is the Zero half of
[django-trusts-zero #16](https://github.com/django-trusts/django-trusts-zero/issues/16),
paired with [django-trusts#118](https://github.com/django-trusts/django-trusts/pull/118)
merge `948d6666342377b9472debb57d4a1e26e81402d1`. Package version stays
**1.0.0.dev0**. No model, table, migration-loader key, content type,
permission row, or stored authorization-data change.

Core #118 already started this section on the library side. This file
records the consumer-facing Zero deletion and Meta donation.

## Decision

Reusable records, registration-time shape validation, lookup,
iteration, `Expr` compile/evaluate, and
`TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS` live in core
(`trusts.conditions` / each `TrustsRegistry`). Zero keeps only the
model-specific collection of:

- `Meta.permission_conditions`
- `Meta.content_permission_conditions`
- built-in `Trust:own` (`u == o.settlor`)

Those tuples are donated onto the configured Zero handle registry.
There is no `Content._conditions` store. `ZeroConfig` binds
`RegistryConditionLookup(handle.registry)`.

## No change to these public call sites

- `User.has_perm` / `ContentQuerySet.permitted` signatures and
  fail-closed results
- `Meta.permission_conditions` and
  `Meta.content_permission_conditions` (still collected by Zero)
- Callable opt-in: missing / `False` (default) never invokes a
  callback; `True` keeps object-only `has_perm` plus `trusts.W001`
- Stored identity: app label `trusts`, Zero migration keys, tables,
  content types, permissions, and rows

## Changes

### Explicit condition registration moves to the handle registry

| | |
| --- | --- |
| Previous | Zero `Content` static methods owned a process-global `_conditions` map. `Junction.register_junction` was a static wrapper. `ContentConditionLookup` was bound from `ZeroConfig`. |
| New | `TrustsRegistry.register_permission_condition` / `get_permission_condition_record` / `iter_permission_conditions`. Bind `RegistryConditionLookup(handle.registry)`. |
| Replacement | Call the configured handle registry from AppConfig / module contribution helpers. Do not add forwarding methods on Zero models. |
| Affected | Explicit `Content.register_permission_condition` callers. `Meta.permission_conditions` behavior is unchanged when Zero donates those tuples. |
| Authorization | Unchanged. Unknown / malformed / unbound conditions fail closed. Callables stay object-only and are never invoked by checks or queryset compilation. |

Exact old / new imports and calls:

```python
# Old (Zero model static methods — deleted)
from trusts.zero.models import Content, Junction
from trusts.conditions import condition_refs

u, p, o = condition_refs()
Content.register_permission_condition(Ticket, 'own', u == o.owner)
Content.register_content(Ticket)
record = Content.get_permission_condition_record(Ticket, 'own')
func = Content.get_permission_condition_func(Ticket, 'own')
for model, code, record in Content.iter_permission_conditions():
    ...
Junction.register_junction(TicketJunction, content_model=Ticket)

# New (core registry APIs; Zero donates Meta declarations here)
from trusts.conditions import (
    ConditionRegistry,
    RegistryConditionLookup,
    condition_refs,
    legacy_permission_callbacks_allowed,
)
from trusts.core import TrustsRegistry
from trusts.zero.apps import CANONICAL_BACKEND_PATH, zero_config
from trusts.zero.models import (
    donate_content_permission_conditions,
    donate_installed_permission_conditions,
    donate_junction_content_permission_conditions,
)

u, p, o = condition_refs()
registry = zero_config().configured_backend(CANONICAL_BACKEND_PATH).registry
registry.register_permission_condition(Ticket, 'own', u == o.owner)
record = registry.get_permission_condition_record(Ticket, 'own')
for model, code, record in registry.iter_permission_conditions():
    ...
# Meta-only apps: ZeroConfig already donated; helpers are for late models
donate_content_permission_conditions(registry, Ticket)
donate_junction_content_permission_conditions(registry, TicketJunction)
donate_installed_permission_conditions(registry)
handle.registry.set_condition_lookup(RegistryConditionLookup(handle.registry))

# Isolated tests / extra owners: a new TrustsRegistry() starts empty
isolated = TrustsRegistry()
isolated.register_permission_condition(Ticket, 'own', u == o.owner)
```

Unchanged `Meta` behavior (Zero still walks these and donates):

```python
class Ticket(Content):
    class Meta:
        permission_conditions = (
            ('own', u == o.owner),
        )

class TicketJunction(Junction):
    class Meta:
        content_permission_conditions = (
            ('via_ticket', u == o.owner),
        )
```

`Trust:own` remains `u == o.settlor` and is donated once to the
configured implementation registry.

Unchanged callable opt-in:

```python
# default / missing / False: trusts.E002 and runtime fail-closed
# (callback never invoked)
TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS = True  # object-only has_perm + W001
```

Import the gate from core; Zero no longer defines a local copy:

```python
from trusts.conditions import legacy_permission_callbacks_allowed
```

## Deleted consumer-facing APIs

These names are removed from Zero models. There is no transparent
forwarding on `Content` or `Junction`.

| Removed | Replacement |
| --- | --- |
| `Content.register_permission_condition` | `handle.registry.register_permission_condition` |
| `Content.register_content` | `donate_content_permission_conditions` / `donate_installed_permission_conditions` |
| `Content.get_permission_condition_record` | `handle.registry.get_permission_condition_record` |
| `Content.get_permission_condition_func` | Deleted (no supported caller). Use `record.func` from `get_permission_condition_record` |
| `Content.iter_permission_conditions` | `handle.registry.iter_permission_conditions` or `trusts.checks.iter_live_permission_conditions` |
| `Content._conditions` | Per-handle `TrustsRegistry.conditions` (`ConditionRegistry`) |
| `Junction.register_junction` | `donate_junction_content_permission_conditions` |
| `ContentConditionLookup` | `trusts.conditions.RegistryConditionLookup` |
| Zero `legacy_permission_callbacks_allowed` | `trusts.conditions.legacy_permission_callbacks_allowed` |

`PermissionConditionNotQueryable` is imported from
`trusts.conditions` only. There is no `trusts.zero.models` alias.

## Old vs new behavior

| Situation | Old (Zero-owned `Content._conditions`) | New (core handle registry) |
| --- | --- | --- |
| Explicit `register_permission_condition` | `Content.register_permission_condition(...)` | `handle.registry.register_permission_condition(...)` |
| `Meta.permission_conditions` | Zero walks Meta onto `Content._conditions` | Zero walks Meta onto `handle.registry` (behavior unchanged) |
| Two implementation owners | One process-global map | Isolated `TrustsRegistry` instances |
| Repeated test / AppConfig registries | Global `_conditions` leaked unless restored | New `TrustsRegistry()` / `ConditionRegistry()` starts empty |
| `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS` missing / False | Fail closed; callback never invoked | Unchanged (gate lives in core) |
| Flag True | Object-only `has_perm` + `trusts.W001` | Unchanged |
| System checks / queryset compile | Never invoke callables | Unchanged |
| `ContentConditionLookup` | Zero class bound from `ZeroConfig` | Generic `RegistryConditionLookup` bound the same way |

## Schema

No change. This slice adds no model, table, migration, app-label, or
package boundary.

## Migration-bot checklist

Search the project (and every remaining Zero caller) for every
removed method and replace it with the core registry API. Do not
leave a forwarding alias on `Content` or `Junction`.

- [ ] Search for `register_permission_condition` (including
      `Content.register_permission_condition`). Retarget explicit
      calls to `handle.registry.register_permission_condition`.
- [ ] Search for `Content.register_content`. Replace with
      `donate_content_permission_conditions` /
      `donate_installed_permission_conditions`.
- [ ] Search for `get_permission_condition_record`. Retarget to
      `handle.registry.get_permission_condition_record`.
- [ ] Search for `get_permission_condition_func`. Delete the call;
      use `record.func` from `get_permission_condition_record` if a
      caller still needs the callable.
- [ ] Search for `iter_permission_conditions`. Retarget to
      `handle.registry.iter_permission_conditions` or
      `trusts.checks.iter_live_permission_conditions`.
- [ ] Search for `Content._conditions`. There is no global map;
      use the configured handle's `registry.conditions`.
- [ ] Search for `register_junction` / `Junction.register_junction`.
      Replace with `donate_junction_content_permission_conditions`.
- [ ] Search for `ContentConditionLookup`. Bind
      `RegistryConditionLookup(handle.registry)` instead.
- [ ] Search for `legacy_permission_callbacks_allowed` defined in
      Zero models. Import it from `trusts.conditions`.
- [ ] Confirm `Meta.permission_conditions` and
      `Meta.content_permission_conditions` still register through
      Zero donation (no host rewrite required for Meta-only apps).
- [ ] Confirm callable opt-in is unchanged: default fail-closed;
      `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS = True` is
      object-only `has_perm` plus `trusts.W001`.
- [ ] Confirm checks and queryset compilation never invoke
      callables.
- [ ] Do not apply a new Trusts schema or data migration; none was
      added.
- [ ] Leave Zero package version at `1.0.0.dev0` and core floor at
      `1.0.0.dev3`.

## Out of scope (this slice)

- Core README rewrite
- GH / Windows README or conversion
- Example deployment
- Stable release-number decision
- New authorization semantics

---

# Archived: unpublished internal staircase

The remainder is historical evidence from unpublished Zero development
snapshots. It is **not** the current upgrade path. Do not follow
archived `INSTALLED_APPS = 'trusts' + ZeroConfig`, `kernel_config()`,
core `AppConfig`, `trusts.backends.TrustModelBackend`, or `dev4`
instructions.

## Archived IIa record (unpublished `2.0.0.dev2`)

Internal Zero-owned AppConfig cut against core Step I
`django-trusts==1.0.0.dev2` (merge `39f1f9611e214193aec4e97526cf9b54ee689967`).
That core still exported `kernel_config()` as a `LookupError` helper and
a temporary historical backend class. Final core deleted both.

| Surface | Then-old (unpublished Z1) | Then-new (unpublished IIa) |
| --- | --- | --- |
| Distribution | `django-trusts-zero==2.0.0.dev0` + `django-trusts>=1.0.0.dev0` | `django-trusts-zero==2.0.0.dev2` + `django-trusts>=1.0.0.dev2,<2` |
| `INSTALLED_APPS` | `'trusts'` then `'trusts.zero.apps.ZeroConfig'` | `'trusts.zero.apps.ZeroConfig'` only |
| Backend | `'trusts.backends.TrustModelBackend'` | `'trusts.zero.backends.TrustModelBackend'` |
| Owner API | `kernel_config()` swallow in `ZeroConfig.ready()` | `ZeroConfig` + `implementation_for_path` / `zero_config()` |

## Archived Z1 reconstitution (unpublished `2.0.0.dev0`)

Implemented against [django-trusts-zero#7](https://github.com/django-trusts/django-trusts-zero/issues/7)
and [django-trusts#54](https://github.com/django-trusts/django-trusts/issues/54).
Persisted identity rows below remain true; the `INSTALLED_APPS` /
`kernel_config()` contract does not.

| Item | Historical value |
| --- | --- |
| Authoritative Zero metadata then | `2.0.0.dev0` + `django-trusts>=1.0.0.dev0` |
| Paired C1 APIs | [django-trusts#95](https://github.com/django-trusts/django-trusts/pull/95) merge [`ffb02364a45f3a4bc2b9a3973de3612c37d785e9`](https://github.com/django-trusts/django-trusts/commit/ffb02364a45f3a4bc2b9a3973de3612c37d785e9) |
| Zero baseline | [`c174388f015d3858d09f3bbd581f72d9e830e577`](https://github.com/django-trusts/django-trusts-zero/commit/c174388f015d3858d09f3bbd581f72d9e830e577) |
| Preserved evidence | [`c60c7eab86bb31f30fe9acb8e83041f14d1c5ac7`](https://github.com/django-trusts/django-trusts-zero/commit/c60c7eab86bb31f30fe9acb8e83041f14d1c5ac7) |

Historical Z1 still moved `0001_initial.py` and `0002_trustgroup.py` to
`trusts.zero.migrations` with **import-only** rewrites:

```python
from trusts.zero import (
    ENTITY_MODEL_NAME, GROUP_MODEL_NAME, PERMISSION_MODEL_NAME,
    DEFAULT_SETTLOR, ALLOW_NULL_SETTLOR, ROOT_PK,
)
from trusts.zero.management.commands.create_trust_root import create_root_trust
from trusts.zero.models import ReadonlyFieldsMixin
```

Loader keys remained `('trusts', '0001_initial')` /
`('trusts', '0002_trustgroup')` because `ZeroConfig.label = 'trusts'`.

| | Old (C1 `ContentQuerySet.permitted`) | Z1 |
| --- | --- | --- |
| Signature | `permitted(perm, user)` | **unchanged** |
| Inactive / anonymous | empty queryset | **unchanged** |
| Superuser short-circuit | not duplicated | **unchanged** |
| `:condition` Expr | AND overlay in SQL | **unchanged** (compiled in Zero, passed as `extra_q`) |
| Callable `:condition` | `PermissionConditionNotQueryable` | **unchanged** |
| Plan sequencing | Zero/core `aggregate_granted` / handle loop | **core** `.authorized` only |
| `get_permission` | manager method | **retained** |
| Fail-closed undeclared | empty | **unchanged** (`any_plan_records`) |
| Write conveniences | `Content.grant` / `revoke`, `Trust.associate_group` / `grant_group_permission*`, `TrustGroup.grant_permission*` | **deleted**; direct ORM |

Forbidden then and now:

- bare `'trusts.zero'` as a substitute for `trusts.zero.apps.ZeroConfig`
- Zero shipping `trusts/__init__.py`
- copying `granted` / `HistoricalGroupQueryCompiler` / `compose` into Zero
- restoring grant/revoke/associate façades on `Content` / `Trust` / `TrustGroup`
