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
