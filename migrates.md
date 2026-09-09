# migrates.md — django-trusts-zero 2.0 package-path split

This file is the mechanical checklist for relocating the historical
concrete Trusts implementation from `django-trusts` / `trusts` into
`django-trusts-zero` / `trusts.zero`.

Implemented revision: **noun-independent-kernel-r3 Step 3 (Zero package)**.
Does **not** close [django-trusts#43](https://github.com/django-trusts/django-trusts/issues/43).

Unrelated to Zero Trust network architecture.

## Companion kernel

| Item | Value |
| --- | --- |
| Kernel pin used to relocate and test | [`624daa198d1922a43c775a814a3ff213cf5bd4d7`](https://github.com/django-trusts/django-trusts/commit/624daa198d1922a43c775a814a3ff213cf5bd4d7) (master after [#45](https://github.com/django-trusts/django-trusts/pull/45)) |
| Kernel Step 3 PR | *not published yet (no open PR / Step 3 branch on django-trusts as of this Zero PR). Do not assume it has landed. Update this row with the companion PR URL and HEAD when known. grokforthomas acknowledged the Step 3 baton in [comment 5599441244](https://github.com/django-trusts/django-trusts/issues/43#issuecomment-5599441244).* |
| What 624daa1 still contains | Concrete models, migrations, backend, `trusts.apps.AppConfig` with `label='trusts'`, Zero settings constants on `trusts/__init__.py` |
| What Zero requires from a split kernel | `pkgutil.extend_path` on `trusts/__init__.py` (editable+editable); `KernelConfig(name='trusts', label='trusts_kernel', default=False)` with **no** migrations |

Until the kernel PR lands, install **only** `trusts.zero.apps.ZeroConfig` (do not also install `'trusts'`). Kernel modules (`trusts.context`, `trusts.trustee`, `trusts.path`, `trusts.conditions`) remain importable from the `django-trusts` distribution.

## Public changes (2.0 package path)

Stored schema and authorization **data** stay compatible. Public **imports and settings** change.

| Surface | Old (django-trusts 1.x / 0.x concrete) | New |
| --- | --- | --- |
| Distribution | `django-trusts` (kernel + concrete) | `django-trusts` (kernel) + `django-trusts-zero` |
| `INSTALLED_APPS` | `'trusts'` | `'trusts.apps.KernelConfig'` (after kernel PR) then `'trusts.zero.apps.ZeroConfig'` |
| Models | `from trusts.models import Trust, Content, Junction, Role` | `from trusts.zero.models import Trust, Content, Junction, Role` |
| Backend | `'trusts.backends.TrustModelBackend'` | `'trusts.zero.backends.TrustModelBackend'` |
| Settings constants | `from trusts import ENTITY_MODEL_NAME, ROOT_PK, …` | `from trusts.zero import ENTITY_MODEL_NAME, ROOT_PK, …` |
| Management commands | still named `create_trust_root`, `grandfather_trust_group_permissions`, `update_roles_permissions` | same names, discovered via Zero’s app |
| Django app label | `trusts` | **`trusts`** (unchanged) |
| Migration names | `0001_initial`, `0002_trustgroup` | **unchanged** |
| Tables | `trusts_trust`, `trusts_trustuserpermission`, `trusts_trust_groups`, `trusts_trustgrouppermission`, `trusts_role`, `trusts_rolepermission` | **unchanged** |
| ContentType natural keys | `trusts \| trust` (and siblings) | **unchanged** |

Forbidden after the split:

- bare `'trusts'` in `INSTALLED_APPS` (selects kernel `trusts/apps.py`)
- bare `'trusts.zero'` as a substitute for the explicit class path in the 2.0 checklist
- Zero shipping `trusts/__init__.py`

## Migration identity (r3)

Move `0001_initial.py` and `0002_trustgroup.py` to `trusts.zero.migrations` with **import-only** rewrites:

```python
from trusts.zero import (
    ENTITY_MODEL_NAME, GROUP_MODEL_NAME, PERMISSION_MODEL_NAME,
    DEFAULT_SETTLOR, ALLOW_NULL_SETTLOR, ROOT_PK,
)
from trusts.zero.management.commands.create_trust_root import create_root_trust
from trusts.zero.models import ReadonlyFieldsMixin
# bases=(ReadonlyFieldsMixin, models.Model)
```

Loader keys remain `('trusts', '0001_initial')` / `('trusts', '0002_trustgroup')` because `ZeroConfig.label = 'trusts'`. No `MIGRATION_MODULES`. No `0003`.

Accepted deconstruction deltas (and only these):

1. `CreateModel.bases` serializes `trusts.zero.models.ReadonlyFieldsMixin`
2. `RunPython` callable module is `trusts.zero.management.commands.create_trust_root`

Any other deconstruction delta is a failure. Schema-bearing ops (`to=`, `through=`, `db_table`, `database_operations=[]`, …) stay equivalent. Do not inline `'auth.Group'` in place of `GROUP_MODEL_NAME`.

## Proofs this package runs

1. **Fresh install** — `scripts/verify-fresh-install.py`: applied `{0001_initial, 0002_trustgroup}`; tables listed above; root row at `TRUSTS_ROOT_PK`; `makemigrations --check` quiet; already-current `migrate --plan` for `trusts` is empty.
2. **Already-applied 1.x** — `scripts/verify-upgrade-current.py`: kernel migrate, swap to ZeroConfig, empty trusts plan, unchanged `COUNT(*)` and content-type natural keys.
3. **Legacy 0001-only** — `scripts/verify-legacy-upgrade.py`: plan is exactly `[('trusts', '0002_trustgroup', False)]`; `0001` is not re-run; `0002` `database_operations=[]` so `trusts_trust_groups` rows are reused.
4. **Install matrix** — `scripts/verify-install-matrix.py`: wheel+wheel, editable+editable (kernel `extend_path` overlay if needed), uninstall/reinstall isolation; Zero RECORD never owns a core path.

Pre-split baseline and legacy DDL live in `scripts/legacy/trusts_0001_sqlite.sql` (copied from django-trusts so comparison remains possible if the kernel PR later drops in-tree concrete files).

## Migration-bot checklist

Search application code and settings for:

```text
INSTALLED_APPS.*trusts
AUTHENTICATION_BACKENDS.*trusts.backends
from trusts.models import
from trusts.backends import
from trusts.admin import
from trusts.authorization import
from trusts.query import
from trusts.decorators import
from trusts import ENTITY_MODEL_NAME
from trusts import ROOT_PK
from trusts import GROUP_MODEL_NAME
from trusts import PERMISSION_MODEL_NAME
from trusts import DEFAULT_SETTLOR
from trusts import ALLOW_NULL_SETTLOR
from trusts import get_entity_model
from trusts import supported_entity_contract
trusts.urls
```

Keep:

```text
from trusts.context import
from trusts.trustee import
from trusts.path import
from trusts.conditions import
```

Replace concrete imports with `trusts.zero.*`. Replace `'trusts'` in `INSTALLED_APPS` with `'trusts.zero.apps.ZeroConfig'` (and `'trusts.apps.KernelConfig'` once the kernel PR is installed). Replace the backend string with `'trusts.zero.backends.TrustModelBackend'`.

Then:

1. `python -m django migrate --plan` — no Trusts operations on an already-current database.
2. `python -m django makemigrations trusts --check` — quiet.
3. Confirm `ContentType` natural keys `trusts | trust` (and siblings) and `COUNT(*)` on every Trusts table are unchanged.
4. Confirm `pip uninstall django-trusts-zero` does not delete `trusts/__init__.py`.

## Out of scope (this slice)

- Recursive / ordered Windows helpers
- Broadening the GH vocabulary proof
- Closing django-trusts#43
- Removing in-tree concrete code from django-trusts **master** (that wait is the coordinated kernel PR; do not merge one side without the other)
