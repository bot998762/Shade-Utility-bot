# TESTING.md
# Shade Utility Platform V8 — Test Suite Documentation
> Verified from actual test source files. Test counts and results from forensic run.

---

## 1. Test Suite Overview

| File | Collected | Pass | Fail | Skip | Purpose |
|---|---|---|---|---|---|
| `tests/test_architecture.py` | 80 | 66 | 0 | 14 | AST/structural/security checks |
| `tests/test_behavioral.py` | 282 | 178 | 0 | 104 | Logic, data parsing, orchestrator, SSRF, /tr stub |
| `tests/test_markdown_safety.py` | 46 | 25 | 0 | 21 | Parse mode / escaping |
| `tests/test_phase2c_2k.py` | 128 | 128 | 0 | 0 | Phase 2C–2K features and architecture invariants |
| `tests/test_session_manager.py` | 60 | 37 | 0 | 23 | Session manager flows |
| `tests/test_short_expand_ssrf.py` | 74 | 67 | 0 | 7 | `/short expand` SSRF hardening (CHG-024) |
| `tests/test_qr_caption.py` | 15 | 13 | 0 | 2 | `/qr` caption length/escaping (CHG-026) |
| **TOTAL** | **685** | **514** | **0** | **171** | 136 subtests also passed |

Command: `/root/.local/bin/pytest tests/ -q` → `514 passed, 171 skipped, 136 subtests passed`.

**CHG-026:** new `tests/test_qr_caption.py` (15 collected: 13 run everywhere against a fake message/QR module, 2 need the real qrcode library). With real qrcode 7.4.2 and aiohttp 3.9.1 the full suite is 542 passed, 143 skipped, 0 failed. `test_markdown_safety.py::test_qr_input_escaped` was updated because caption escaping moved into `_build_qr_caption`.

**CHG-025:** +7 handler-message tests in `test_short_expand_ssrf.py` (`TestExpandResultMessages`); they need no optional dependencies, so all 7 pass in the default sandbox. With real qrcode 7.4.2 and aiohttp 3.9.1 the full suite is 527 passed, 143 skipped, 0 failed.

**CHG-024 follow-up:** +4 tests (3 QR overflow regression, 1 health-state isolation) that skip without optional deps. With real qrcode 7.4.2 and aiohttp 3.9.1 available, the full suite is 520 passed, 143 skipped, 0 failed (aiogram, telethon and pyzbar still absent).

**Correction (CHG-024):** earlier versions of this table listed 433 total / 286 pass / 147 skip. That was wrong: it omitted `test_phase2c_2k.py` (128 tests) and listed `test_architecture.py` as 46 tests when it collects 77. The table above is taken from actual collection and per-file runs. Before CHG-024 the full suite was 434 passed / 158 skipped (592 collected); CHG-024 added 67 collected tests (60 pass, 7 skip).

**Skipped tests are NOT passes.** Skip reasons in the current environment (`pytest -rs`): telethon not installed 86; aiogram not installed 32; deep_translator not installed 19; aiohttp not installed 21; pydantic_settings not installed 4; qrcode not installed 7; prometheus_client or other dependency not installed 2. Earlier notes attributing the behavioral skips to aiohttp alone were inaccurate.

**Dead tests:** the 19 `deep_translator` skips can never run as written: `deep-translator` was removed from `requirements.txt` in CHG-021 and nothing in `app/` imports it.

**Environment limitation:** aiogram, aiohttp, Telethon, qrcode, pyzbar, pydantic-settings, cachetools, python-json-logger and prometheus_client are not installed in the development container and could not be installed (package index unreachable). Handler-level behaviour and anything needing a real aiohttp connector were therefore not executed there. Run the full suite in an environment built from `requirements.txt` for complete coverage.

Skips are graceful: guarded by `@needs_aiogram`, `@needs_telethon`, `skipTest(...)` or `skipUnless(...)`. They do not represent failures — they are tests that require optional libraries, and they are reported separately from passes.

**Known broken tests (currently masked by skip):** `TestHealthEndpoints` — would fail with TypeError and assertion errors if aiohttp were present (see Section 4).

---

## 2. Test Structure

### `tests/test_architecture.py` (46 tests, all pass)

