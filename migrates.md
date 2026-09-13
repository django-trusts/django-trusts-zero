# migrates.md — django-trusts-zero 1.0.0.dev0

This is the executable route from django-trusts 0.x onto
`django-trusts-zero`. Stored schema and authorization **data** stay
compatible. Public **imports and settings** change.

Unrelated to Zero Trust network architecture.

Do **not** install a core Django app, call `kernel_config()`, list
`trusts.backends.TrustModelBackend`, or plan a later `dev4` cleanup.
Those surfaces are gone on the supported core library.

Schema-neutral Core-only adopters (no Trust/Content tables) should use
the current Core README and RST. A concise Core 1.x migration router is
forthcoming on django-trusts `dev`; do not follow this file for that
audience.

## Audience

Install `django-trusts-zero` when you already have, or want, the
historical Trust/Content models and their persisted identities. Core
arrives as the `django-trusts>=1.0.0.dev3,<2` library dependency. It is
not a Django app.

## Upgrade order (fail-closed)

Do these steps in order. Do not migrate before settings/import
rewrites; do not run grandfather before the backend path is the Zero
identity.

1. `pip install django-trusts-zero` (pulls Core `>=1.0.0.dev3,<2`).
2. Rewrite `INSTALLED_APPS` / `AUTHENTICATION_BACKENDS` / imports
   (tables below). Remove `'trusts'` and
   `'trusts.backends.TrustModelBackend'`.
3. `python -m django check` — canonical settings start; old backend
   path is `ImproperlyConfigured`.
4. `python -m django migrate --plan` — already-current 0.x databases
   have no Trusts operations. `makemigrations trusts --check` is quiet.
5. If the root row is missing, `manage.py create_trust_root` (idempotent
   when `pk` exists). Requires `trusts.zero.apps.ZeroConfig`.
6. If group-permission rows still need grandfathering,
   `manage.py grandfather_trust_group_permissions --dry-run` then the
   live command. `manage.py update_roles_permissions` remains the role
   sync.
7. Verify allow/deny, `.permitted()`, create-under-Trust
   (`add_category` not `add_trust`), and fail-closed
   anonymous/inactive/undeclared cases.

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
| URLs | `include('trusts.urls')` | `include('trusts.zero.urls')` (`app_name = 'trusts'` unchanged) |
| Templates | `auth/group_detail.html`, `auth/group_form.html` | `trusts_zero/team_detail.html`, `trusts_zero/team_form.html` |
| Admin | `from trusts.admin import register_auto_modeladmins` | `from trusts.zero.admin import register_auto_modeladmins` |
| Views | `from trusts.views import NewTeamView, TeamView, …` | `from trusts.zero.views import NewTeamView, TeamView, …` |
| Commands | Core `trusts.management.commands.*` | Zero `manage.py create_trust_root` / `grandfather_trust_group_permissions` / `update_roles_permissions` |

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

Confirm `ContentType` natural keys `trusts | trust` (and siblings) and
`COUNT(*)` on every Trusts table are unchanged.

## Imports that must move

Supported model imports (`Trust`, `Content`, `Junction`, `Role`,
`TrustUserPermission`, `TrustGroup`, `TrustGroupPermission`,
`ReadonlyFieldsMixin`) stay on `trusts.zero.models`.

```python
# Old leftovers (delete)
from trusts.zero.models import (
    compile_registered_condition_q, django_permission_filter,
    donate_content_permission_conditions, register_zero_relations,
    ContentQuerySet, PermissionConditionNotQueryable,
)
from trusts.zero.backends import HistoricalGroupQueryCompiler
from trusts.authorization import AuthorizationDenied, has_trust_row_perm
from trusts.views import NewTeamView, TeamView
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
```

`HistoricalGroupQueryCompiler` is removed; use `PlanQueryCompiler`.
Hosts that previously donated only TUP and relied on that compiler must
call `register_zero_content(registry, Model)` (TUP + both TGP
alternatives) for each terminal. `register_zero_relations` still donates
Trust-as-content only.

