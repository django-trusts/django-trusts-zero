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
| Paired core #151 C1 | [django-trusts#154](https://github.com/django-trusts/django-trusts/pull/154) merge [`b6eebc9273bf30048d410305a53249bdb51679f0`](https://github.com/django-trusts/django-trusts/commit/b6eebc9273bf30048d410305a53249bdb51679f0) |
| Previous paired core #142 Stage A | [django-trusts#144](https://github.com/django-trusts/django-trusts/pull/144) head [`5d12fa2fe18097abfe8f4ed30da6dafd1ace60be`](https://github.com/django-trusts/django-trusts/commit/5d12fa2fe18097abfe8f4ed30da6dafd1ace60be) |
| Previous paired core #18/#120 | [django-trusts#121](https://github.com/django-trusts/django-trusts/pull/121) head [`a0104be138f5fbcc7d74ce1fce8054c3e1e89634`](https://github.com/django-trusts/django-trusts/commit/a0104be138f5fbcc7d74ce1fce8054c3e1e89634) |
| Zero Z-convert baseline | [`94256b4e50acc0c95c488cfc1e8797d542cf65b7`](https://github.com/django-trusts/django-trusts-zero/commit/94256b4e50acc0c95c488cfc1e8797d542cf65b7) |

# Zero #151 Z2: strip production `_ir` bind (1.0.0.dev0)

This is the Zero half of
[django-trusts#151](https://github.com/django-trusts/django-trusts/issues/151)
r2, paired with merged Core C1
[django-trusts#154](https://github.com/django-trusts/django-trusts/pull/154)
merge `b6eebc9273bf30048d410305a53249bdb51679f0`.
Package version stays **1.0.0.dev0**. No model, table, migration-loader
key, content type, permission row, stored authorization-data, or
`trusts.conditions` six-name public-API change.

Do **not** start Core C2 or the #152 archive/reset in this PR.
Historical sections below keep their original immutable SHAs.

## Decision

`ZeroConfig` donates TUP/TGP and Meta conditions through the handle API
only. Production no longer imports `trusts.conditions._ir` or binds
`RegistryConditionLookup`. Core now self-binds the private store adapter
at construct. Application hosts register a builder; they do not import
`_ir` or call `set_condition_lookup`. Tests may still override or unbind.

## Old → new

| Situation | Previous | New |
| --- | --- | --- |
| Production lookup | Zero imported `RegistryConditionLookup` from `_ir` and called `set_condition_lookup` | Core self-binds at construct. Zero does not import `_ir` or bind lookup |
| Donation | Same handle API, plus a redundant production bind | Handle API only (`register_zero_relations` / Meta donation in `ready()`) |
| Application authorization | `User.has_perm` / `.permitted()` / fail-closed unknown/malformed | Unchanged |
| Schema / data | Unchanged | Unchanged |
| Package version | `1.0.0.dev0` | Unchanged |
| Core `trusts.conditions` | Six public names | Unchanged |
| Active kernel pin | Stage A `710b3ea…` plus superseded Stage-B / six-name candidate jobs | Merged Core C1 `b6eebc9273bf30048d410305a53249bdb51679f0` only |

## Migration-bot checklist

- [ ] Search Zero production (`trusts/zero/**/*.py`) for
      `trusts.conditions._ir`, `_IR_MODULE`,
      `_load_conditions_implementation`, and `RegistryConditionLookup`.
      Those production imports and bind helpers go away.
- [ ] Search production `ready()` / donation for `set_condition_lookup`.
      Drop the redundant bind. Tests that inject a fake or unbind
      (`tests/legacy/test_issue54.py`) may keep the call.
- [ ] Search active pairing pins (`requirements.txt`,
      `.github/workflows/ci.yml`, `DEV.md`) for
      `710b3ea26778ff069d1f5329adc9f2f481a1ea92`,
      `12a81d2d679c8eaf98ea5f5e0fb20ab064ea9faa`,
      `30b4878e68883e81a16913e4fd05015f4551e164`,
      `STAGE_B_KERNEL_SHA`, `SIX_NAME_KERNEL_SHA`, `pair-stage-b`, and
      `pair-six-name`. Retarget the live companion pin to
      `b6eebc9273bf30048d410305a53249bdb51679f0` and remove the
      superseded candidate jobs. Do not delete those SHA literals from
      historical `migrates.md` sections.
- [ ] Confirm `User.has_perm`, `.permitted()`, unknown/malformed
      fail-closed, and Core's six-name `trusts.conditions` surface are
      unchanged.
- [ ] Confirm first-party donation remains zero-SQL.
- [ ] Do not apply a new Trusts schema or data migration; none was
      added.
- [ ] Leave Zero package version at `1.0.0.dev0` and core floor at
      `1.0.0.dev3`.
- [ ] Do not start Core C2 or the #152 archive/reset here.

## Out of scope (this slice)

- Core C2 pin-only follow-up
- #152 archive/reset of historical sections
- tags, releases, #145, #146, #138, #137

# Zero #142 Z-convert: registration-time condition builders

This is the Zero half of
[django-trusts#142](https://github.com/django-trusts/django-trusts/issues/142)
r2 / PM S1, paired with Core Stage A
[django-trusts#144](https://github.com/django-trusts/django-trusts/pull/144)
head `5d12fa2fe18097abfe8f4ed30da6dafd1ace60be`. Package version stays
**1.0.0.dev0**. No model, table, migration-loader key, content type,
permission row, or stored authorization-data change.

Do **not** ask Core to restore `legacy_permission_callbacks_allowed`,
`trusts.E002` / `trusts.W001`, or a writable post-ready live registry.

## Decision

A callable supplied to condition registration is a **builder**. Core
invokes it once with symbolic `(u, p, o)`, stores normalized IR, and
discards the callable from the policy record. Authorization never
invokes it.

Zero production `Trust:own` and test Meta fixtures are builders.
Donation uses `BackendHandle.register_permission_condition` inside
`ZeroConfig.ready()` (pre-finalization). After `apps.ready`, the live
handle is frozen; further `register_permission_condition` raises
`TrustsConfigurationError` **before** the builder runs. Ad-hoc test
conditions register on an isolated unfrozen `TrustsRegistry()`.

There is no Zero runtime-callback shim.

## Old → new

```python
# Old (Expr via condition_refs, registry write, runtime-callback meaning)
from trusts.conditions import condition_refs, legacy_permission_callbacks_allowed

u, p, o = condition_refs()

class Trust(Content):
    class Meta:
        permission_conditions = (('own', u == o.settlor),)

handle.registry.register_permission_condition(Ticket, 'own', u == o.owner)
handle.registry.register_permission_condition(
    Category, 'spy', lambda user, perm, obj: obj.name == 'keep',
)
# TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS = True  # object-only has_perm + W001

# New (builder; donate through the handle in ready())
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

## Behavior

| Situation | Old | New |
| --- | --- | --- |
| `Trust:own` / Meta tuples | Prebuilt `Expr` from `condition_refs()` | Builder callable donated in `ready()` |
| Explicit registration | `handle.registry.register_permission_condition` | `handle.register_permission_condition` in the pre-finalization window |
| Callable argument | Object-only runtime callback gated by `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS` | Builder: invoke once, store IR, never call during auth |
| Live registry after `apps.ready` | Condition writes still accepted | Frozen; register raises before builder invoke |
| Setting `True` | Object-only `has_perm` + `trusts.W001` | `trusts.E007`; does not enable callbacks |
| Setting missing / False | `trusts.E002`; callback never invoked | No callback path; `legacy_permission_callbacks_allowed` is deleted |
| `ConditionRecord.func` | Present (`None` for Expr) | Deleted; IR only (`record.expr`) |
| Isolated `TrustsRegistry()` | Unfrozen; still the test surface | Unchanged |

## Fail-closed rollout

1. Pair against Core Stage A `5d12fa2…` (this PR). Do not merge Core #144 until Chat reviews the exact-SHA pair.
2. Host apps convert Meta / explicit registrations to builders and move writes into `AppConfig.ready()`.
3. Remove `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS` and any `legacy_permission_callbacks_allowed` / `E002` / `W001` imports.
4. Example conversion and Core Stage B (public `Expr` / `condition_refs` import break) stay later.

## Deleted / retired consumer names

| Removed | Replacement |
| --- | --- |
| `from trusts.conditions import condition_refs` in Zero production / Meta | Builder `lambda u, p, o: ...` or a named `def` |
| `handle.registry.register_permission_condition` as the application API | `handle.register_permission_condition` |
| `legacy_permission_callbacks_allowed` | Deleted. Leftover setting is `trusts.E007` |
| `CHECK_ID_LEGACY_CALLBACK` / `trusts.E002` | Deleted |
| `CHECK_ID_LEGACY_CALLBACK_WARNING` / `trusts.W001` | Deleted |
| `ConditionRecord.func` | Gone. Use `record.expr` |

## Migration-bot checklist

- [ ] Search for `condition_refs` in Zero models, host Meta, and docs. Replace with builders.
- [ ] Search for `u == o.` / `_u == _o.` Meta tuples. Convert to `lambda u, p, o: ...` or a named function.
- [ ] Search for `register_permission_condition`. Call it on the **handle** from `AppConfig.ready()`, not on the post-ready frozen live registry.
- [ ] Search for `legacy_permission_callbacks_allowed`, `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS`, `trusts.E002`, `trusts.W001`, `CHECK_ID_LEGACY_CALLBACK`. Delete those expectations.
- [ ] Search for `record.func`. The field is gone; records are IR-only.
- [ ] Move ad-hoc test condition registration onto `TrustsRegistry()` (unfrozen). Do not write the live frozen registry.
- [ ] Confirm `Trust:own` still authorizes settlor rows on both `has_perm` and `.permitted()`.
- [ ] Confirm first-party donation (`Trust:own`, host Meta) is zero-SQL and idempotent on re-entry to `ready()`.
- [ ] Confirm a leftover `TRUSTS_ALLOW_LEGACY_PERMISSION_CALLBACKS = True` is `trusts.E007` and does not enable callbacks.
- [ ] Confirm a frozen handle raises `TrustsConfigurationError` before the builder is invoked.
- [ ] Do not apply a new Trusts schema or data migration; none was added.
- [ ] Leave Zero package version at `1.0.0.dev0` and core floor at `1.0.0.dev3`.

## Out of scope (this slice)

- Core Stage B (reject `Expr` / private IR move)
- zero-example conversion
- #138, #137, `TQ.contains` / membership grammar
- Restoring a Core callback shim or weakening freeze-before-invoke
- Merging Core #144


# Zero #18: declarative models + receive core #120 UI
