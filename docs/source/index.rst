django-trusts-zero Step IIa
===========================

Concrete 0.x Trusts models under ``trusts.zero``, owned by
``ZeroConfig`` on merged django-trusts Step I
(``1.0.0.dev2`` / merge ``39f1f961``). Unrelated to Zero Trust network
architecture.

This is **Step IIa** of the approved package-boundary staircase
(`#102 r5 <https://github.com/django-trusts/django-trusts/issues/102#issuecomment-5639018377>`_).
Package version is ``2.0.0.dev2`` with
``django-trusts>=1.0.0.dev2,<2``.

Core public APIs consumed
-------------------------

* ``trusts.query.AuthorizedQuerySet.authorized`` control flow via ``granted``
* ``trusts.core.filter_authorized_scopes``
* ``trusts.core.ConditionLookup`` / ``TrustsRegistry.set_condition_lookup``
* ``trusts.core.Ref`` / ``TrustsRegistry.register``
* ``trusts.apps.TrustsImplementationConfig``
* ``trusts.apps.implementation_for_path`` / ``implementation_for_class``
* ``trusts.backends.TrustModelBackendMixin`` (same object as ``trusts.core_backends`` until Step III)

Zero-owned surfaces
-------------------

* ``trusts.zero.apps.ZeroConfig`` — sole implementation owner
  (``name='trusts.zero'``, persisted ``label='trusts'``)
* Distinct canonical class ``trusts.zero.backends.TrustModelBackend``
  (not the temporary core historical class)
* Concrete models at ``trusts.zero.models``
* ``ContentQuerySet.permitted(perm, user)`` — Django-permission codec over
  owner-resolved ``.authorized``
* ``Model.objects.get_permission(...)``
* ``Trust.objects.get_or_create_settlor_default`` / ``get_root`` /
  ``filter_by_user_perm`` / ``filter_by_user_content_perm``
* ``Content.register_permission_condition`` and ``:condition`` overlay via
  ``ContentConditionLookup`` bound from ``ZeroConfig.ready()``
* Historical migrations ``trusts.0001_initial`` / ``trusts.0002_trustgroup``

Installation
------------

::

   INSTALLED_APPS = [
       'django.contrib.contenttypes',
       'django.contrib.auth',
       'trusts.zero.apps.ZeroConfig',  # models, label=trusts
   ]
   AUTHENTICATION_BACKENDS = (
       'django.contrib.auth.backends.ModelBackend',  # optional global
       'trusts.zero.backends.TrustModelBackend',
   )

Do **not** list ``'trusts'`` (core is a library, not an installed app).
Bare ``'trusts.zero'`` is forbidden. Do **not** keep
``'trusts.backends.TrustModelBackend'`` — IIa fails startup with
``ImproperlyConfigured`` naming the canonical Zero path.

Persisted identity is unchanged: migration keys
``('trusts', '0001_initial')`` / ``('trusts', '0002_trustgroup')``,
tables ``trusts_trust`` …, content types ``trusts | trust``.

Startup and failure behavior
----------------------------

* Missing Step I helper or django-trusts below ``1.0.0.dev2`` raises
  ``ImproperlyConfigured`` from ``ZeroConfig.ready()``.
* The old core backend path raises ``ImproperlyConfigured`` (not an alias).
* ``kernel_config()`` raises ``LookupError`` because the kernel
  ``AppConfig`` is not installed. Host apps donate through
  ``implementation_for_path``, never ``kernel_config()``.

Authorized list filtering
-------------------------

::

   from trusts.zero.models import Trust

   Trust.objects.permitted('change', request.user)
   Trust.objects.get_permission('change')
   Trust.objects.filter_by_user_content_perm(request.user, Receipt, 'add')

``.permitted`` does not sequence grant plans. It resolves the Django
permission codec (active principal, optional ``:condition``,
``get_permission``) and delegates to ``.authorized``. Handles come from
the Zero owner, not the kernel AppConfig.

TUP + TGP registration
----------------------

``ZeroConfig.ready()`` registers Trust-as-content TUP records on
``implementation_for_path('trusts.zero.backends.TrustModelBackend').configured_backend(...).registry``
using core ``Ref`` / ``register()``. TGP membership/ceiling records are
attempted on the same public API. Merged core user paths are still one
direct hop, so TGP ``user_set`` registration is rejected until a later
core grammar widening; group list/object grants continue through
Zero-owned ``HistoricalGroupQueryCompiler``.

Host Content subclasses still contribute their own TUP ``register()``
lines from their ``AppConfig.ready()``, using
``implementation_for_path``, not ``kernel_config()``.

Direct ORM writes (r7 deletion map)
-----------------------------------

Write conveniences are gone in 2.0: ``Content.grant`` / ``revoke``,
``Trust.associate_group`` / ``grant_group_permission`` /
``revoke_group_permission`` / ``set_group_permissions``, and
``TrustGroup.grant_permission`` / ``revoke_permission`` /
``set_permissions``. Ceiling integrity stays on
``TrustGroupPermission.clean`` / ``save`` / ``bulk_create``.

::

   from django.contrib.auth.models import Group
   from trusts.zero.models import (
       TrustGroup, TrustGroupPermission, TrustUserPermission,
   )

   perm = Receipt.objects.get_permission('read')

   # trustee grant / revoke
   TrustUserPermission.objects.get_or_create(
       trust=receipt.trust, entity=trustee, permission=perm)
   TrustUserPermission.objects.filter(
       trust=receipt.trust, entity=trustee, permission=perm).delete()
   TrustUserPermission.objects.filter(
       trust=receipt.trust, entity=trustee).delete()  # former perm=None

   # associate / disassociate
   trust.groups.add(accountants)
   trust.groups.remove(accountants)

   # local group grant / revoke / set
   tg, _created = TrustGroup.objects.get_or_create(
       trust=trust, group=accountants)
   TrustGroupPermission.objects.get_or_create(
       trustgroup=tg, permission=perm)
   TrustGroupPermission.objects.filter(
       trustgroup=tg, permission=perm).delete()
   # replace local set: delete extras, create missing TrustGroupPermission rows

   # membership / ceiling
   accountants.user_set.add(user)
   accountants.permissions.add(perm)

Create-under-Trust (``filter_by_user_content_perm``) resolves the
permission on the **requested content model** (``add_category``, not
``add_trust``).
