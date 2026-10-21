"""Test-only Trusts-derived backends."""

from django.contrib.auth.backends import ModelBackend

from trusts.backends import TrustModelBackendMixin
from trusts.zero.backends import TrustModelBackend


class MixinOnlyBackend(TrustModelBackendMixin, ModelBackend):
    """Listed mixin-only path: plan compiler, no package Trust-as-content."""


class HostTrustModelBackend(TrustModelBackendMixin, ModelBackend):
    """Host backend. Pair historical SQL lives on Zero."""


class GroupOnlyBackend(TrustModelBackendMixin, ModelBackend):
    """Mixin host. Core reads the containing app's catalog, not a
    compiler stored on the backend class.
    """


# Same owned Zero backend class under a second import path (alias tests).
AliasedTrustModelBackend = TrustModelBackend
