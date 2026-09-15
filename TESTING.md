# TESTING.md
# Shade Utility Platform V8 — Test Suite Documentation
> Verified from actual test source files. Test counts and results from forensic run.

---

## 1. Test Suite Overview

| File | Tests | Pass | Fail | Skip | Purpose |
|---|---|---|---|---|---|
| `tests/test_architecture.py` | 46 | 46 | 0 | 0 | AST/structural/security checks |
| `tests/test_behavioral.py` | 62 | 62 | 0 | 0 | Logic and data parsing |
| `tests/test_markdown_safety.py` | 46 | 25 | 0 | 21 | Parse mode / escaping |
| `tests/test_session_manager.py` | 60 | 37 | 0 | 23 | Session manager flows |
| **TOTAL** | **214** | **170** | **0** | **44** |  |

**44 skips** are graceful: guarded by `@needs_aiogram` or `@needs_telethon` decorators. They do not represent failures — they represent tests that require optional libraries to run.

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

### `tests/test_behavioral.py` (62 tests, all pass in isolation)

Mix of: pure-Python logic tests (no aiogram needed) and aiogram-dependent tests (skipped).

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

---

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
| SSRF guard correctness | `TestSSRFGuard` — 15 vectors, all passing |
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
