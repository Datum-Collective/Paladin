from .base import Provider, ProviderError, guidance
from .anthropic_api import Anthropic
from .openai_api import OpenAI

_REGISTRY: dict[str, Provider] = {p.id: p for p in (Anthropic(), OpenAI())}


def get_provider(pid: str) -> Provider:
    try:
        return _REGISTRY[pid]
    except KeyError:
        raise KeyError(pid) from None


def all_providers() -> list[Provider]:
    return list(_REGISTRY.values())


__all__ = ["Provider", "ProviderError", "guidance", "get_provider", "all_providers"]