Zero-only `Meta` option names (`roles`, `content_roles`,
`content_permission_conditions`, `auto_modeladmin`) are registered when
`trusts.zero.apps` is imported. Generic `permission_conditions` is
registered by Core.

`has_trust_row_perm` uses `Trust.objects.filter_by_user_content_perm`
/ public Core `filter_authorized_scopes`. There is no `trust_grant_q`
fallback.

## Conditions (current)

A callable supplied to condition registration is a **builder**. Core
invokes it once with symbolic `(u, p, o)`, stores normalized IR, and
never runs it during `has_perm` or `.permitted()`.
`filter_by_user_content_perm` still refuses a `:condition` suffix.

Zero production `Trust:own` (`u == o.settlor`) and host
`Meta.permission_conditions` are builders donated through
`handle.register_permission_condition` in `ZeroConfig.ready()` (or the
host `AppConfig.ready()`) before finalization. After `apps.ready`, the
live handle is frozen; further `register_permission_condition` raises
`TrustsConfigurationError` **before** the builder runs. Ad-hoc test
conditions register on an isolated unfrozen `TrustsRegistry()`.

Production Zero does **not** import `trusts.conditions._ir` or call
`set_condition_lookup`. Core self-binds the private store adapter at
construct. Applications register a builder; they do not bind lookup.

```python
def trust_own(u, p, o):
    return u == o.settlor

class Trust(Content):
    class Meta:
        permission_conditions = (('own', trust_own),)

class DocumentsConfig(AppConfig):
    def ready(self):
        handle = owner.configured_backend(CANONICAL_BACKEND_PATH)
        handle.register_permission_condition(
            Document, 'non_confidential',
            lambda u, p, o: o.confidential != True,
        )
```

Deleted / retired consumer names:

| Removed | Replacement |
| --- | --- |
| `from trusts.conditions import condition_refs` / `Expr` | Builder `lambda u, p, o: …` or a named `def` |
| `handle.registry.register_permission_condition` as the application API | `handle.register_permission_condition` |
| `Content.register_permission_condition` / `Content._conditions` | Handle + Meta donation |
| `legacy_permission_callbacks_allowed` / `trusts.E002` / `trusts.W001` | Deleted. Leftover `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS = True` is `trusts.E007` and does not enable callbacks |
| `ConditionRecord.func` | Gone. Records are IR-only (`record.expr`) |
| Production `RegistryConditionLookup` / `set_condition_lookup` | Core construct-time self-bind |

Unchanged public calls: `User.has_perm`,
`ContentQuerySet.permitted(perm, user)`,
`Trust.objects.filter_by_user_content_perm` (still refuses `:condition`),
`Meta.permission_conditions` / `content_permission_conditions` names,
`Trust:own` meaning.

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

Authorization-aware helpers (`grant_trustee`, `revoke_trustee`,
`associate_group_with_trust`, `grant_trust_group_permission`) remain
in `trusts.zero.authorization` and require administrative `change`
authority. They do not restore the deleted model methods.

Create-under-Trust: `Trust.objects.filter_by_user_content_perm(user, Category, 'add')`
must resolve `add_category`, not `add_trust`. A trustee grant of
`add_trust` alone is insufficient.

