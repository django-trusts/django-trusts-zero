"""Test-only Trusts-derived backends for multi-path S3a/S3b cases."""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin
from trusts.zero.backends import TrustModelBackend


class TestsCatalogBackend(TrustModelBackendMixin, ModelBackend):
    """Listed backend for the tests app catalog.

    Category, Ticket, and Group registrations live on ``TestsConfig``.
    This class's module is ``tests.backends``, so
    ``get_containing_app_config`` binds it to that catalog.
    """


class MixinOnlyBackend(TrustModelBackendMixin, ModelBackend):
    """Listed mixin-only path: plan compiler, no package Trust-as-content."""


class HostTrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Kernel-only host backend. Pair historical SQL lives on Zero."""


class GroupOnlyBackend(TrustModelBackendMixin, ModelBackend):
    """Mixin host whose complete proof is registered TGP alternatives only.

    Isolation is records present vs absent on this backend, not a
    Zero-owned compiler. Hosts that need group-only coverage donate
    the TGP pair and omit TUP. The plan compiler is the app config's,
    not an attribute of this class.
    """


# Same owned Zero backend class under a second import path (alias tests).
AliasedTrustModelBackend = TrustModelBackend


class MissingCompilerBackend(TrustModelBackendMixin, ModelBackend):
    query_compiler = None


class MalformedCompilerBackend(TrustModelBackendMixin, ModelBackend):
    query_compiler = object()


class _RaisingQueryCompiler(object):
    def complete_exists(self, plan, candidates, user, permission, *,
                        skipped=()):
        raise RuntimeError('compiler exploded')

    def group_exists(self, plan, candidates, user, permission, *,
                     skipped=()):
        raise RuntimeError('compiler exploded')


class RaisingCompilerBackend(TrustModelBackendMixin, ModelBackend):
    query_compiler = _RaisingQueryCompiler()
