from __future__ import annotations

from django.apps import apps
from django.core.checks import Error, register

from trusts.zero.apps import ZeroConfig
from trusts.zero.models import Content
from trusts.zero.registry import ContextRegistry, TrusteeRegistry, get_registry


def _kernel_owns_adapter_rewalks() -> bool:
    """True when the kernel already registers generic adapter re-walks."""
    return apps.is_installed("trusts")


def _unresolved_content_messages() -> list[Error]:
    """Leftover-only Content walker (no adapter re-walks, no trustee walk)."""
    messages: list[Error] = []
    leftovers = {
        name: item
        for name, item in Content._registry.items()
        if item.get("model") is None
    }
    if leftovers:
        leftover_names = ", ".join(sorted(leftovers))
        messages.append(
            Error(
                f"Unresolved Content model registrations: {leftover_names}.",
                hint=(
                    "Define the missing Content models, or remove unused Content.register() "
                    "calls."
                ),
                obj=Content,
                id="trusts.E006",
            )
        )
    return messages


def check_unresolved_content_registrations(
    app_configs=None, **kwargs
) -> list[Error]:
    """Register leftover Content errors when the kernel owns generic adapter re-walks."""
    return _unresolved_content_messages()


def check_context_registry(
    app_configs=None, **kwargs
) -> list[Error]:
    """Validate Content leftover registrations and generic adapter re-walks."""
    messages = _unresolved_content_messages()
    registry: ContextRegistry = get_registry()
    for name, adapter in registry.adapters.items():
        if not adapter.model_class:
            messages.append(
                Error(
                    f"Unresolved adapter registration: {name}.",
                    hint=(
                        "Adapter.contribute_to_class() was not called or the model "
                        "was never imported."
                    ),
                    obj=adapter,
                    id="trusts.E006",
                )
            )
            continue
        if adapter.pk_field != adapter.model_class._meta.pk.name:
            messages.append(
                Error(
                    f"Adapter {name} pk_field '{adapter.pk_field}' does not match "
                    f"model pk '{adapter.model_class._meta.pk.name}'.",
                    obj=adapter,
                    id="trusts.E007",
                )
            )
    return messages


def check_trustee_registry(
    app_configs=None, **kwargs
) -> list[Error]:
    """Validate that the Zero Trustee registry can still be frozen."""
    messages: list[Error] = []
    registry: TrusteeRegistry = get_registry().trustee
    try:
        registry.ensure_frozen()
    except Exception as exc:
        messages.append(
            Error(
                f"Trustee registry failed to freeze: {exc}",
                hint=(
                    "Call Trustee.configure() from AppConfig.ready() before the "
                    "registry is frozen."
                ),
                obj=TrusteeRegistry,
                id="trusts.E007",
            )
        )
    return messages


def _register_zero_checks() -> None:
    """Register leftover-only Content check when kernel owns adapter re-walks."""
    if _kernel_owns_adapter_rewalks():
        register(ZeroConfig.check_ready_ran, ZeroConfig)
        register(check_unresolved_content_registrations, ZeroConfig)
        return
    register(ZeroConfig.check_ready_ran, ZeroConfig)
    register(check_context_registry, ZeroConfig)
    register(check_trustee_registry, ZeroConfig)


_register_zero_checks()