`TRUSTS_GROUP_MODEL` and `TRUSTS_PERMISSION_MODEL` no longer swap field
targets.

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
from trusts.conditions import condition_refs
from trusts.conditions import Expr
from trusts.conditions._ir
set_condition_lookup
Content.register_permission_condition
.content.grant(
.content.revoke(
.associate_group(
.grant_group_permission(
.revoke_group_permission(
.set_group_permissions(
.grant_permission(
.set_permissions(
from trusts.zero.models import compile_registered_condition_q
from trusts.zero.models import ContentQuerySet
from trusts.zero.backends import HistoricalGroupQueryCompiler
from trusts.authorization import
from trusts.views import
from trusts.urls import
from trusts.admin import
include('trusts.urls')
auth/group_detail.html
auth/group_form.html
trust_grant_q
legacy_permission_callbacks_allowed
TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS
```

Then:

- [ ] Install `django-trusts-zero` (it pulls `django-trusts` 1.x). Do not add `'trusts'` to `INSTALLED_APPS`.
- [ ] Set `INSTALLED_APPS` to `'trusts.zero.apps.ZeroConfig'` (plus Django contrib).
- [ ] Set `AUTHENTICATION_BACKENDS` to `'trusts.zero.backends.TrustModelBackend'`. Remove `'trusts.backends.TrustModelBackend'`.
- [ ] Replace `from trusts.backends import TrustModelBackend` with `from trusts.zero.backends import TrustModelBackend`.
- [ ] Replace `from trusts.models import …` with `from trusts.zero.models import …`.
- [ ] Move settings constants used by migrations/commands to `trusts.zero`.
- [ ] Delete any `kernel_config()` or core `AppConfig` usage.
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
- [ ] Replace `Content.grant`/`revoke`, `Trust.associate_group`/`grant_group_permission`/`revoke_group_permission`/`set_group_permissions`, and `TrustGroup.grant_permission`/`revoke_permission`/`set_permissions` with the ORM snippets above. Do not restore those methods.
- [ ] Keep ceiling writes on `TrustGroupPermission` (`.full_clean()` / `save` / `bulk_create`); do not bypass `local_grant_outside_ceiling`.
- [ ] `filter_by_user_content_perm(user, ContentModel, 'add')` must keep authorizing the **content** permission (e.g. `add_category`), not `add_trust`.
- [ ] Convert Meta / explicit registrations to builders. Call `handle.register_permission_condition` from `AppConfig.ready()`, not the post-ready frozen live registry.
- [ ] Search production for `trusts.conditions._ir`, `RegistryConditionLookup`, and `set_condition_lookup`. Those production imports and bind calls go away.
- [ ] Search for `condition_refs`, `legacy_permission_callbacks_allowed`, `trusts.E002`, `trusts.W001`. Delete those expectations. A leftover setting is `trusts.E007`.
- [ ] Search for `record.func`. The field is gone; records are IR-only.
- [ ] Move ad-hoc test condition registration onto `TrustsRegistry()` (unfrozen).
- [ ] Confirm `Trust:own` still authorizes settlor rows on both `has_perm` and `.permitted()`.
- [ ] Confirm first-party donation is zero-SQL and idempotent on re-entry to `ready()`.
- [ ] Confirm a frozen handle raises `TrustsConfigurationError` before the builder is invoked.
- [ ] Retarget `Content.register_*` / `Junction.register_junction` leftovers to handle / donation helpers.
- [ ] `include('trusts.urls')` → `include('trusts.zero.urls')`; template overrides → `trusts_zero/team_*.html`.
- [ ] Do not apply a new Trusts schema or data migration; none was added.
- [ ] Leave Zero package version at `1.0.0.dev0` and core floor at `1.0.0.dev3`.

## Archaeology

Chronology of unpublished development stairs (#8 through #151, Zero
Z-convert / #18 / #16, and `2.0.0.dev*` snapshots) is **not** this
route. It lives in the Core archive and in this repository's git
history.

- Tag file: https://github.com/django-trusts/django-trusts/blob/migration-archive-pre-1.0/migrates.md
- Immutable SHA file: https://github.com/django-trusts/django-trusts/blob/7414886263faafb6edfb44c0c5fcf9fc8fa14e79/migrates.md

The immutable pre-curation Zero file (this guide before #152) is
`841004af49687c31c466ed03dbfd4f8ce9c7f153`:
https://github.com/django-trusts/django-trusts-zero/blob/841004af49687c31c466ed03dbfd4f8ce9c7f153/migrates.md

Do not copy Core's historical `migrates.md` into this package.
