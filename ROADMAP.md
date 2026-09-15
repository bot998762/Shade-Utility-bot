# ROADMAP.md
# Shade Utility Platform V8 — Safe Future Roadmap
> Blueprint only. No implementation in this document.
> Each phase lists exact goals, files likely affected, risks, dependencies, required tests, and rollback considerations.

---

## PHASE 0 — Final Verification + Documentation
**Status: COMPLETE**

**Goals:**
- Complete forensic read of all source files
- Document exact current state
- Identify all bugs, conflicts, and risks
- Establish safe upgrade baseline

**Deliverables:**
- CURRENT_STATE.md ✅
- FEATURE_CATALOG.md ✅
- COMMAND_REFERENCE.md ✅
- ARCHITECTURE.md ✅
- SECURITY.md ✅
- TESTING.md ✅
- FEATURE_UPGRADE_BLUEPRINT.md ✅
- CONFLICT_MAP.md ✅
- FUTURE_FEATURES.md ✅
- UPGRADE_RISK_MATRIX.md ✅
- FROZEN_COMPONENTS.md ✅
- ROADMAP.md ✅

**Risk:** None (read-only)
**Rollback:** N/A

---

## PHASE 1 — Safe Low-Risk Fixes
**Goal: Fix known bugs and documentation gaps without changing architecture or adding features.**

All changes in this phase are isolated, low-risk, and verifiable.

---

### 1A: Fix TestHealthEndpoints (test-only)

**Files affected:**
- `tests/test_architecture.py` — `TestHealthEndpoints` class

**Changes:**
- Update `_reset()` to use correct `_readiness` keys (`bot_task`, `http_session`)
- Update `set_ready()` calls to use correct kwarg names and `AsyncMock`/`MagicMock` with correct return values
- Remove `@needs_aiohttp` skip decorator (aiohttp is always installed)

**Risk:** TEST ONLY. Zero production code changes. If tests fail: indicates a real production bug to investigate.

**Required tests:** All 4 `TestHealthEndpoints` tests must pass.

**Rollback:** Revert test file only.

---

### 1B: Add API_ID / API_HASH to .env.example and Settings

**Files affected:**
- `.env.example`
- `app/core/config.py`
- `app/features/session/router.py` — update `_get_creds()` to read from `settings`
- `app/features/session_manager/router.py` — update `_get_creds()` to read from `settings`

**Changes:**
- Add `API_ID=` and `API_HASH=` to `.env.example` with comment
- Add `API_ID: int` and `API_HASH: str` to `Settings` class
- Add `validate_startup()` WARNING log if either is missing (non-fatal)
- Change both `_get_creds()` functions to read `settings.API_ID` and `settings.API_HASH`

**Risk:** LOW. `session/router.py` change is minimal (two variable reads). The frozen constraint applies to the auth flow logic, not the settings reader.

**Required tests:**
- `TestSessionManagerCredGuard` must still pass
- New test: `TestAPICredsInSettings` — Settings exposes API_ID and API_HASH

**Rollback:** Revert `.env.example` and `config.py` changes. Revert `_get_creds()` to use `os.environ.get()` directly.

---

### 1C: Fix /b64de and /urlde Markdown Rendering Bug

**Files affected:**
- `app/features/crypto/router.py` — `/b64de` and `/b64en` handlers
- `app/features/general/router.py` — `/urlde` handler
- `tests/test_markdown_safety.py` — add to UNTRUSTED_FIELDS or dedicated test

**Changes:**
- `/b64de`: switch `parse_mode="Markdown"` → `parse_mode="HTML"`, wrap decoded output in `html.escape()` + `<code>` tag
- `/b64en`: same switch (output is Base64 charset, safe either way, but HTML is consistent)
- `/urlde`: same switch
- Add regression test: `TestB64DeBacktickSafety` — `/b64de` of backtick-containing input succeeds and returns correct decoded text

**Risk:** LOW. Only changes the display format (Markdown → HTML). The underlying decode logic is unchanged. HTML is strictly safer than Markdown for user-controlled content.

**Required tests:**
- New test: base64 encode "hello`world" → b64de → displays correctly (not error)
- New test: urlencode backtick → urldecode → displays correctly

**Rollback:** Revert parse_mode switch in affected handlers.

---

### 1D: Fix /login_session Account Name Markdown Bug

**Files affected:**
- `app/features/session_manager/router.py` — `ls_recv_file` handler (lines 1167–1185)

