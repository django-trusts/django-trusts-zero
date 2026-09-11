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
| Paired final core | [django-trusts#112](https://github.com/django-trusts/django-trusts/pull/112) merge [`11058641b533e0f8489598e0b1f5cbe5d42a81db`](https://github.com/django-trusts/django-trusts/commit/11058641b533e0f8489598e0b1f5cbe5d42a81db) (`django-trusts==1.0.0.dev3`) |
| Zero code baseline | [`94e0fa109a8a7a5f53a028438ada899cbc1be1ad`](https://github.com/django-trusts/django-trusts-zero/commit/94e0fa109a8a7a5f53a028438ada899cbc1be1ad) |

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