Pure AST/import/structural tests. No network. No Telegram. No mock of Bot.

| Class | Tests | What it checks |
|---|---|---|
| `TestSyntaxValidity` | 6 | All .py files in `app/` parse without SyntaxError |
| `TestCircuitBreaker` | 4 | CircuitBreaker state transitions (CLOSED→OPEN→HALF_OPEN→CLOSED) |
| `TestProviderFailoverEngine` | 3 | Failover engine calls secondary on primary failure |
| `TestCapabilityRegistry` | 3 | register(), require(), toggle() behavior |
| `TestCryptoUtils` | 6 | UUID, password entropy, hash correctness, b64 roundtrip, url encode/decode |
| `TestAdminCheckAST` | 2 | AST confirms `_is_admin` returns False when ADMIN_ID==0 |
| `TestSessionFeatureArchitecture` | 4 | ACTIVE_CLIENTS and CS_ACTIVE are separate dicts; shutdown functions exist |
| `TestShutdownOrderAST` | 3 | bootstrap on_shutdown calls SM shutdown before session shutdown |
| `TestNoSecretsInLogs` | 4 | AST confirms BOT_TOKEN/API_HASH/string_session never appear in log calls |
| `TestSSRFGuardAST` | 3 | is_safe_host() blocks loopback, private, CGNAT ranges |
| `TestNoPerRequestSessions` | 2 | No `aiohttp.ClientSession()` inside handler functions (all use shared session) |
| `TestHealthRoutesInMain` | 2 | /health/live and /health/ready registered in main.py |
| `TestHealthEndpoints` | 4 | **⚠️ CURRENTLY SKIPPED** (needs aiohttp) — would FAIL due to stale API |

---

### `tests/test_behavioral.py` (281 tests: 178 pass, 103 skip)

Mix of: pure-Python logic tests (no aiogram needed) and aiogram-dependent tests (skipped).
103 tests are skipped because optional libraries (aiogram, aiohttp, deep_translator, …) are not installed in the test container.

**Original classes (pre-CHG-022):**

| Class | Tests | Skip | What it checks |
|---|---|---|---|
| `TestWeatherResponseParsing` | 5 | 0 | wttr.in JSON field extraction, KeyError handling |
| `TestIPResponseParsing` | 5 | 0 | ip-api.com JSON field extraction, 429/error handling |
| `TestCleanURIResponseParsing` | 3 | 0 | CleanURI response parsing, bad response handling |
| `TestOCRSpaceResponseParsing` | 4 | 0 | OCRSpace JSON parsing, empty result handling |
| `TestSSRFGuard` | 15 | 0 | Full SSRF guard with 15 distinct attack vectors |
| `TestPasswordStrengthLabels` | 5 | 0 | checkpwd scoring labels (Weak/Moderate/Strong/Very Strong) |
| `TestFeatureManifestDescriptionField` | 3 | 0 | FeatureManifest has name, description, version fields |
| `TestLoadFeaturesReturnValue` | 2 | 0 | load_features() returns (loaded_list, failed_list) tuple |
| `TestNoUnsafeRespJson` | 4 | 0 | Providers use text-first response reading (avoids ContentTypeError) |
| `TestEventBusSyncGuard` | 3 | 0 | EventBus.publish() raises RuntimeError if called from sync context |
| `TestTranslatorTimeout` | 2 | ~2 | TranslatorService respects 15s timeout (needs asyncio runner) |
| `TestIdInfoNoneFromUser` | 3 | ~3 | /id and /info handle from_user=None without crash (needs aiogram mock) |
| `TestSessionSelfCleanup` | ~4 | ~4 | Cleanup removes from ACTIVE_CLIENTS/CS_ACTIVE (needs aiogram) |
| *(remaining aiogram-dependent)* | ~4 | ~4 | Various handler behavior tests |

**CHG-022 additions (50 new tests across 7 new classes):**

