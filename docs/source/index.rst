django-trusts-zero
==================

``django-trusts-zero`` is the concrete continuation of django-trusts 0.x.
Use it when an application needs the historical Trust/Content models, stored
Django identities, and a migration path from the 0.x package. The name is
unrelated to Zero Trust networking.

The package depends on the schema-neutral ``django-trusts`` 1.x core. Core is
a Python library; Zero owns the concrete Django application, models, backend,
and migration identity.

Install
-------

.. code-block:: bash

   pip install django-trusts-zero

Configure the explicit Zero application and backend:

.. code-block:: python

   INSTALLED_APPS = [
       "django.contrib.contenttypes",
       "django.contrib.auth",
       "trusts.zero.apps.ZeroConfig",
   ]

   AUTHENTICATION_BACKENDS = (
       "django.contrib.auth.backends.ModelBackend",
       "trusts.zero.backends.TrustModelBackend",
   )

Do not add ``"trusts"`` to ``INSTALLED_APPS``. The core package arrives as a
dependency and does not provide a Django application. ``ZeroConfig`` keeps
the historical app label ``trusts`` so existing migrations, tables, content
types, permissions, and stored rows retain their identities.

Concrete model surface
----------------------

Representative imports are:

.. code-block:: python

   from trusts.zero.models import (
       Content,
       Junction,
       Trust,
       TrustGroup,
       TrustGroupPermission,
       TrustUserPermission,
   )

``Trust`` is the organization or scope tree. ``Content`` is the abstract
mixin for rows protected by a Trust. ``Junction`` supports an optional
through-model. ``TrustUserPermission`` and ``TrustGroupPermission`` persist
local grants; Django groups and roles provide membership and capability
ceilings.

Authorization
-------------

Object checks use Django's normal permission surface:

.. code-block:: python

   allowed = request.user.has_perm("billing.read_receipt", receipt)

Zero's backend uses core ``PlanQueryCompiler``. Its supported relational
object decisions and authorized listings compile through the same registered
policy and remain fixed-query with respect to candidate count.

Filter before slicing or pagination:

.. code-block:: python

   page = Receipt.objects.permitted("read", request.user)[:25]

``ContentQuerySet.permitted`` is Zero's Django-permission codec over
``.authorized``. ``get_permission`` resolves a Django permission for the
model. Create-under-Trust filtering uses the permission on the requested
content model:

.. code-block:: python

   targets = Trust.objects.filter_by_user_content_perm(
       request.user,
       Receipt,
       "add",
   )

That scope projection is implemented by core ``filter_authorized_scopes``.
The shared query primitives are ``granted`` and ``filter_authorized_scopes``;
malformed, unsupported, or unregistered policy fails closed.

Register protected content
--------------------------

``ZeroConfig`` registers ``Trust`` as protected content. A host application
donates each additional ``Content`` model from its ``AppConfig.ready()``:

.. code-block:: python

   from trusts.apps import implementation_for_path
   from trusts.zero.apps import CANONICAL_BACKEND_PATH
   from trusts.zero.registration import register_zero_content

   owner = implementation_for_path(CANONICAL_BACKEND_PATH)
   registry = owner.configured_backend(CANONICAL_BACKEND_PATH).registry
   register_zero_content(registry, Receipt)

``register_zero_content`` registers the direct
``TrustUserPermission`` path and two complete same-root
``TrustGroupPermission`` alternatives. A local group grant must also be
within either ``group.permissions`` or ``group.roles.permissions``. Complete
paths combine by OR. ``register_zero_relations`` performs only Zero's
Trust-as-content donation; host applications remain responsible for donating
their own content models.

Registered ``Meta.permission_conditions`` (including built-in
``Trust:own``) are builder callables donated through
``handle.register_permission_condition`` in ``ZeroConfig.ready()`` while
``apps.ready`` is still false. Core binds the registry-backed lookup at
``TrustsRegistry`` construction; Zero donates conditions only through
the handle API. Explicit named-condition registration uses the same
handle method in that pre-finalization window. After ready, the live
handle is frozen; further condition writes raise
``TrustsConfigurationError`` before a builder runs. Isolated tests use
an unfrozen ``TrustsRegistry()``.

Edit grants
-----------

Applications may edit ``TrustUserPermission`` and
``TrustGroupPermission`` through normal ORM workflows. Zero also supplies
authorization-aware helpers in ``trusts.zero.authorization``:

.. code-block:: python

   from trusts.zero.authorization import (
       associate_group_with_trust,
       grant_trust_group_permission,
       grant_trustee,
       revoke_trustee,
   )

   grant_trustee(actor, receipt, colleague, "read")
   associate_group_with_trust(actor, receipt, accountants)
   grant_trust_group_permission(actor, receipt, accountants, "read")
   revoke_trustee(actor, receipt, colleague, "read")

These helpers require administrative ``change`` authority. Group membership
and global ``Group.permissions`` changes can affect more than one Trust, so
real applications must still validate their own administrative workflows and
transaction boundaries.

Views and decorators
--------------------

Zero owns the reusable team views:

.. code-block:: python

   from django.urls import include, path

   urlpatterns = [
       path("", include("trusts.zero.urls")),
   ]

Their namespace is ``trusts`` (for example ``trusts:team_create`` and
``trusts:team_detail``). View decorators remain core APIs under
``trusts.decorators``.

Supported versions and limits
-----------------------------

* Python 3.12, 3.13, and 3.14
* Django 6.1
* ``django-trusts>=1.0.0.dev3,<2``
* Named permission conditions are registration-time builders. Core
  invokes the callable once with symbolic ``(u, p, o)``, stores IR only,
  and never runs it during ``has_perm`` or ``.permitted()``.
* Configured group and permission model substitutions are not supported.
* This development release preserves the 0.x persisted identity, but not
  every historical convenience method or import path.

Migration and related projects
------------------------------

* `Zero migration guide
  <https://github.com/django-trusts/django-trusts-zero/blob/dev/migrates.md>`_
  (executable 0.x → Zero route)
* `Core authorization guide
  <https://github.com/django-trusts/django-trusts/blob/dev/docs/source/index.rst>`_
* `Supported Python and Django versions
  <https://github.com/django-trusts/django-trusts/blob/dev/docs/support-matrix.md>`_
* `GitHub-style relational example
  <https://github.com/django-trusts/django-trusts-gh-permissions>`_
* `Bounded Windows ACL example
  <https://github.com/django-trusts/django-trusts-windows-acl>`_
* `Runnable Zero application
  <https://github.com/django-trusts/django-trusts-example/tree/dev>`_

Contributor and build history lives in ``DEV.md``. ``migrates.md`` is
the executable 0.x → Zero route. Unpublished chronology is the Core
archive tag ``migration-archive-pre-1.0``, not this file. Neither is
the current API reference.

Copyright BeeDesk, Inc., 2015--2026. BSD-2-Clause.
