# migrates.md — django-trusts-zero Z1 (C1 APIs)

This file is the mechanical checklist for reconstituting the historical
concrete Trusts implementation under `trusts.zero` on merged C1 public
APIs. It does **not** close django-trusts#54. It does **not** authorize
merging Z1 alone against C1.

Implemented revision: **Z1 reconstitution** for
[django-trusts-zero#7](https://github.com/django-trusts/django-trusts-zero/issues/7).
Authorized by [django-trusts#54 C1/r9](https://github.com/django-trusts/django-trusts/issues/54#issuecomment-5631620100)
and the #93 baton
[comment 5632052795](https://github.com/django-trusts/django-trusts/pull/93#issuecomment-5632052795).

Unrelated to Zero Trust network architecture.

## Companion kernel

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
| Create-under-Trust | `trust_grant_q` inside `TrustManager` | `filter_scope_rows` → `filter_authorized_scopes` when TGP records exist; C1 `trust_grant_q` remains the group-parity fallback until TGP grammar exists |
| `:condition` overlay | `Content` registry imported by core | `ContentConditionLookup` bound from `ZeroConfig.ready()` |
| Django app label | `trusts` | **`trusts`** (unchanged, owned by ZeroConfig) |
| Migration names | `0001_initial`, `0002_trustgroup` | **unchanged** loader keys `trusts.0001_initial` / `trusts.0002_trustgroup` |
| Tables / content types | `trusts_trust`, `trusts \| trust`, … | **unchanged** |

Forbidden:

- merging Z1 onto Zero `dev` while core `dev` is still C1
- bare `'trusts.zero'` as a substitute for `trusts.zero.apps.ZeroConfig`
- Zero shipping `trusts/__init__.py`
- copying `granted` / `HistoricalGroupQueryCompiler` / `compose` into Zero

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
| `filter_by_user_content_perm` | `trust_grant_q` | codec + `filter_authorized_scopes` (TGP) or C1 `trust_grant_q` fallback |
| Fail-closed undeclared | empty | **unchanged** (`any_plan_records`) |

## Migration-bot checklist

Search application code and settings for:

```text
INSTALLED_APPS.*trusts
AUTHENTICATION_BACKENDS.*trusts.backends
from trusts.models import
from trusts import ENTITY_MODEL_NAME
from trusts import ROOT_PK
```

Then:

- [ ] Do **not** add `'trusts.zero.apps.ZeroConfig'` next to C1 `'trusts'`. Wait for C2.
- [ ] After CUT, `INSTALLED_APPS` is `'trusts'` + `'trusts.zero.apps.ZeroConfig'`.
- [ ] Keep `'trusts.backends.TrustModelBackend'` (core path). Do not switch to a Zero backend module.
- [ ] Canonical model import is `trusts.zero.models`. C2 1.x shim still serves `trusts.models` when Zero is installed.
- [ ] Settings constants for migrations/commands: `trusts.zero`.
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
