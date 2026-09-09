# Migration notes

## 2026-09-09: S5 leftover-only Content diagnostic (kernel companion)

Companion to django-trusts kernel S5 (`trusts.E006`/`trusts.E007`/`trusts.E008`).
When `KernelConfig` is installed, Zero no longer registers the combined
`check_context_registry` / `check_trustee_registry` walkers. Those generic
adapter re-walks and Trustee freeze diagnostics belong to the kernel.

Zero still owns unresolved legacy `Content` leftovers. With a kernel present,
`check_unresolved_content_registrations()` registers that leftover-only walk
exactly once. Combined `check_context_registry()` remains the no-kernel
fallback and still includes leftovers plus adapters.

Paired kernel+Zero `manage.py check` therefore emits exactly one leftover
`trusts.E006` for an unresolved `Content` declaration, and no duplicate
generic adapter `E006`/`E007` rows from Zero.

This is not a Zero execution-wrapper migration and does not change request-time
fail-closed behavior.

## 2026-09-07: S4 create-under-scope (kernel overlay)

`Trustee.create(...)` now accepts an explicit `scope=` argument so callers can
create a `User` under a known parent without going through `add_user`. The
runtime still requires a configured `scope_model`. A missing `scope=` value
raises `TypeError` at the wrapper; an unknown `scope=` value raises
`ObjectDoesNotExist` from `scope_model._default_manager.get(...)`.

The public wrapper does not grow `parent=` / `parent_id=` aliases, does not
change the existing `add_user` path, and does not interpret `scope=` as a
permission or group noun. Kernel S4 owns the same create-under-scope contract
for `trusts.api.Trustee`.

## 2026-09-07: S3 runtime + public Trustee surface

Zero now exposes a public `Trustee` namespace (`trusts.zero.Trustee`) with the
same constructor and helper surface as the kernel `trusts.api.Trustee` wrapper.
The previous `get_trustees(...)` helper remains as a compatibility alias.

Runtime changes:

- `content_type` / `permission` remain in the public constructor for one
  release. Passing either kwarg logs a `RemovedInZero20Warning` and the values
  are ignored.
- `Trustee.has_perm` no longer treats Django `Permission` rows or
  `user.has_perm(...)` as authorization success. Unknown or unpublished
  operations fail closed.
- Direct `Content` ORM authorization queries are no longer a supported
  compatibility path. Request-time code should use `Trustee.has_perm(...)`.

## 2026-09-06: First extracted Zero overlay

`django-trusts-zero` is the first extracted compatibility overlay. It keeps the
legacy `Content` noun, the historical `trusts.zero` import path, and the
Zero-era `Trustee` helpers that still talk to that noun.

The kernel no longer vendors this package. Install Zero independently when an
existing project still needs the `Content` model during the migration window.
