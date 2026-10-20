"""Test-only Trusts-derived backends."""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin
from trusts.plan.relations import PlanQueryCompiler, QueryCompiler
from trusts.zero.backends import TrustModelBackend


class MixinOnlyBackend(TrustModelBackendMixin, ModelBackend):
    """Listed mixin-only path: plan compiler, no package Trust-as-content."""


class HostTrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Host backend. Pair historical SQL lives on Zero."""


class GroupOnlyBackend(TrustModelBackendMixin, ModelBackend):
    """Mixin host whose complete proof is registered TGP alternatives only.

    Isolation is records present vs absent on this backend, not a
    Zero-owned compiler. Hosts that need group-only coverage donate
    the TGP pair and omit TUP.
    """

    query_compiler = PlanQueryCompiler()


# Same owned Zero backend class under a second import path (alias tests).
AliasedTrustModelBackend = TrustModelBackend


class MissingCompilerBackend(TrustModelBackendMixin, ModelBackend):
    query_compiler = None


class MalformedCompilerBackend(TrustModelBackendMixin, ModelBackend):
    query_compiler = object()


class _RaisingQueryCompiler(QueryCompiler):
    def applies(self, plan):
        return bool(plan.records or plan.delegations)

    def complete_exists(self, plan, candidates, user, permission, *,
                        skipped=()):
        raise RuntimeError('compiler exploded')

    def group_exists(self, plan, candidates, user, permission, *,
                     skipped=()):
        raise RuntimeError('compiler exploded')


class RaisingCompilerBackend(TrustModelBackendMixin, ModelBackend):
    query_compiler = _RaisingQueryCompiler()
