# CONFLICT_MAP.md
# Shade Utility Platform V8 — Conflict and Duplication Map
> All findings from forensic source analysis. Nothing removed or changed.

---

## CONFLICT-01: `/time` vs `/epoch` — Functional Overlap

**CURRENT:**
- `/time` (crypto/router.py): Returns current Unix epoch as integer. Zero documentation.
- `/epoch` with no args (general/router.py): Returns current epoch **plus** formatted UTC string. Documented everywhere.

**PROBLEM:**
Two commands return the same core value (current Unix epoch). `/time` is a strict subset of `/epoch`. Users who discover `/time` get less information than `/epoch` and have no documentation to explain the difference.

**RISK:**
LOW. No runtime conflict. No routing conflict. Users simply have two ways to do the same thing. Confusion risk only.

**RECOMMENDED FUTURE ACTION:**
Option A (preferred): Deprecate `/time` silently — alias it to `/epoch` behavior (same output).
Option B: Remove `/time` and update CryptoTools to remove the handler.
Option C: Keep `/time` but add it to HELP_MANUAL_TEXT and the dev category description.

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-02: `/short` Category Mismatch

**CURRENT:**
- `/short` is implemented in `app/features/media/router.py` (MediaTools manifest)
- `/short` is documented under 🌐 Web & Utilities in the category description handler (`cat_web`)
- `/short` is listed under "Network & System Tools" section in HELP_MANUAL_TEXT

**PROBLEM:**
The command's router module (MediaTools) and its UI placement (Web & Utilities) disagree. This is an organizational inconsistency only — the command routes and executes correctly.

**RISK:**
LOW. No functional impact. Becomes important if MediaTools is ever disabled via `CapabilityRegistry.toggle()` — `/short` would be gated with MediaTools even though it appears in the web category.

