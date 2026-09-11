# migrates.md — django-trusts-zero Step IIa

This file is the mechanical checklist for Step IIa: Zero-owned
`ZeroConfig` and a distinct canonical backend against merged core Step I.
It does **not** implement GH IIb, core Step III / tombstone, examples, or
Windows.

Implemented revision: **Step IIa** for
[django-trusts-zero#9](https://github.com/django-trusts/django-trusts-zero/issues/9).
Authorized by [django-trusts#102 r5](https://github.com/django-trusts/django-trusts/issues/102#issuecomment-5639018377)
and the #93 baton.

Unrelated to Zero Trust network architecture.

## Companion kernel

| Item | Value |
| --- | --- |
| Authoritative Zero metadata | this repo `pyproject.toml` (`2.0.0.dev2` + `django-trusts>=1.0.0.dev2,<2`) |
| Paired Step I core | [django-trusts#109](https://github.com/django-trusts/django-trusts/pull/109) merge [`39f1f9611e214193aec4e97526cf9b54ee689967`](https://github.com/django-trusts/django-trusts/commit/39f1f9611e214193aec4e97526cf9b54ee689967) (reviewed head [`5a7cf4fd66011048ae11621d8b524e9d558d361f`](https://github.com/django-trusts/django-trusts/commit/5a7cf4fd66011048ae11621d8b524e9d558d361f)) |
| Raw Zero (do not rewrite) | `2.0.0.dev0` @ [`41d07f40e676f75389b91219106440932d402b53`](https://github.com/django-trusts/django-trusts-zero/commit/41d07f40e676f75389b91219106440932d402b53) (`django-trusts>=1.0.0.dev0`) |
| Z0-cap (separate artifact) | `2.0.0.dev1` is **not** this PR |

## Public changes

Stored schema and authorization **data** stay compatible. Public
**imports and settings** change at IIa.

| Surface | Old (Z1 / raw `2.0.0.dev0`) | New (IIa `2.0.0.dev2`) |
| --- | --- | --- |
| Distribution | `django-trusts` + `django-trusts-zero==2.0.0.dev0` | same pair; Zero `2.0.0.dev2` requires `django-trusts>=1.0.0.dev2,<2` |
| `INSTALLED_APPS` | `'trusts'` then `'trusts.zero.apps.ZeroConfig'` | **`'trusts.zero.apps.ZeroConfig'` only** (no `'trusts'`) |
| Core AppConfig | installed (`label='trusts_core'` after C2) | **not installed** (core is a library) |
| Models | `from trusts.zero.models import Trust, Content, Junction` | **unchanged** |
| Backend | `'trusts.backends.TrustModelBackend'` (core historical class) | `'trusts.zero.backends.TrustModelBackend'` (distinct Zero class) |
| Registry owner | `kernel_config()` | `implementation_for_path('trusts.zero.backends.TrustModelBackend')` / `ZeroConfig` |
| Settings constants | `from trusts.zero import ENTITY_MODEL_NAME, ROOT_PK, …` | **unchanged** |
| List codec | `django_permission_filter` → core `.authorized` → `kernel_config()` | same codec; Zero `ContentQuerySet.authorized` uses the owner |
| Django app label | `trusts` | **`trusts`** (unchanged, owned by ZeroConfig) |
| Migration names | `0001_initial`, `0002_trustgroup` | **unchanged** loader keys `trusts.0001_initial` / `trusts.0002_trustgroup` |
| Tables / content types | `trusts_trust`, `trusts \| trust`, … | **unchanged** |

### Old / new settings

```python
# Old (Z1 / raw 2.0.0.dev0, after C2)
INSTALLED_APPS = [
    'trusts',
    'trusts.zero.apps.ZeroConfig',
]
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'trusts.backends.TrustModelBackend',
]

# New (IIa)
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'trusts.zero.apps.ZeroConfig',
]
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'trusts.zero.backends.TrustModelBackend',
]
```

```python
# Old donations
from trusts.apps import kernel_config
kernel_config().configured_handles()

# New donations
from trusts.apps import implementation_for_path
implementation_for_path('trusts.zero.backends.TrustModelBackend')
```

### Startup / failure

| Situation | IIa behavior |
| --- | --- |
| Supported settings above | populate succeeds; `ZeroConfig` is the sole `TrustsImplementationConfig` |
| `'trusts'` listed (installs kernel `AppConfig`) | not the supported IIa install; do not use |
| `'trusts.backends.TrustModelBackend'` listed | `ImproperlyConfigured` naming `trusts.zero.backends.TrustModelBackend` |
| Core below `1.0.0.dev2` or missing `TrustsImplementationConfig` | `ImproperlyConfigured` from the startup belt |
| `kernel_config()` under supported IIa | `LookupError` (no kernel `AppConfig`) |

Do **not** add transparent core-path forwarding. The old backend path
must fail, not succeed as an alias.

## Migration identity

Loader keys remain `('trusts', '0001_initial')` / `('trusts', '0002_trustgroup')`
because `ZeroConfig.label = 'trusts'`. No `0003`.
`0002` still `dependencies = [('trusts', '0001_initial')]` and
`database_operations=[]`.

Already-applied 1.x / Z1 DBs keep matching `django_migrations` rows.
`makemigrations trusts --check` is quiet. Table names, content-type
natural keys, permissions, and representative rows are unchanged.

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
from trusts.apps import kernel_config
kernel_config(
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

- [ ] Remove `'trusts'` from `INSTALLED_APPS`. Keep only `'trusts.zero.apps.ZeroConfig'`.
- [ ] Replace `'trusts.backends.TrustModelBackend'` with `'trusts.zero.backends.TrustModelBackend'`. Do not leave the old path as an alias.
- [ ] Do not list bare `'trusts.zero'`.
- [ ] Canonical model import is `trusts.zero.models`. Do not add core-path forwarding.
- [ ] Replace `kernel_config()` donations with `implementation_for_path('trusts.zero.backends.TrustModelBackend')`.
- [ ] Settings constants for migrations/commands: `trusts.zero`.
- [ ] Replace `Content.grant`/`revoke`, `Trust.associate_group`/`grant_group_permission`/`revoke_group_permission`/`set_group_permissions`, and `TrustGroup.grant_permission`/`revoke_permission`/`set_permissions` with the ORM snippets above. Do not restore those methods.
- [ ] Keep ceiling writes on `TrustGroupPermission` (`.full_clean()` / `save` / `bulk_create`); do not bypass `local_grant_outside_ceiling`.
- [ ] `filter_by_user_content_perm(user, ContentModel, 'add')` must keep authorizing the **content** permission (e.g. `add_category`), not `add_trust`.
- [ ] `python -m django migrate --plan` — no Trusts operations on an already-current database.
- [ ] `python -m django makemigrations trusts --check` — quiet.
- [ ] Confirm `ContentType` natural keys `trusts | trust` (and siblings) and `COUNT(*)` on every Trusts table are unchanged.
- [ ] Confirm `pip uninstall django-trusts-zero` does not delete `trusts/__init__.py`.
- [ ] Confirm the old backend path raises `ImproperlyConfigured` naming the canonical Zero path.
- [ ] Confirm django-trusts `<1.0.0.dev2` is rejected by metadata and the startup belt.
- [ ] Leave package version at `2.0.0.dev2`. Do not rewrite raw `2.0.0.dev0` history. Do not fold Z0-cap `2.0.0.dev1` into this step.
- [ ] Do not begin GH IIb, core Step III / `1.0.0.dev4`, Windows #17, or examples in this PR.

## Out of scope (this slice)

- GH IIb reconstitution
- Core Step III failure-only `kernel_config` tombstone / `1.0.0.dev3`
- Tombstone removal (`1.0.0.dev4`)
- Z0-cap metadata-only `2.0.0.dev1`
- Windows #17
- Examples
- User-path membership hop / `permission_in` on core `register()` (TGP full records wait on that core grammar)