| Class | Tests | Skip | What it checks |
|---|---|---|---|
| `TestOrchestratorDefect01Regression` | 5 | 0 | UNSUPPORTED_LANGUAGE/INVALID_INPUT do not increment failure counters; AUTH_ERROR disables provider |
| `TestOrchestratorCooldownAndRecovery` | 5 | 0 | Cooldown entry/skip/all-in-cooldown/half-open recovery/attempt budget |
| `TestOrchestratorDuplicateProviderID` | 1 | 0 | Duplicate provider_id results in single _EntryState (documented behavior) |
| `TestSSRFHardeningLibreTranslate` | 20 | 0 | All previously bypassing vectors now blocked; legitimate endpoints pass; allow_private=True opt-in |
| `TestSSRFEndpointSafetyFunction` | 11 | 0 | Unit tests for `_is_endpoint_safe()`: IPv4-mapped IPv6, CGNAT, malformed URLs |
| `TestProviderPoolGapDetection` | 3 | 0 | Gap warnings logged for both LibreTranslate and Google pool builders |
| `TestIsEndpointSafePublicIPv6` | 3 | 0 | Cloudflare public IPv6 accepted; link-local and unique-local IPv6 blocked |

**CHG-023 addition (5 new tests, 1 new class):**

| Class | Tests | Skip | What it checks |
|---|---|---|---|
| `TestTrUpcomingFeatureStub` | 5 | 5* | `/tr` returns coming-soon notice; `parse_mode="HTML"`; `TranslatorService.translate` never called |

*Skipped when aiogram not installed (`_skip_no_aiogram()` guard). Pass when aiogram is present.

---

### `tests/test_short_expand_ssrf.py` (67 tests: 60 pass, 7 skip, 136 subtests — CHG-024)

All DNS and HTTP behaviour is faked (scripted resolver, fake sessions). No real network traffic, no real internal services, no port scanning. Layers 1–5 are stdlib-only and also pass on Python 3.11 and 3.12 (`python3.X -m unittest tests.test_short_expand_ssrf`).

| Class | Tests | What it checks |
|---|---|---|
| `TestUrlValidation` | 12 | Valid public URLs; schemes; embedded credentials; invalid ports; malformed input; non-canonical numeric hosts (decimal/octal/hex/short); prohibited IP literals; bracketed IPv6 and IPv4-mapped IPv6; zone ids; internal names; case/trailing-dot/IDNA normalisation |
| `TestAddressPolicy` | 6 | Public IPv4/IPv6 allowed; prohibited IPv4 and IPv6 classes; IPv4-mapped unwrap; 6to4 and NAT64 embedded IPv4 |
| `TestGuardedResolver` | 14 | `127.0.0.1.nip.io` / `localtest.me`-style names resolving to loopback blocked; every prohibited class via DNS; mixed public+private answers fail closed; DNS failure, resolver timeout, empty/malformed answers fail closed; DNS-rebinding answer sequences validated on every resolution (no caching); IP literals validated without reaching the base resolver; scoped IPv6; errors are `OSError` subclasses so aiohttp wraps them |
| `TestRedirectTracing` | 15 | Legitimate HTTP/HTTPS expansion; relative and protocol-relative redirects; redirects to loopback/private/link-local/metadata/IPv6/encoded hosts are never requested; bad scheme/credentials/port in redirects; oversized Location; multi-hop; redirect limit and truncation notice; loop detection (incl. case/fragment variants); overall deadline; network errors propagate |
| `TestErrorClassification` | 2 | blocked / timeout / network classification through `os_error` and cause chains |
| `TestWiringAndMessages` | 11 | Handler uses the bootstrap-owned guarded session, never a per-request or unguarded one; fails closed when missing; no host/exception text in replies; `logger` defined (regression); bootstrap creates and closes the session and shutdown order is preserved; guarded-session configuration; bounded constants; frozen file hash; `is_safe_host` not weakened |
| `TestAiohttpConnectionPathEnforcement` | 7 | **Skipped without aiohttp.** Real `TCPConnector` + `GuardedResolver`: hostname→loopback, rebinding, mixed answers blocked by the connector; DNS failure not reported as blocked; IP literals stopped before the connector; yarl/validator host agreement; `create_guarded_session()` configuration |

**Negative controls (run once, scratch copy, not committed):** removing the address-policy check made 84 tests fail; removing the resolver's answer validation made 21 tests fail.