**RECOMMENDED FUTURE ACTION:**
Move `/short` to a dedicated URL/Web utilities module (or to general/router.py if that's the logical home). Update HELP_MANUAL_TEXT and `cat_web` handler accordingly.

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-03: Dual ACTIVE_CLIENTS Dict Names

**CURRENT:**
Both `session/router.py` and `session_manager/router.py` define a module-level dict named `ACTIVE_CLIENTS`. They are in separate Python modules (different namespaces) and do not conflict at runtime.

**PROBLEM:**
Same variable name in two separate modules is a readability/maintenance hazard. A future developer merging or moving code could accidentally reference the wrong dict.

**RISK:**
LOW (runtime). MEDIUM (maintenance). If a future refactor imports from both modules in the same namespace, there would be a name collision.

**RECOMMENDED FUTURE ACTION:**
Rename `session_manager/router.py`'s dict to `SM_ACTIVE_CLIENTS` to make the distinction explicit. The existing `CS_ACTIVE` (for create_session) is already distinctly named. The `ACTIVE_CLIENTS` in session_manager/router.py is used for the login_session client tracking specifically.

**DO NOT CHANGE NOW:** YES — especially since session/router.py is FROZEN.

---

## CONFLICT-04: Duplicated QR Background Task Pattern

**CURRENT:**
- `session/router.py`: `_qr_countdown()` + `_wait_for_qr()` (QR session for /string)
- `session_manager/router.py`: `_cs_qr_countdown()` + `_cs_wait_for_qr()` (QR session for /create_session)

Both are near-identical implementations of the same pattern (countdown timer + wait for QR scan event).

**PROBLEM:**
Maintenance duplication. A bug fix to the countdown logic must be applied in two places independently.

**RISK:**
LOW (runtime — they are correctly isolated). MEDIUM (maintenance — drift risk if one is updated without the other).

**RECOMMENDED FUTURE ACTION:**
Extract the common pattern into `app/utils/session_tasks.py` with parameterized functions. session_manager can use these utilities. session/router.py (FROZEN) keeps its own copy — never modify it.

**DO NOT CHANGE NOW:** YES — session/router.py cannot be touched.

---

## CONFLICT-05: Duplicated Delivery Type Helpers

**CURRENT:**
Both session routers contain private helpers that describe Telegram's code delivery type names (e.g. `SentCodeTypeApp` → "Telegram App", `SentCodeTypeSms` → "SMS"):
- `session/router.py`: `_describe_current_type()`, `_describe_next_type()`
- `session_manager/router.py`: `_current_type_label()`, `_next_type_label()`

Same logic, slightly different names.

**PROBLEM:**
If Telegram adds a new `SentCodeType` variant in a future Telethon update, both files must be updated independently.

**RISK:**
LOW. Separate namespaces. Both work correctly.

**RECOMMENDED FUTURE ACTION:**
Consolidate into `app/utils/telethon_helpers.py`. session_manager imports from it. session/router.py (FROZEN) keeps its own copy.

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-06: `back_main` Callback — Cross-Module Dependency

**CURRENT:**
The `back_main` callback is:
- **Used in** `_session_menu_kb()` keyboard (session_manager/router.py)
- **Handled in** `back_to_main()` (general/router.py)

**PROBLEM:**
session_manager has an invisible dependency on general's callback handler. If general/router.py fails to load (feature isolation), the Back button from the session manager menu would become a dead button.

**RISK:**
LOW in practice (general is extremely unlikely to fail to load). Medium as an architectural principle (invisible cross-module dependency).

**RECOMMENDED FUTURE ACTION:**
Either: (a) Add a `back_main` handler directly in session_manager as a passthrough, or (b) document this dependency explicitly so future developers don't remove the general handler thinking it's unused.

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-07: `metrics.api_failures` — Defined but Never Incremented

**CURRENT:**
`MetricsRegistry.api_failures` is a Prometheus `Counter` defined in `app/core/metrics.py`. No code anywhere calls `.inc()` on it.

**PROBLEM:**
Dead metric. Prometheus scraping would always show 0 for `api_failures_total`, making it useless for monitoring.

**RISK:**
INFO. No functional impact.

**RECOMMENDED FUTURE ACTION:**
Wire it into `ProviderFailoverEngine` — increment on each provider failure: `metrics.api_failures.labels(provider=provider_name).inc()` inside the failover engine's exception handler.

**DO NOT CHANGE NOW:** YES (but this is a low-risk improvement)

---

## CONFLICT-08: `cachetools` in requirements.txt — Unused

**CURRENT:**
`cachetools==5.3.2` is listed in `requirements.txt`. It is not imported anywhere in the application.

**PROBLEM:**
Unnecessary dependency adds to install time and attack surface.

**RISK:**
LOW. No functional impact. If `cachetools` has a vulnerability, the bot would be flagged even though it doesn't use it.

**RECOMMENDED FUTURE ACTION:**
Remove from requirements.txt. (Can be added back when IP caching is implemented — it's the natural choice for TTLCache.)

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-09: `MAX_RETRIES = 3` in Settings — Never Used

**CURRENT:**
`settings.MAX_RETRIES = 3` is defined in `app/core/config.py`. No code reads this value.

**PROBLEM:**
Dead configuration. Implies retry behavior exists when it doesn't.

**RISK:**
INFO. Misleading to future developers who read the Settings class.

**RECOMMENDED FUTURE ACTION:**
Either use it (implement retry in ProviderFailoverEngine or HTTP calls) or remove it.

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-10: `CapabilityRegistry.toggle()` — Defined, No Caller

**CURRENT:**
`toggle(name, state)` method exists in CapabilityRegistry. No code calls it. Only `require()` is called (by OCRService only).

**PROBLEM:**
Feature disabling infrastructure exists but is unused. Only OCR is gated. No admin command exposes the toggle.

**RISK:**
LOW. Infrastructure is not harmful.

**RECOMMENDED FUTURE ACTION:**
Add `/diag disable <feature>` and `/diag enable <feature>` to the admin commands (future upgrade, not now).

**DO NOT CHANGE NOW:** YES

---

## CONFLICT-11: `EventBus` — Publisher Without Subscribers

**CURRENT:**
`OCRService.extract_text()` publishes `"ocr_processed"` to the EventBus. No subscriber has been registered for any event type.

**PROBLEM:**
The event system is built but not wired. Events fire into void.

**RISK:**
INFO. No functional impact.

**RECOMMENDED FUTURE ACTION:**
Future candidates for subscribers: rate limiter, audit logger, metrics aggregator. When building any of these, subscribe to relevant events via `event_bus.subscribe()`.

**DO NOT CHANGE NOW:** YES

---

## Summary Table

| ID | Conflict Type | Severity | Runtime Impact | Fix Priority |
|---|---|---|---|---|
| C-01 | /time vs /epoch overlap | LOW | None | P3 |
| C-02 | /short category mismatch | LOW | None currently, risk if toggle used | P2 |
| C-03 | ACTIVE_CLIENTS name collision risk | LOW/MEDIUM | None (separate namespaces) | P2 |
| C-04 | QR task pattern duplication | LOW/MEDIUM | None | P3 |
| C-05 | Delivery type helper duplication | LOW | None | P3 |
| C-06 | back_main cross-module dependency | LOW | None in practice | P2 |
| C-07 | api_failures never incremented | INFO | Dead metric | P3 |
| C-08 | cachetools unused dependency | INFO | Unnecessary install weight | P2 |
| C-09 | MAX_RETRIES never used | INFO | Misleading config | P3 |
| C-10 | toggle() no caller | INFO | Unused infrastructure | P3 |
| C-11 | EventBus no subscribers | INFO | Events fire into void | P3 |
