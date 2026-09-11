# migrates.md — django-trusts-zero IIa (2.0.0.dev2)

This file is the mechanical checklist for Step IIa: Zero-owned
`AppConfig` and canonical backend. It closes
[django-trusts-zero#9](https://github.com/django-trusts/django-trusts-zero/issues/9).
Authorized by approved
[#102 r3](https://github.com/django-trusts/django-trusts/issues/102#issuecomment-5638914363),
[r4](https://github.com/django-trusts/django-trusts/issues/102#issuecomment-5638983164),
and [r5](https://github.com/django-trusts/django-trusts/issues/102#issuecomment-5639018377).
Core pair pin is [django-trusts#109](https://github.com/django-trusts/django-trusts/pull/109)
merge [`39f1f9611e214193aec4e97526cf9b54ee689967`](https://github.com/django-trusts/django-trusts/commit/39f1f9611e214193aec4e97526cf9b54ee689967)
(`django-trusts==1.0.0.dev2`).

Unrelated to Zero Trust network architecture.

Z0-cap `2.0.0.dev1` is a separate metadata-only artifact and is **not**
this revision. Raw `2.0.0.dev0` history is not rewritten here.

## Companion kernel (IIa)

| Item | Value |
| --- | --- |
| Authoritative Zero metadata | this repo `pyproject.toml` (`2.0.0.dev2` + `django-trusts>=1.0.0.dev2,<2`) |
| Paired Step I core | [django-trusts#109](https://github.com/django-trusts/django-trusts/pull/109) merge [`39f1f9611e214193aec4e97526cf9b54ee689967`](https://github.com/django-trusts/django-trusts/commit/39f1f9611e214193aec4e97526cf9b54ee689967) |
| Zero baseline (Z1) | [`ce0a1754036ffa111ba179926d7edad43a15b706`](https://github.com/django-trusts/django-trusts-zero/commit/ce0a1754036ffa111ba179926d7edad43a15b706) / raw pin [`41d07f40e676f75389b91219106440932d402b53`](https://github.com/django-trusts/django-trusts-zero/commit/41d07f40e676f75389b91219106440932d402b53) |

## Public changes (IIa)

Stored schema and authorization **data** stay compatible. Public
**imports and settings** change.

| Surface | Old (Z1 / `2.0.0.dev0`) | New (IIa / `2.0.0.dev2`) |
| --- | --- | --- |
| Distribution | `django-trusts-zero==2.0.0.dev0` + `django-trusts>=1.0.0.dev0` | `django-trusts-zero==2.0.0.dev2` + `django-trusts>=1.0.0.dev2,<2` |
| `INSTALLED_APPS` | `'trusts'` then `'trusts.zero.apps.ZeroConfig'` | **`'trusts.zero.apps.ZeroConfig'` only** (no `'trusts'`) |
| Backend settings | `'trusts.backends.TrustModelBackend'` | `'trusts.zero.backends.TrustModelBackend'` |
| Backend import | `from trusts.backends import TrustModelBackend` | `from trusts.zero.backends import TrustModelBackend` |
| Owner API | `kernel_config()` swallow in `ZeroConfig.ready()` | `ZeroConfig(TrustsImplementationConfig)` + `implementation_for_path` / `zero_config()` |
| Models | `from trusts.zero.models import Trust, Content, Junction` | **unchanged** |
| Settings constants | `from trusts.zero import ENTITY_MODEL_NAME, ROOT_PK, …` | **unchanged** |
| Django app label | `trusts` | **`trusts`** (unchanged) |
| Migration names | `0001_initial`, `0002_trustgroup` | **unchanged** loader keys `trusts.0001_initial` / `trusts.0002_trustgroup` |
| Tables / content types / permissions | `trusts_trust`, `trusts \| trust`, … | **unchanged** |

### Old / new startup and failure behavior

| Situation | Old (Z1) | New (IIa) |
| --- | --- | --- |
| Canonical IIa settings | N/A | Starts. No core `AppConfig`. Exactly one implementation owner (`ZeroConfig`). |
| `'trusts'` in `INSTALLED_APPS` | Required (kernel store) | Not required. Supported IIa omits it. |
| `AUTHENTICATION_BACKENDS = ['trusts.backends.TrustModelBackend']` | Supported (core historical class + `kernel_config()`) | **`ImproperlyConfigured`** naming `trusts.zero.backends.TrustModelBackend`. No forwarding. |
| Both backend paths listed | N/A | **`ImproperlyConfigured`** (two mixin classes; old path is not Zero identity) |
| Canonical path missing | N/A | **`ImproperlyConfigured`** from `ZeroConfig.ready()` |
| Core below `1.0.0.dev2` | Installable (`>=1.0.0.dev0`) | **Metadata refuse** (`Requires-Dist: django-trusts>=1.0.0.dev2,<2`) and **startup belt** `ImproperlyConfigured` if `TrustsImplementationConfig` is missing |
| Missing kernel `AppConfig` | `ZeroConfig.ready()` swallowed `LookupError` and skipped donation | **OK.** Donation writes Zero's registry. `kernel_config()` is never called. |
| Owner-present mixin / list / create-under-Trust | Used `kernel_config()` | Resolves through `ZeroConfig`. `kernel_config()` is not called. |

Do **not** add transparent core-path forwarding or make the old backend
path succeed under IIa.

## Migration identity (unchanged)

Loader keys remain `('trusts', '0001_initial')` / `('trusts', '0002_trustgroup')`
because `ZeroConfig.label = 'trusts'`. No `MIGRATION_MODULES`. No `0003`.
`0002` still `dependencies = [('trusts', '0001_initial')]` and
`database_operations=[]`.

Already-applied 1.x / Z1 DBs keep matching `django_migrations` rows.
`python -m django migrate --plan` has no Trusts operations on an
already-current database. `makemigrations trusts --check` is quiet.

## IIa migration-bot checklist

Search application code and settings for:

```text
INSTALLED_APPS.*trusts
AUTHENTICATION_BACKENDS.*trusts.backends
from trusts.backends import TrustModelBackend
from trusts.apps import kernel_config
from trusts.models import
from trusts import ENTITY_MODEL_NAME
from trusts import ROOT_PK
```

Then:

- [ ] Set `INSTALLED_APPS` to `'trusts.zero.apps.ZeroConfig'` (plus Django contrib). Remove `'trusts'`.
- [ ] Set `AUTHENTICATION_BACKENDS` to `'trusts.zero.backends.TrustModelBackend'`. Remove `'trusts.backends.TrustModelBackend'`.
- [ ] Replace `from trusts.backends import TrustModelBackend` with `from trusts.zero.backends import TrustModelBackend`.
- [ ] Replace `kernel_config()` donations with `implementation_for_path('trusts.zero.backends.TrustModelBackend', apps_registry=self.apps)` or `zero_config()`.
- [ ] Confirm startup: canonical settings succeed; old backend path raises `ImproperlyConfigured`.
- [ ] Confirm no installed core `AppConfig` and exactly one implementation owner.
- [ ] `python -m django migrate --plan` — no Trusts operations on an already-current database.
- [ ] `python -m django makemigrations trusts --check` — quiet.
- [ ] Confirm `ContentType` natural keys `trusts | trust` (and siblings) and `COUNT(*)` on every Trusts table are unchanged.
- [ ] Confirm model labels, migration keys, permissions, and representative rows are unchanged.
- [ ] Confirm object/list authorization, fail-closed anonymous/inactive/undeclared cases, and fixed query counts.
- [ ] Confirm `pip` rejects `django-trusts==1.0.0.dev1` against this wheel (`>=1.0.0.dev2,<2`).
- [ ] Confirm `pip uninstall django-trusts-zero` does not delete `trusts/__init__.py`.
- [ ] Confirm uninstalling core makes `trusts.zero.backends` unusable.
- [ ] Set package version to `2.0.0.dev2`. Do not fold Z0-cap `2.0.0.dev1` into this revision.
- [ ] Do not implement GH IIb, core Step III/tombstone, `dev4` removal, examples, or Windows in this PR.

## Out of scope (IIa)

- GH IIb
- Core Step III / `kernel_config()` tombstone / `1.0.0.dev4` deletion
- Z0-cap `2.0.0.dev1` metadata-only artifact
- Windows #17, examples, docs restructuring beyond this IIa record

---

# Prior: Z1 reconstitution (C1 APIs, `2.0.0.dev0`)

The remainder records the earlier Z1 reconstitution. IIa supersedes its
`INSTALLED_APPS` / backend / `kernel_config()` contract. Persisted
identity rows below remain true.

Implemented revision: **Z1 reconstitution** for
[django-trusts-zero#7](https://github.com/django-trusts/django-trusts-zero/issues/7).
Authorized by [django-trusts#54 C1/r9](https://github.com/django-trusts/django-trusts/issues/54#issuecomment-5631620100)
and the #93 baton
[comment 5632052795](https://github.com/django-trusts/django-trusts/pull/93#issuecomment-5632052795).

## Companion kernel (Z1, historical)

| Item | Value |
| --- | --- |
| Authoritative Zero metadata | this repo `pyproject.toml` (`2.0.0.dev0` + `django-trusts>=1.0.0.dev0`) |
| Paired C1 APIs | [django-trusts#95](https://github.com/django-trusts/django-trusts/pull/95) merge [`ffb02364a45f3a4bc2b9a3973de3612c37d785e9`](https://github.com/django-trusts/django-trusts/commit/ffb02364a45f3a4bc2b9a3973de3612c37d785e9) (reviewed head [`39c848dab5b8786c0f5595f0922e64176f41f64e`](https://github.com/django-trusts/django-trusts/commit/39c848dab5b8786c0f5595f0922e64176f41f64e)) |
| Zero baseline | [`c174388f015d3858d09f3bbd581f72d9e830e577`](https://github.com/django-trusts/django-trusts-zero/commit/c174388f015d3858d09f3bbd581f72d9e830e577) |
| Preserved evidence | [`c60c7eab86bb31f30fe9acb8e83041f14d1c5ac7`](https://github.com/django-trusts/django-trusts-zero/commit/c60c7eab86bb31f30fe9acb8e83041f14d1c5ac7) |

## Merge boundary (negative duplicate-label gate)

| | Old (C1 alone) | Z1-alone vs C1 | New (CUT = C2 + Z1) |
| --- | --- | --- | --- |
| `INSTALLED_APPS` | `'trusts'` | **unsupported** | `'trusts'` + `'trusts.zero.apps.ZeroConfig'` |
| Kernel `label` | `trusts` | still `trusts` | `trusts_core` |
| Zero `label` | — | `trusts` | `trusts` |
| Populate | succeeds | **`ImproperlyConfigured` (duplicate label `trusts`)** | succeeds |

Do **not** merge this PR onto Zero `dev` until C2 is ready to land in the
same window. Pair CI against a future C2 branch is required for the
final merge. Z1 may be reviewed now.

## Public changes

Stored schema and authorization **data** stay compatible. Public
**imports and settings** change at CUT.

| Surface | Old (django-trusts 1.x / C1 concrete) | New (Z1, after CUT) |
| --- | --- | --- |
| Distribution | `django-trusts` (kernel + concrete) | `django-trusts` (kernel) + `django-trusts-zero` |
| `INSTALLED_APPS` | `'trusts'` | `'trusts'` then `'trusts.zero.apps.ZeroConfig'` |
| Models | `from trusts.models import Trust, Content, Junction` | canonical `from trusts.zero.models import …` (C2 1.x shim still re-exports when Zero is installed) |
| Backend | `'trusts.backends.TrustModelBackend'` | **unchanged** (core) |
| Settings constants | `from trusts import ENTITY_MODEL_NAME, ROOT_PK, …` | `from trusts.zero import ENTITY_MODEL_NAME, ROOT_PK, …` |
| List codec | `ContentQuerySet.permitted` sequenced handles in Zero/core models | one-line `django_permission_filter` → `.authorized` |
| Create-under-Trust | `trust_grant_q` inside `TrustManager` using the **content** permission | `filter_scope_rows` → `resolve_content_permission(content, perm_name)` then `filter_authorized_scopes` when TGP records exist; C1 `trust_grant_q` remains the group-parity fallback until TGP grammar exists |
| Write conveniences | `Content.grant`/`revoke`, `Trust.associate_group`/`grant_group_permission`/`revoke_group_permission`/`set_group_permissions`, `TrustGroup.grant_permission`/`revoke_permission`/`set_permissions` | **removed** (r7). Direct ORM on `TrustUserPermission` / `Trust.groups` / `TrustGroupPermission`. Ceiling still enforced by `TrustGroupPermission.clean`/`save`/`bulk_create` |
| `:condition` overlay | `Content` registry imported by core | `ContentConditionLookup` bound from `ZeroConfig.ready()` |
| Django app label | `trusts` | **`trusts`** (unchanged, owned by ZeroConfig) |
| Migration names | `0001_initial`, `0002_trustgroup` | **unchanged** loader keys `trusts.0001_initial` / `trusts.0002_trustgroup` |
| Tables / content types | `trusts_trust`, `trusts \| trust`, … | **unchanged** |

Forbidden:

- merging Z1 onto Zero `dev` while core `dev` is still C1
- bare `'trusts.zero'` as a substitute for `trusts.zero.apps.ZeroConfig`
- Zero shipping `trusts/__init__.py`
- copying `granted` / `HistoricalGroupQueryCompiler` / `compose` into Zero
- restoring r7-deleted grant/revoke/associate façades on `Content` / `Trust` / `TrustGroup`

## Migration identity

Move `0001_initial.py` and `0002_trustgroup.py` to `trusts.zero.migrations`
with **import-only** rewrites (same accepted deconstruction deltas as
preserved `c60c7eab`):

```python
from trusts.zero import (
    ENTITY_MODEL_NAME, GROUP_MODEL_NAME, PERMISSION_MODEL_NAME,
    DEFAULT_SETTLOR, ALLOW_NULL_SETTLOR, ROOT_PK,
)
from trusts.zero.management.commands.create_trust_root import create_root_trust
from trusts.zero.models import ReadonlyFieldsMixin
```

Loader keys remain `('trusts', '0001_initial')` / `('trusts', '0002_trustgroup')`
because `ZeroConfig.label = 'trusts'`. No `MIGRATION_MODULES`. No `0003`.
`0002` still `dependencies = [('trusts', '0001_initial')]` and
`database_operations=[]`.

Already-applied 1.x DBs keep matching `django_migrations` rows.
`makemigrations trusts --check` is quiet on the supported paired
configuration (C2+Z1, or Z1 tests using the documented C2-shape harness
against C1 APIs).

## Old / new authorization behavior

| | Old (C1 `ContentQuerySet.permitted`) | New (Z1) |
| --- | --- | --- |
| Signature | `permitted(perm, user)` | **unchanged** |
| Inactive / anonymous | empty queryset | **unchanged** |
| Superuser short-circuit | not duplicated | **unchanged** |
| `:condition` Expr | AND overlay in SQL | **unchanged** (compiled in Zero, passed as `extra_q`) |
| Callable `:condition` | `PermissionConditionNotQueryable` | **unchanged** |
| Plan sequencing | Zero/core `aggregate_granted` / handle loop | **core** `.authorized` only |
| `get_permission` | manager method | **retained** |
| `filter_by_user_content_perm` | `trust_grant_q` with permission resolved on the **content** model | codec + `resolve_content_permission(content, perm_name)` then `filter_authorized_scopes` (TGP) or C1 `trust_grant_q` fallback |
| Fail-closed undeclared | empty | **unchanged** (`any_plan_records`) |
| Write conveniences | `Content.grant` / `revoke`, `Trust.associate_group` / `grant_group_permission*`, `TrustGroup.grant_permission*` | **deleted**; direct ORM |

## Write conveniences (r7 deletion map)

Approved 2.0 removals from reconstituted `trusts.zero.models`. Actor gating stays application code after a read/guard. `TrustGroupPermission.clean` / `save` / `bulk_create` still reject local grants outside the group's global ceiling.

| Old | New (direct ORM) |
| --- | --- |
| `content.grant(perm, user)` | `TrustUserPermission.objects.get_or_create(trust=content.trust, entity=user, permission=Content.objects.get_permission(perm) if needed else perm)` |
| `content.revoke(perm, user)` | `TrustUserPermission.objects.filter(trust=content.trust, entity=user, permission=…).delete()`; omit `permission` for former `perm=None` |
| `trust.associate_group(group)` | `trust.groups.add(group)` or `TrustGroup.objects.get_or_create(trust=trust, group=group)` |
| `trust.grant_group_permission(group, perm)` | `TrustGroupPermission.objects.get_or_create(trustgroup=tg, permission=perm)` after association + ceiling on `group.permissions` |
| `trust.revoke_group_permission(group, perm)` | `TrustGroupPermission.objects.filter(trustgroup=tg, permission=perm).delete()` (association left in place) |
| `trust.set_group_permissions(group, perms)` | delete extra `TrustGroupPermission` rows; create missing ones |
| `trustgroup.grant_permission` / `revoke_permission` / `set_permissions` | same `TrustGroupPermission` ORM |

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

## Migration-bot checklist

Search application code and settings for:

```text
INSTALLED_APPS.*trusts
AUTHENTICATION_BACKENDS.*trusts.backends
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

- [ ] Do **not** add `'trusts.zero.apps.ZeroConfig'` next to C1 `'trusts'`. Wait for C2.
- [ ] After CUT, `INSTALLED_APPS` is `'trusts'` + `'trusts.zero.apps.ZeroConfig'`.
- [ ] **Superseded by IIa:** do not keep `'trusts.backends.TrustModelBackend'`. Use `'trusts.zero.backends.TrustModelBackend'`.
- [ ] Canonical model import is `trusts.zero.models`. C2 1.x shim still serves `trusts.models` when Zero is installed.
- [ ] Settings constants for migrations/commands: `trusts.zero`.
- [ ] Replace `Content.grant`/`revoke`, `Trust.associate_group`/`grant_group_permission`/`revoke_group_permission`/`set_group_permissions`, and `TrustGroup.grant_permission`/`revoke_permission`/`set_permissions` with the ORM snippets above. Do not restore those methods.
- [ ] Keep ceiling writes on `TrustGroupPermission` (`.full_clean()` / `save` / `bulk_create`); do not bypass `local_grant_outside_ceiling`.
- [ ] `filter_by_user_content_perm(user, ContentModel, 'add')` must keep authorizing the **content** permission (e.g. `add_category`), not `add_trust`.
- [ ] `python -m django migrate --plan` — no Trusts operations on an already-current database.
- [ ] `python -m django makemigrations trusts --check` — quiet in the paired configuration.
- [ ] Confirm `ContentType` natural keys `trusts | trust` (and siblings) and `COUNT(*)` on every Trusts table are unchanged.
- [ ] Confirm `pip uninstall django-trusts-zero` does not delete `trusts/__init__.py`.
- [ ] Confirm C1 + ZeroConfig raises `ImproperlyConfigured` (duplicate label).
- [ ] Leave package version at `2.0.0.dev0`.
- [ ] Do not begin C2, G1, Windows #17, examples, docs restructuring, or admin work in this PR.

## Out of scope (this slice)

- Core C2 extraction (`label='trusts_core'`, PEP 562 shim, deleting kernel models)
- G1 GH reconstitution
- Windows #17
- Examples, docs restructuring, admin extraction
- User-path membership hop / `permission_in` on core `register()` (TGP full records wait on that core grammar)