**Legacy tests updated (CHG-024):** `tests/test_phase2c_2k.py::TestPhase2J_ShortExpand` had 8 assertions that string-matched the old implementation inside `media/router.py` (`_safe(redir_host)`, `_safe(initial_host)`, `location.startswith("/")`, old message text, etc.). They now assert the equivalent properties in `app/utils/safe_url.py` and the new router text. No assertion was removed without an equivalent stronger check.

### `tests/test_markdown_safety.py` (46 tests, 25 pass, 21 skip)

Tests that verify parse_mode usage and html.escape() application.

| Class | Tests | Skip | What it checks |
|---|---|---|---|
| `TestParseModesAreHTMLForUserContent` | 5 | 0 | /ua, /ip, /weather, /id, /info use HTML mode |
| `TestHTMLEscapingApplied` | 5 | 0 | AST confirms html.escape() called before each HTML reply |
| `TestNoRawMarkdownOnUserFields` | 5 | 0 | UNTRUSTED_FIELDS not interpolated into Markdown strings |
| `TestMediaHandlerMarkdownSafety` | 5 | 0 | /ocr, /short, /tr, /qr, /qrscan use HTML + escape |
| `TestNoRawMarkdownInSessionOutput` | 5 | 0 | /string output in backtick block (base64 chars — safe) |
| `TestNoRawMarkdownRemaining` | ~21 | ~21 | Aiogram-dependent markup behavior tests |

**Known gap:** `UNTRUSTED_FIELDS` set does not include `decoded`, `b64_decode(...)`, or `url_decode(...)`. Therefore `/b64de` and `/urlde` — which use `parse_mode=Markdown` with user-derived decoded output — are NOT caught by these tests. This is the test suite's most significant coverage gap.

---

### `tests/test_session_manager.py` (60 tests, 37 pass, 23 skip)

| Class | Tests | Skip | What it checks |
|---|---|---|---|
| `TestLoginSessionFileGuards` | 6 | 0 | Extension check, size limit, empty file handling |
| `TestTmpDirPermissions` | 4 | 0 | mkdtemp chmod 700, file chmod 600 |
| `TestCSActiveSeparation` | 3 | 0 | CS_ACTIVE separate from ACTIVE_CLIENTS |
| `TestShutdownAllSmSessions` | 3 | 0 | shutdown_all_sm_sessions() exported and callable |
| `TestCreateSessionState` | 4 | 0 | FSM state class exists with correct states |
| `TestLoginSessionState` | 3 | 0 | FSM state class exists with correct states |
| `TestSmCallbackPrefixIsolation` | 4 | 0 | sm_*/lsess_* callbacks not in session/router.py |
| `TestSessionManagerCredGuard` | 4 | 0 | _get_creds() returns falsy when env vars missing |
| `TestRmtmpdirCalled` | 3 | 0 | _rmtmpdir is called in finally blocks |
| `TestLoginSessionFileFlow` | ~7 | ~7 | Full aiogram mock of file upload flow (needs aiogram) |
| `TestCreateSessionQRFlow` | ~8 | ~8 | Full QR flow mock (needs aiogram + telethon) |
| `TestCreateSessionOTPFlow` | ~8 | ~8 | Full OTP flow mock (needs aiogram + telethon) |

---

## 3. What the Tests Protect

### Critical Protection (regression-preventing)

| Functionality | Test coverage |
|---|---|
| `/string` output never logged | `TestNoSecretsInLogs` — AST confirmed |
| `/short expand` SSRF (resolving hostnames, rebinding, redirects, IPv6) | `tests/test_short_expand_ssrf.py` — 60 passing deterministic tests + 7 aiohttp integration tests (skipped without aiohttp) |
| SSRF guard correctness | `TestSSRFGuard` — 15 vectors; `TestSSRFHardeningLibreTranslate` — 20 vectors; `TestSSRFEndpointSafetyFunction` — 11 unit tests; `TestIsEndpointSafePublicIPv6` — 3 IPv6 tests |
| Orchestrator DEFECT-01 (no counter on user errors) | `TestOrchestratorDefect01Regression` — 5 regression tests |
| Orchestrator cooldown/circuit-breaker | `TestOrchestratorCooldownAndRecovery` — 5 state tests |
| Provider pool gap/duplicate detection | `TestProviderPoolGapDetection` — 3 tests |
| Admin fail-closed when ADMIN_ID=0 | `TestAdminCheckAST` — AST confirmed |
| ACTIVE_CLIENTS and CS_ACTIVE separate | `TestCSActiveSeparation`, `TestSessionFeatureArchitecture` |
| Shutdown order (SM before string sessions) | `TestShutdownOrderAST` |
| Temp file permissions | `TestTmpDirPermissions` |
| File extension/size guards | `TestLoginSessionFileGuards` |
| Callback prefix isolation | `TestSmCallbackPrefixIsolation` |
| Provider failover logic | `TestProviderFailoverEngine` |
| CircuitBreaker state machine | `TestCircuitBreaker` |
| HTML escaping on all user-facing HTML replies | `TestHTMLEscapingApplied`, `TestParseModesAreHTMLForUserContent` |
| No aiohttp.ClientSession() created per-request | `TestNoPerRequestSessions` |
| All .py files are syntax-valid | `TestSyntaxValidity` |

