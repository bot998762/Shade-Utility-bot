"""
TranslationOrchestrator
=======================

Manages an ordered pool of translation providers and drives failover.

Failover policy:
  INPUT / USER errors (UNSUPPORTED_LANGUAGE, INVALID_INPUT)
    → raise immediately, do NOT try another provider

  AUTH / CONFIG errors (AUTH_ERROR, CONFIG_ERROR)
    → disable that entry permanently (this process lifetime)
    → raise immediately, do NOT failover (misconfiguration)

  TEMPORARY errors (TIMEOUT, CONNECTION, RATE_LIMITED, SERVER_ERROR,
                    EMPTY_RESULT, UNKNOWN)
    → record failure, apply cooldown after threshold, try next entry

Cooldown (in-memory, per process):
  After _FAILURE_THRESHOLD consecutive temporary failures:
    → entry enters cooldown for _DEFAULT_COOLDOWN_SECS
    → entry is skipped during cooldown window
    → on cooldown expiry: entry becomes eligible again (half-open)
  On any success: reset consecutive failure count

Attempt budget: _MAX_ATTEMPTS hard cap prevents retry storms.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.core.exceptions import ProviderAPIError
from app.providers.translation_provider import (
    FailureKind,
    ITranslationProvider,
    TranslationError,
)

logger = logging.getLogger(__name__)

_FAILOVER_ELIGIBLE: frozenset[FailureKind] = frozenset([
    FailureKind.TIMEOUT,
    FailureKind.CONNECTION,
    FailureKind.RATE_LIMITED,
    FailureKind.SERVER_ERROR,
    FailureKind.EMPTY_RESULT,
    FailureKind.UNKNOWN,
])

_NO_FAILOVER: frozenset[FailureKind] = frozenset([
    FailureKind.UNSUPPORTED_LANGUAGE,
    FailureKind.INVALID_INPUT,
    FailureKind.AUTH_ERROR,
    FailureKind.CONFIG_ERROR,
])

_DEFAULT_COOLDOWN_SECS: float = 60.0
_FAILURE_THRESHOLD: int = 3
_MAX_ATTEMPTS: int = 8


@dataclass
class _EntryState:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    disabled: bool = False

    def is_available(self) -> bool:
        if self.disabled:
            return False
        if self.cooldown_until > 0 and time.monotonic() < self.cooldown_until:
            return False
        return True

    def record_failure(self, kind: FailureKind) -> None:
        if kind in (FailureKind.AUTH_ERROR, FailureKind.CONFIG_ERROR):
            self.disabled = True
            logger.warning("Provider entry permanently disabled (auth/config error).")
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= _FAILURE_THRESHOLD:
            self.cooldown_until = time.monotonic() + _DEFAULT_COOLDOWN_SECS
            self.consecutive_failures = 0
            logger.info(
                "Provider entry entering cooldown for %ss.", _DEFAULT_COOLDOWN_SECS
            )

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.cooldown_until = 0.0


class TranslationOrchestrator:
    """
    Manages ordered provider pools and drives failover.

    Providers are tried in the order supplied.
    Google Cloud entries first, then LibreTranslate entries,
    as determined by the order passed from bootstrap.
    """

    def __init__(self, providers: list[ITranslationProvider]) -> None:
        self._providers = providers
        self._states: dict[str, _EntryState] = {
            p.provider_id: _EntryState() for p in providers
        }

    def has_providers(self) -> bool:
        return bool(self._providers)

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
    ) -> str:
        """
        Attempt translation across provider pool.
        Returns translated text string.
        Raises ProviderAPIError or ValueError (never raw provider exceptions).
        """
        if not self._providers:
            raise ProviderAPIError("No translation providers configured.")

        attempts = 0
        last_error: TranslationError | None = None

        for provider in self._providers:
            state = self._states[provider.provider_id]

            if not state.is_available():
                logger.debug("Skipping unavailable provider: %s", provider.provider_id)
                continue

            if attempts >= _MAX_ATTEMPTS:
                logger.warning(
                    "Translation: reached max attempt budget (%d).", _MAX_ATTEMPTS
                )
                break

            attempts += 1
            try:
                result = await provider.translate(text, target_lang, source_lang)
                state.record_success()
                logger.debug(
                    "Translation success via %s (attempt %d).",
                    provider.provider_id, attempts,
                )
                return result.translated_text

            except TranslationError as exc:
                last_error = exc
                logger.info(
                    "Provider %s failed: kind=%s",
                    provider.provider_id, exc.kind.value,
                )

                # _NO_FAILOVER check MUST precede record_failure so that
                # user-error kinds (UNSUPPORTED_LANGUAGE, INVALID_INPUT) do
                # not increment the provider's failure counter or trigger
                # cooldown. AUTH/CONFIG errors are handled inside
                # record_failure itself (sets disabled=True) and still need
                # record_failure called before we raise.
                if exc.kind in (
                    FailureKind.UNSUPPORTED_LANGUAGE,
                    FailureKind.INVALID_INPUT,
                ):
                    raise self._to_user_exception(exc)

                state.record_failure(exc.kind)

                if exc.kind in _NO_FAILOVER:
                    # AUTH_ERROR / CONFIG_ERROR: provider is now disabled;
                    # raise immediately without trying further providers.
                    raise self._to_user_exception(exc)

                # Eligible for failover — continue to next provider
                continue

            except asyncio.TimeoutError:
                last_error = TranslationError(
                    "Request timed out.",
                    FailureKind.TIMEOUT,
                    provider.provider_id,
                )
                state.record_failure(FailureKind.TIMEOUT)
                continue

            except Exception as exc:
                logger.warning(
                    "Unexpected exception from provider %s: %s",
                    provider.provider_id, type(exc).__name__,
                )
                te = TranslationError(
                    str(exc), FailureKind.UNKNOWN, provider.provider_id
                )
                last_error = te
                state.record_failure(FailureKind.UNKNOWN)
                continue

        # All providers exhausted or attempt budget reached
        if last_error is not None:
            raise self._to_user_exception(last_error)
        raise ProviderAPIError("Translation service is temporarily unavailable.")

    @staticmethod
    def _to_user_exception(exc: TranslationError) -> Exception:
        """Normalize provider error to safe user-facing exception."""
        kind = exc.kind
        if kind == FailureKind.UNSUPPORTED_LANGUAGE:
            return ValueError(
                f"Language not supported. "
                "Use a code like 'en', 'fr', 'hi', or a name like 'french'."
            )
        if kind == FailureKind.RATE_LIMITED:
            return ProviderAPIError(
                "Translation service is busy. Please try again in a moment."
            )
        if kind == FailureKind.TIMEOUT:
            return ProviderAPIError(
                "Translation service timed out. Please try again."
            )
        if kind in (FailureKind.AUTH_ERROR, FailureKind.CONFIG_ERROR):
            return ProviderAPIError(
                "Translation service is not properly configured."
            )
        return ProviderAPIError(
            "Translation service is temporarily unavailable."
        )
