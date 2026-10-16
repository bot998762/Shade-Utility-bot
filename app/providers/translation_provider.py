"""
Translation provider abstraction.

ITranslationProvider — protocol every translation backend must satisfy.
TranslationResult     — structured result value.
TranslationError      — provider-level error carrying failure classification.
FailureKind           — used by the orchestrator for failover decisions.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class FailureKind(enum.Enum):
    # User / input problems — do NOT failover
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    INVALID_INPUT = "invalid_input"
    # Temporary provider problems — eligible for failover / cooldown
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    # Configuration / auth problems — mark entry unhealthy
    AUTH_ERROR = "auth_error"
    CONFIG_ERROR = "config_error"
    # Provider returned unusable result
    EMPTY_RESULT = "empty_result"
    # Unknown
    UNKNOWN = "unknown"


@dataclass
class TranslationError(Exception):
    """Provider-level error. Never surfaced directly to Telegram users."""
    message: str
    kind: FailureKind = FailureKind.UNKNOWN
    provider_id: str = ""

    def __str__(self) -> str:
        return self.message


@dataclass
class TranslationResult:
    translated_text: str
    provider_id: str
    source_lang_detected: str = ""


@runtime_checkable
class ITranslationProvider(Protocol):
    provider_id: str

    def supported_languages(self) -> frozenset[str]:
        """Return ISO 639-1 codes this provider supports. Empty = assume all."""
        ...

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> TranslationResult:
        """Translate text. Raises TranslationError on any failure."""
        ...
