# migrates.md — django-trusts-zero 1.0.0.dev0

This file is the **executable 0.x → Zero route**. Stored schema and
authorization **data** stay compatible. Public **imports and settings**
change.

Unrelated to Zero Trust network architecture.

Do **not** install a core Django app, call `kernel_config()`, list
`trusts.backends.TrustModelBackend`, or plan a later `dev4` cleanup.
Those surfaces are gone on the supported core library. The core floor
is `django-trusts>=1.0.0.dev3,<2`. Do not follow a companion-SHA
staircase.

## Audience

- **Upgrading django-trusts 0.x** (concrete Trust / Content / TUP / TGP):
  install `django-trusts-zero` and execute this checklist.
- **Schema-neutral Core-only adopters:** this guide is not your route.
  The Core 1.x migration router is forthcoming on django-trusts `dev`.
  Until then, use the existing Core README and authorization guide:
  [README](https://github.com/django-trusts/django-trusts/blob/dev/README.md)
  and
  [docs/source/index.rst](https://github.com/django-trusts/django-trusts/blob/dev/docs/source/index.rst).

## Upgrade ordering

Execute in this order. Fail closed at each step.

1. Install `django-trusts-zero` (it pulls `django-trusts` 1.x).
2. Point `INSTALLED_APPS` and `AUTHENTICATION_BACKENDS` at Zero. Remove
   bare `'trusts'` and the old backend path.
3. Retarget model, backend, and settings-constant imports.
4. Register condition **builders** on the handle in `AppConfig.ready()`.
5. Retarget views, URL include, templates, admin, and management-command
   imports to Zero-owned paths.
6. Replace removed convenience writers with direct ORM.
7. `migrate --plan` / `makemigrations trusts --check` (no new Trusts
   operations on an already-current database).
8. Run `create_trust_root`, `grandfather_trust_group_permissions`, and
   `update_roles_permissions` only when those operator actions apply.
9. Verify representative allow/deny, ContentTypes, table counts, and
   fail-closed startup.

## Package / settings / AppConfig / backend

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

| Situation | Result |
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

`ContentType` natural keys (`trusts | trust` and siblings), model
labels, permissions, and `COUNT(*)` on every Trusts table stay the same.

## Conditions (current rule)

Register a **builder**. Core invokes it once with symbolic `(u, p, o)`,
stores IR, and never calls it during `has_perm` or `.permitted()`.

Production must **not** import `trusts.conditions._ir` or call
`set_condition_lookup`. `ZeroConfig` donates TUP / TGP and Meta
conditions through the handle API only. Core self-binds the private
store adapter at construct.

```python
from django.apps import AppConfig
from trusts.apps import implementation_for_path
from trusts.zero.apps import CANONICAL_BACKEND_PATH

# New (builder; donate through the handle in ready())
def trust_own(u, p, o):
    return u == o.settlor

class Trust(Content):
    class Meta:
        permission_conditions = (('own', trust_own),)

class DocumentsConfig(AppConfig):
    def ready(self):
        owner = implementation_for_path(
            CANONICAL_BACKEND_PATH, apps_registry=self.apps,
        )
        handle = owner.configured_backend(CANONICAL_BACKEND_PATH)
        handle.register_permission_condition(
            Document, 'non_confidential',
            lambda u, p, o: o.confidential != True,
        )

# Isolated / unfrozen tests (never the post-ready live registry)
from trusts.core import TrustsRegistry
isolated = TrustsRegistry()
isolated.register_permission_condition(Ticket, 'own', lambda u, p, o: u == o.owner)
```

Unchanged public call sites: `User.has_perm`,
`ContentQuerySet.permitted(perm, user)`,
`Trust.objects.filter_by_user_content_perm` (still refuses `:condition`),
`Meta.permission_conditions` / `content_permission_conditions` names,
`Trust:own` authorization meaning (`u == o.settlor`).

| Situation | Do this |
| --- | --- |
| `Trust:own` / Meta tuples | Builder callable donated in `ready()` — not `condition_refs()` / prebuilt `Expr` |
| Explicit registration | `handle.register_permission_condition` in the pre-finalization window |
| Live registry after `apps.ready` | Frozen; further `register_permission_condition` raises `TrustsConfigurationError` **before** the builder runs |
| `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS = True` | `trusts.E007`; does not enable callbacks |
| `legacy_permission_callbacks_allowed` / `trusts.E002` / `trusts.W001` | Deleted. Do not import them |
| Isolated tests | New `TrustsRegistry()` (unfrozen) |

Deleted Zero model static methods — no forwarding alias on `Content` or
`Junction`:

| Removed | Replacement |
| --- | --- |
| `Content.register_permission_condition` | `handle.register_permission_condition` |
| `Content.register_content` | `donate_content_permission_conditions` / `donate_installed_permission_conditions` |
| `Content.get_permission_condition_record` | `handle.registry.get_permission_condition_record` |
| `Content.get_permission_condition_func` | Deleted. Records are IR-only (`record.expr`) |
| `Content.iter_permission_conditions` | `handle.registry.iter_permission_conditions` or `trusts.checks.iter_live_permission_conditions` |
| `Content._conditions` | Per-handle `TrustsRegistry.conditions` |
| `Junction.register_junction` | `donate_junction_content_permission_conditions` |
| `from trusts.conditions import condition_refs` in production / Meta | Builder `lambda u, p, o: ...` or a named `def` |
| `handle.registry.register_permission_condition` as the application API | `handle.register_permission_condition` |

`PermissionConditionNotQueryable` is imported from `trusts.conditions`
only. There is no `trusts.zero.models` alias.

Hosts that previously donated only TUP and relied on
`HistoricalGroupQueryCompiler` must call
`register_zero_content(registry, Model)` (TUP + both TGP alternatives)
for each terminal. `register_zero_relations` still donates Trust-as-content
only. `HistoricalGroupQueryCompiler` is removed; use core
`PlanQueryCompiler`.

## Moved views / templates / admin / management commands

| Surface | Old (0.x / leftover core path) | New (Zero-owned) |
| --- | --- | --- |
| Views | `from trusts.views import NewTeamView, TeamView, newteam, team` | `from trusts.zero.views import NewTeamView, TeamView, newteam, team` |
| URLs | `include('trusts.urls')` | `include('trusts.zero.urls')` |
| Admin | `from trusts.admin import register_auto_modeladmins` | `from trusts.zero.admin import register_auto_modeladmins` |
| Authorization helpers | `from trusts.authorization import AuthorizationDenied, has_trust_row_perm` | `from trusts.zero.authorization import AuthorizationDenied, has_trust_row_perm` |
| Templates | `auth/group_detail.html`, `auth/group_form.html` | `trusts_zero/team_detail.html`, `trusts_zero/team_form.html` |
| `create_trust_root` | historical `trusts` command | `trusts.zero.management.commands.create_trust_root` |
| `grandfather_trust_group_permissions` | historical `trusts` command | `trusts.zero.management.commands.grandfather_trust_group_permissions` |
| `update_roles_permissions` | historical `trusts` command | `trusts.zero.management.commands.update_roles_permissions` |

URL namespace `app_name = 'trusts'` is unchanged (`trusts:team_create`,
`trusts:team_detail`); only the include path changes. Django still
discovers the three management commands through app label `trusts`.

`create_trust_root` creates the self-referential root when missing.
`grandfather_trust_group_permissions` is `--dry-run` by default; pass
`--apply` to copy each TrustGroup's current global ceiling into local
`TrustGroupPermission` rows. `update_roles_permissions` refreshes
`Role` / `RolePermission` rows from `Meta.roles` /
`Meta.content_roles`.

## Query / registration / policy imports

Supported model imports (`Trust`, `Content`, `Junction`, `Role`,
`TrustUserPermission`, `TrustGroup`, `TrustGroupPermission`,
`ReadonlyFieldsMixin`) stay on `trusts.zero.models`. Helpers that used
to live on that module moved:

```python
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
```

Zero-only `Meta` option names (`roles`, `content_roles`,
`content_permission_conditions`, `auto_modeladmin`) are registered when
`trusts.zero.apps` is imported, not in `ZeroConfig.ready()` and not by
importing `trusts.zero.models`. Generic `permission_conditions` is
registered by core `trusts.conditions`.

`has_trust_row_perm` uses `Trust.objects.filter_by_user_content_perm`
/ public core `filter_authorized_scopes`. There is no Zero wrapper and
no `trust_grant_q` fallback.

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

| Removed | Replacement |
| --- | --- |
| `Content.grant` / `Content.revoke` | `TrustUserPermission.objects.get_or_create` / `.filter(...).delete()` |
| `Trust.associate_group` | `trust.groups.add` / `TrustGroup.objects.get_or_create` |
| `Trust.grant_group_permission` / `revoke_group_permission` / `set_group_permissions` | `TrustGroupPermission` ORM |
| `TrustGroup.grant_permission` / `revoke_permission` / `set_permissions` | `TrustGroupPermission` ORM |

Do not restore those methods.

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
from trusts.views import
from trusts.urls import
from trusts.admin import
from trusts.authorization import
include('trusts.urls')
auth/group_detail.html
auth/group_form.html
from trusts.zero.models import compile_registered_condition_q
from trusts.zero.models import donate_
from trusts.zero.models import register_zero_
from trusts.zero.models import ContentQuerySet
from trusts.zero.backends import HistoricalGroupQueryCompiler
from trusts.conditions import condition_refs
from trusts.conditions import legacy_permission_callbacks_allowed
Content.register_permission_condition
Content.register_content
trusts.conditions._ir
set_condition_lookup
TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS
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
- [ ] Convert Meta / explicit condition registrations to builders. Call `handle.register_permission_condition` from `AppConfig.ready()`, not on the post-ready frozen live registry.
- [ ] Search production for `trusts.conditions._ir` and `set_condition_lookup`. Do not import or bind them. Tests that inject a fake or unbind may keep the call.
- [ ] Remove `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS`, `legacy_permission_callbacks_allowed`, `condition_refs`, `trusts.E002`, and `trusts.W001`. A leftover `True` setting is `trusts.E007`.
- [ ] Retarget `include('trusts.urls')` to `include('trusts.zero.urls')`. Move template overrides to `trusts_zero/team_{detail,form}.html`.
- [ ] Retarget views, admin, authorization helpers, and management-command imports to `trusts.zero.*`.
- [ ] Retarget query / registration / policy helpers that used to import from `trusts.zero.models`.
- [ ] Confirm `register_zero_content` for each host terminal that needs TUP + TGP. Do not rely on `HistoricalGroupQueryCompiler`.
- [ ] Confirm startup: canonical settings succeed; old backend path raises `ImproperlyConfigured`.
- [ ] Confirm no installed core `AppConfig` and exactly one implementation owner.
- [ ] `python -m django migrate --plan` — no Trusts operations on an already-current database.
- [ ] `python -m django makemigrations trusts --check` — quiet.
- [ ] Confirm `ContentType` natural keys `trusts | trust` (and siblings) and `COUNT(*)` on every Trusts table are unchanged.
- [ ] Confirm model labels, migration keys, permissions, and representative rows are unchanged.
- [ ] Run `create_trust_root` if the root row is missing. Dry-run, then optionally `--apply`, `grandfather_trust_group_permissions` if you want former implicit group-derived Trust access copied into local TGP rows. Run `update_roles_permissions` if `Meta.roles` / `Meta.content_roles` changed.
- [ ] Confirm object/list authorization, fail-closed anonymous/inactive/undeclared cases, and fixed query counts.
- [ ] Confirm `pip` refuses core below `1.0.0.dev3` against this wheel (`django-trusts>=1.0.0.dev3,<2`).
- [ ] Confirm `pip uninstall django-trusts-zero` does not delete `trusts/__init__.py`.
- [ ] Confirm uninstalling core makes `trusts.zero.backends` unusable.
- [ ] Replace `Content.grant`/`revoke`, `Trust.associate_group`/`grant_group_permission`/`revoke_group_permission`/`set_group_permissions`, and `TrustGroup.grant_permission`/`revoke_permission`/`set_permissions` with the ORM snippets above. Do not restore those methods.
- [ ] Keep ceiling writes on `TrustGroupPermission` (`.full_clean()` / `save` / `bulk_create`); do not bypass `local_grant_outside_ceiling`.
- [ ] `filter_by_user_content_perm(user, ContentModel, 'add')` must keep authorizing the **content** permission (e.g. `add_category`), not `add_trust`.
- [ ] Confirm first-party donation remains zero-SQL and idempotent on re-entry to `ready()`.
- [ ] Confirm a frozen handle raises `TrustsConfigurationError` before the builder is invoked.
- [ ] Do not apply a new Trusts schema or data migration; none was added.
- [ ] Leave Zero package version at `1.0.0.dev0` and core floor at `1.0.0.dev3`.

## Archaeology

This file is the live executable route only. It does not inline Core
#8–#151 chronology or unpublished internal development snapshots.

The full historical Core `migrates.md` is archived at both of these
URLs (tag for convenience; SHA for immutability):

- https://github.com/django-trusts/django-trusts/blob/migration-archive-pre-1.0/migrates.md
- https://github.com/django-trusts/django-trusts/blob/7414886263faafb6edfb44c0c5fcf9fc8fa14e79/migrates.md

Zero git history at
[`841004af49687c31c466ed03dbfd4f8ce9c7f153`](https://github.com/django-trusts/django-trusts-zero/commit/841004af49687c31c466ed03dbfd4f8ce9c7f153)
still holds the pre-curation Zero file (the previous default-branch
guide, including chronological Zero records). Read that commit for
Zero's own pre-reset text. Do not copy the Core archive into this
package or wheel.