---

## 4. Known Broken Tests

### `TestHealthEndpoints` (4 tests, currently skipped by `@needs_aiohttp`)

**Problem 1 — Wrong keyword argument names:**
```python
# Test code (wrong):
h.set_ready(bot_task_ok=True, http_session_ok=True, features_loaded=5, degraded_features=[])

# Actual signature:
def set_ready(*, bot_task: asyncio.Task, http_session: aiohttp.ClientSession, 
              features_loaded: int, degraded_features: list[str]) -> None:
```
Would raise `TypeError: set_ready() got unexpected keyword argument 'bot_task_ok'`.

**Problem 2 — Wrong mock types:**
`readiness_handler` calls `not bot_task.done()`. A bare `MagicMock().done()` returns a truthy `MagicMock`, so `not bot_task.done()` = `False`, causing the handler to return 503 instead of expected 200.

**Problem 3 — Stale `_reset()` dict:**
`_reset()` writes `bot_task_ok` and `http_session_ok` into `_readiness`, but `readiness_handler` reads `bot_task` and `http_session` (the live-object keys). Even bypassing the TypeError, `_readiness["bot_task"]` would be `None` (initial state), causing a `NoneType` AttributeError on `.done()`.

**Impact:** Health endpoint has zero test coverage despite having 4 tests written for it.

---

## 5. Testing Gaps

### Gap 1: `/b64de` and `/urlde` Markdown rendering
No test verifies that decoded output containing backticks causes a `TelegramBadRequest`. The `TestNoRawMarkdownInSessionOutput` test covers session output but not crypto decoder output.

### Gap 2: `/qr` DataOverflowError
No test verifies that oversized input to `/qr` produces a user-friendly error instead of a generic internal error.

### Gap 3: `/time` completely untested
No test references `/time` at all.

### Gap 4: `cat_session` stale usage text
No test verifies the content of category description messages.

### Gap 5: `/create_session` Markdown rendering
`/login_session`'s account name display in Markdown with special characters is not tested.

### Gap 6: `metrics.api_failures` never incremented
No test verifies that provider failures increment the counter (because they don't — it's dead code).

### Gap 7: End-to-end aiogram-dependent tests require aiogram install
21 tests in markdown_safety and 23 in session_manager skip without aiogram/telethon. A CI pipeline that can install these packages would increase coverage to ~190/214.

### Gap 8: `CapabilityRegistry.toggle()` untested as called path
`toggle()` is tested for its return value (TestCapabilityRegistry) but no production code calls it. No test validates behavior when a feature is actually disabled mid-run.

---

## 6. Recommended Regression Tests for Future Additions

Before any upgrade, ensure these specific regressions remain protected:

| Test requirement | Priority |
|---|---|
| ACTIVE_CLIENTS and CS_ACTIVE remain in separate modules | P0 |
| `ses_*` callbacks only handled in session/router.py | P0 |
| Shutdown calls SM cleanup before session cleanup | P0 |
| No secrets in logs | P0 |
| SSRF guard unchanged | P0 |
| HTML escaping on all new HTML-mode handlers | P1 |
| Fix TestHealthEndpoints before adding health features | P1 |
| Add test for /b64de+/urlde Markdown backtick case | P1 |
| Add test for /qr DataOverflowError user message | P2 |