**Changes:**
- Switch account display to `parse_mode="HTML"`
- Apply `html.escape(full_name)` and `html.escape(uname)` before embedding in message
- Wrap fields in `<b>`, `<code>` HTML tags instead of Markdown `**`, `` ` ``

**Risk:** LOW. Only affects the success display message after `/login_session` validation.

**Required tests:**
- New test: account name with underscore/asterisk in `full_name` displays without Markdown parse error

**Rollback:** Revert the two lines in `ls_recv_file`.

---

### 1E: Fix cat_session Stale Usage Text

**Files affected:**
- `app/features/general/router.py` — `handle_session_cat` callback handler

**Changes:**
- Remove the line: `` "`/string <API_ID> <API_HASH>`\n\n" ``
- Replace with: `` "`/string` — Interactive authentication via Telegram\n\n" ``
- Remove the line: `"💡 Get credentials at https://my.telegram.org\n"` (stale — no longer user-facing)

**Risk:** MINIMAL. Text-only change in a callback handler.

**Required tests:** None (content tests don't currently exist for this handler).

**Rollback:** Revert the string constant in `handle_session_cat`.

---

### 1F: Remove cachetools from requirements.txt

**Files affected:**
- `requirements.txt`

**Changes:**
- Remove `cachetools==5.3.2` line

**Risk:** MINIMAL. Not imported anywhere. Can be re-added when IP caching is implemented.

**Required tests:** Verify no `import cachetools` exists in production code.

**Rollback:** Re-add the line.

---

### 1G: Document or Remove /time

**Files affected:**
- Option A (document): `app/features/general/router.py` (HELP_MANUAL_TEXT), `app/keyboards/inline_kb.py` (category dev button)
- Option B (remove): `app/features/crypto/router.py` (remove handler and `current_time()` from utils)

**Changes:**
- Option A: Add `/time` to HELP_MANUAL_TEXT under Developer Tools and to cat_dev callback description
- Option B: Remove `cmd_time` handler and its registration

**Risk:** LOW either way. `/time` has no users that we know of (undocumented). No callbacks or keyboard buttons reference it.

**Required tests:** If removing: add test that `/time` returns 404/no handler (negative test).

**Rollback:** Revert the single handler.

---

### Phase 1 Summary

| Change | Files | Risk | Tests needed |
|---|---|---|---|
| 1A: Fix health tests | test_architecture.py | Minimal | 4 health tests pass |
| 1B: API_ID/HASH in Settings | config.py, .env.example, 2× router.py | Low | New settings tests |
| 1C: Fix /b64de+/urlde Markdown | crypto/router.py, general/router.py | Low | New Markdown tests |
| 1D: Fix /login_session Markdown | session_manager/router.py | Low | New Markdown test |
| 1E: Fix cat_session text | general/router.py | Minimal | None |
| 1F: Remove cachetools | requirements.txt | Minimal | Verify no imports |
| 1G: /time resolution | crypto/router.py or general/router.py | Low | Depends on choice |

**Phase 1 Total Risk: LOW**
**Estimated files changed: 8**
**Zero architectural changes**

---

## PHASE 2 — Feature Upgrades
**Goal: Upgrade existing features with meaningful new capability. No new modules. No new major dependencies.**

Prerequisite: Phase 1 complete, all tests passing.

---

### 2A: /ip Improvements
- HTTPS endpoint (swap ip-api.com free HTTP for a provider with HTTPS free tier, or add HTTPS key)
- TTLCache (maxsize=256, TTL=300s) using `cachetools` (re-added to requirements)
- Add retry on timeout (1 retry, 2s delay)
- Expand output: add org/ASN, is_proxy flag (if provider supports)

**Files:** `app/features/general/router.py`, `app/providers/` (new IP provider or update existing), `requirements.txt`
**Risk:** LOW — same pattern, new provider URL, TTLCache is read-through
**Tests needed:** TestIPCache, TestIPRetry, TestIPHTTPS

---

### 2B: /weather Multi-Day + Units
- Unit selection: `/weather London F` (Fahrenheit)
- Multi-day: `/weather London 3` → 3-day forecast from wttr.in j1 response (daily data already present)
- Wind direction field

**Files:** `app/features/general/router.py`
**Risk:** LOW — same wttr.in endpoint, parse additional existing fields
**Tests needed:** TestWeatherUnits, TestWeatherForecast

---

### 2C: /epoch Timezone + Relative Time
- Timezone: `/epoch 1700000000 America/New_York`
- Relative time (no-arg mode): "2 hours ago" or "in 3 days"
- Duration: `/epoch 1700000000 1700086400` → 24 hours

**Files:** `app/features/general/router.py`
**Risk:** LOW — stdlib `zoneinfo`, careful catch `ZoneInfoNotFoundError`
**Tests needed:** TestEpochTimezone, TestEpochRelative

---

### 2D: /hash Extended Algorithms + File Mode
- Add SHA-3 256/512 and BLAKE2b (stdlib)
- File mode: reply to document + `/hash` → hash the file bytes

**Files:** `app/features/crypto/router.py`, `app/utils/crypto.py`
**Risk:** LOW for algorithms. MEDIUM for file mode (memory: up to 20 MB)
**Tests needed:** TestHashSHA3, TestHashBLAKE2, TestHashFileMode

---

### 2E: /password Passphrase Mode + Entropy Display
- Passphrase mode: `/password phrase` or `/password phrase 4` → N random words
- Show entropy bits alongside passwords
- Add local EFF wordlist as static file in `app/data/eff_wordlist.txt`

**Files:** `app/features/crypto/router.py`, `app/utils/crypto.py`, new `app/data/eff_wordlist.txt`
**Risk:** LOW
**Tests needed:** TestPassphraseGeneration, TestEntropyDisplay

---

### 2F: /checkpwd Enhanced Scoring
- Score breakdown: show which of 5 criteria passed/failed
- Minimum entropy estimate
- Common password list check (local top-10000 list as `app/data/common_passwords.txt`)

**Files:** `app/features/general/router.py`, `app/utils/crypto.py`, new `app/data/common_passwords.txt`
**Risk:** LOW
**Tests needed:** TestCheckpwdBreakdown, TestCheckpwdCommonList

---

### 2G: /qr Fixes and Enhancements
- Catch `DataOverflowError` with helpful user message
- Error correction level selection
- Size control option

**Files:** `app/features/media/router.py`, `app/utils/qr.py`
**Risk:** LOW
**Tests needed:** TestQROverflowError, TestQRErrorCorrectionLevel

---

### 2H: /qrscan Multi-Result + Type Display
- Decode all QR codes found (pyzbar returns list)
- Show format type (QR_CODE, EAN_13, etc.)

**Files:** `app/features/media/router.py`, `app/utils/qr.py`
**Risk:** LOW — pyzbar already returns this data
**Tests needed:** TestQRScanMultiple, TestQRScanFormat

---

### 2I: /short URL Validation + Expand Mode
- Input validation: check URL scheme before sending to providers
- Expand mode: `/short expand <short_url>` → HEAD request + SSRF guard → show destination domain

**Files:** `app/features/media/router.py` (or new URL module)
**Risk:** LOW for validation. MEDIUM for expand (SSRF guard critical path)
**Tests needed:** TestShortInputValidation, TestShortExpand, TestShortExpandSSRF

---

### 2J: /tr Language Detection + Alias Expansion
- Detect and display source language
- Expand alias list (more common language names)
- Better error messages for unsupported codes

**Files:** `app/features/media/router.py`, `app/services/translator_service.py`
**Risk:** LOW
**Tests needed:** TestTrDetectLanguage, TestTrAliasExpansion

---

### 2K: Tesseract Local OCR Fallback (if approved)
- New `TesseractOCRProvider` implementing `IOCRProvider`
- Replaces `DummyFallbackOCRProvider` as second tier
- Requires `Dockerfile` update and `pytesseract` in requirements.txt

**Files:** `app/providers/ocr_providers.py`, `app/core/bootstrap.py` (provider registration), `Dockerfile`, `requirements.txt`
**Risk:** MEDIUM — Dockerfile change + new system dependency
**Tests needed:** TestTesseractProvider, TestTesseractFallback, TestOCRFallbackChain

---

### 2L: Rate Limiting Middleware
- `app/middlewares/rate_limit.py` — new middleware
- Per-user, per-command-category sliding window
- Register in bootstrap after PlatformErrorMiddleware

**Files:** `app/middlewares/rate_limit.py` (new), `app/core/bootstrap.py`
**Risk:** LOW — middleware is additive, can be disabled by not registering it
**Tests needed:** TestRateLimitMiddleware, TestRateLimitExceedMessage

---

### 2M: /diag Enhanced Diagnostics
- Add active Telethon session count (read-only from ACTIVE_CLIENTS and CS_ACTIVE)
- Add circuit breaker states
- Wire api_failures counter

**Files:** `app/features/admin/router.py`, `app/core/metrics.py`, `app/platform/failover.py`
**Risk:** LOW
**Tests needed:** TestDiagSessionCount, TestDiagCircuitBreakers

---

### Phase 2 Summary

**Estimated files changed: 15–20**
**New files: 3–5 (data files, new middleware, new provider)**
**New dependencies: `pytesseract` (if 2K approved), `cachetools` (re-added)**
**Architectural changes: None (additive only)**

---

## PHASE 3 — Advanced Capabilities
**Goal: More powerful features, some with new external dependencies.**

Prerequisite: Phase 2 complete, all tests passing (including previously skipped tests now that aiogram/telethon are available in CI).

---

### 3A: HaveIBeenPwned Integration (/checkpwd --pwned)
- Opt-in only
- SHA-1 prefix k-anonymity lookup
- Clear user explanation before sending any data

**Dependencies:** `api.pwnedpasswords.com` (no key required)
**Risk:** MEDIUM — new external call, user trust/education required

---

### 3B: /tr Official API
- Switch from unofficial `deep_translator` to DeepL free API or LibreTranslate
- Keep `deep_translator` as fallback in ProviderFailoverEngine pattern

**Dependencies:** DeepL API key or LibreTranslate host
**Risk:** LOW-MEDIUM

---

### 3C: /ip Advanced (ASN, Reverse DNS, Multi-IP)
- Multi-IP batch mode
- Reverse DNS (PTR lookup via `dnspython`)
- ASN details

**Dependencies:** `dnspython`
**Risk:** LOW (dnspython is well-maintained)

---

### 3D: /b64de Binary Hex Preview + URL-safe Base64
- Binary content → show hex preview instead of error
- URL-safe variant

**Risk:** LOW

---

### 3E: /qr WiFi QR Mode
- `/qr wifi <SSID> <PASSWORD>`
- Standard WiFi QR format

**Risk:** LOW (format is standardized; password in command text is inherent limitation)

---

### Phase 3 Summary

**Estimated files changed: 10–15**
**New dependencies: DeepL or LibreTranslate, dnspython**
**Architectural changes: None**

---

## PHASE 4 — Performance and Security Hardening
**Goal: Infrastructure improvements — observability, resilience, ops tooling.**

---

### 4A: Event Bus Subscribers
- Audit log subscriber for OCR operations
- Rate limit subscriber (feeds into rate limit middleware)
- Metrics subscriber

**Risk:** LOW — subscribers are additive

---

### 4B: CapabilityRegistry Admin Toggle
- `/diag disable MediaTools`, `/diag enable MediaTools`
- Requires wiring existing `toggle()` method to admin commands
- Gate more handlers with `registry.require()` (currently only OCR)

**Risk:** MEDIUM — disabling a feature must not leave orphaned FSM state or dead buttons

---

### 4C: PDF OCR Support
- `/ocr` on PDF documents (not just photos)
- `pdf2image` + `poppler-utils` system package
- Strict limits: 5 pages max, 5 MB max, 30s timeout

**Risk:** MEDIUM-HIGH — poppler processes untrusted PDFs

---

### 4D: Admin Auto-Alert on Polling Death
- Background health monitor task
- If `bot_task.done()` → attempt to notify admin via secondary mechanism

**Risk:** MEDIUM — bootstrap change, background task

---

### Phase 4 Summary

**Architectural changes: Minor (background task, new middleware wiring)**
**Risk: MEDIUM**

---

## PHASE 5 — Final Regression Verification
**Goal: Ensure all frozen components remain intact after Phases 1–4.**

---

### 5A: Full Regression Suite Run
- All 214 tests must pass (170+ previously, 44 previously skipped must now run)
- Zero failures

### 5B: Frozen Component Verification
Explicitly verify each item in FROZEN_COMPONENTS.md:
- `ses_*` callbacks still only handled in `session/router.py`
- `ACTIVE_CLIENTS` and `CS_ACTIVE` still separate
- Shutdown order unchanged
- SSRF guard unchanged (all 15 vectors still blocked)
- No secrets in logs (AST check must still pass)

### 5C: Security Re-audit
- Re-run SSRF tests
- Re-run `TestNoSecretsInLogs`
- Manual review of any new handlers that take user input

### 5D: /session refresh (optional, Phase 5 only)
If `/session refresh` is approved, implement as a completely new isolated module at this phase when the regression suite is comprehensive enough to catch any interaction bugs.

---

## Upgrade Philosophy

1. **Always Phase 0 first** — never upgrade without a verified baseline
2. **Phases are sequential** — each phase's tests must pass before the next starts
3. **Frozen components are checkpoints** — verify them at the end of every phase
4. **New features are additive** — they must not require changes to frozen files
5. **If a planned change requires modifying session/router.py** — stop, re-evaluate, find an alternative approach
6. **Tests before features** — fix TestHealthEndpoints (Phase 1A) before adding any health-related features
7. **Security risk requires justification** — any upgrade in MEDIUM or HIGH security risk tier needs a documented threat model and mitigation before implementation
