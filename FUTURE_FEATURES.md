# FUTURE_FEATURES.md
# Shade Utility Platform V8 — Future Feature Proposals
> Blueprint only. No implementation. Every proposed feature has a rationale.
> Avoids feature bloat: each item must add genuine value to the existing utility bot identity.

---

## P0 — Essential (Should be done before any new feature)

---

### P0-01: Fix TestHealthEndpoints Test Suite

**Purpose:** The health endpoint is the production readiness signal for Render/Heroku. The test suite for it is currently broken and masked by a skip guard.

**Value:** Prevents silent regressions in the most critical monitoring component.

**Complexity:** Low — test-only change.

**Dependencies:** `aiohttp`, `unittest.mock.AsyncMock`

**Security concerns:** None.

**Performance concerns:** None.

**Potential conflicts:** None — test files only.

**Implementation approach:**
1. Update `_reset()` to set `bot_task=None` and `http_session=None` (actual dict keys)
2. Update `set_ready()` calls to pass `bot_task=AsyncMock(done=lambda: False)` and `http_session=MagicMock(closed=False)`
3. Remove the `@needs_aiohttp` skip since aiohttp is already a required dependency
4. Verify all 4 health tests pass

---

### P0-02: Add API_ID / API_HASH to .env.example and Settings

**Purpose:** Session features silently fail when `API_ID`/`API_HASH` are not set. New deployers have no indication these are required.

**Value:** Eliminates the most common deployment failure for session features.

**Complexity:** Low — config and documentation change.

**Dependencies:** None.

**Security concerns:** None (only documenting that the variable exists, not exposing values).

**Implementation approach:**
1. Add to `.env.example`:
   ```
   API_ID=
   API_HASH=
   ```
2. Add to `Settings` in `config.py`:
   ```python
   API_ID: int = int(os.getenv("API_ID", "0"))
   API_HASH: str = os.getenv("API_HASH", "")
   ```
3. Update `validate_startup()` to log a warning (non-fatal) if either is missing
4. Update session routers to read from `settings.API_ID` instead of `os.environ.get()` directly

---

### P0-03: Fix /b64de and /urlde Markdown Rendering Bug

**Purpose:** These commands give a misleading "Invalid Base64" error for valid inputs that decode to backtick-containing text.

**Value:** Correctness fix. Users currently cannot reliably use these commands with binary-encoded content.

**Complexity:** Low — parse_mode switch.

**Dependencies:** None (stdlib `html`).

**Implementation approach:**
1. In `crypto/router.py`: switch `/b64de` and `/b64en` replies to `parse_mode="HTML"` + `html.escape(decoded)`
2. In `general/router.py`: switch `/urlde` reply to `parse_mode="HTML"` + `html.escape(decoded)`
3. Add regression tests: base64 of a backtick string should succeed and display correctly
4. Update test_markdown_safety.py to include these commands in `UNTRUSTED_FIELDS`

---

## P1 — High Value

---

### P1-01: Per-User Rate Limiting

**Purpose:** Prevent resource exhaustion from a single user spamming commands.

**Value:** Stability under abuse. Protects external API quotas (OCRSpace, ip-api, wttr.in).

**Complexity:** Medium.

**Dependencies:** `cachetools.TTLCache` (already in requirements), or `asyncio` sliding window counter.

**Security concerns:** None — this is a protective measure.

**Performance concerns:** Small overhead per message (dict lookup). TTLCache is O(1) amortized.

**Potential conflicts:** None. Implemented as middleware or per-handler.

**Implementation approach:**
1. Create `app/middlewares/rate_limit.py` with `RateLimitMiddleware`
2. Per-user, per-command window: e.g., 5 requests per 10 seconds per user per command category
3. Different limits for expensive operations (OCR, translation) vs cheap (UUID, hash)
4. Rate-limited users get: `⏳ Slow down! Try again in {N} seconds.`
5. Register after PlatformErrorMiddleware in bootstrap

---

### P1-02: Maximum Concurrent Telethon Session Limit

**Purpose:** Prevent OOM on resource-constrained deployments from many simultaneous auth flows.

**Value:** Stability guarantee for production deployment.

**Complexity:** Low.

**Dependencies:** None.

**Security concerns:** None.

**Implementation approach:**
1. Add `MAX_SESSION_USERS = 25` constant to session routers (configurable via env var)
2. In `/string` and `/create_session` entry handlers: check `len(ACTIVE_CLIENTS) >= MAX_SESSION_USERS`
3. If at limit: reply "Authentication service is at capacity. Please try again shortly."
4. Do NOT add this to session/router.py (FROZEN) without extreme care — add only to session_manager

---

### P1-03: Fix /login_session Account Name Markdown Bug

**Purpose:** Account names with underscores or asterisks break Markdown rendering in login_session output.

**Value:** Correctness fix for session_manager.

**Complexity:** Low — parse_mode switch.

**Dependencies:** None.

**Implementation approach:**
1. In `session_manager/router.py` `ls_recv_file` handler: switch account display to `parse_mode="HTML"`
2. Apply `html.escape()` to `full_name` and `uname` variables before embedding in message
3. Add regression test for account name with underscore/asterisk

---

### P1-04: Tesseract Local OCR Fallback

**Purpose:** The current `DummyFallbackOCRProvider` returns an empty string when OCRSpace fails. A local Tesseract fallback would provide a meaningful second tier.

**Value:** OCR works even when the external API is unavailable. No additional API costs.

**Complexity:** Medium (requires Dockerfile change + new provider class).

**Dependencies:** `tesseract-ocr` (system package), `pytesseract` (Python).

**Security concerns:** Tesseract shells out to a system binary. The input is image bytes from Telegram (trusted source for the pixel data). No shell injection risk (image bytes, not shell commands).

**Performance concerns:** Tesseract is CPU-intensive. 2–5 seconds per image on small instances. Must be wrapped in `asyncio.wait_for()` with timeout.

**Potential conflicts:** None — replaces DummyFallbackOCRProvider, same interface.

**Implementation approach:**
1. Add `apt-get install -y tesseract-ocr` to Dockerfile
2. Add `pytesseract` to requirements.txt
3. Create `TesseractOCRProvider` implementing `IOCRProvider`
4. Replace `DummyFallbackOCRProvider` with `TesseractOCRProvider` in bootstrap
5. Keep `DummyFallbackOCRProvider` as last-resort third tier

---

### P1-05: Wire api_failures Prometheus Counter

**Purpose:** `metrics.api_failures` counter is defined but never incremented. Provider failures are invisible in metrics.

**Value:** Operational observability — know when providers are failing.

**Complexity:** Low.

**Dependencies:** None.

**Implementation approach:**
1. In `ProviderFailoverEngine.execute()`, after catching a provider exception, call:
   `metrics.api_failures.labels(provider=provider.__class__.__name__).inc()`
2. Verify counter increments in test

---

### P1-06: /epoch Timezone Support

**Purpose:** Current `/epoch` only outputs UTC. Most users care about local time.

**Value:** Genuinely useful for developers working across timezones.

**Complexity:** Low (stdlib `zoneinfo`).

**Dependencies:** stdlib `zoneinfo` (Python 3.9+).

**Implementation approach:**
`/epoch [value] [timezone]` — e.g., `/epoch 1700000000 America/New_York`
Use `ZoneInfo(tz_str)` with `ZoneInfoNotFoundError` catch.

---

## P2 — Nice to Have

---

### P2-01: /ip Response Caching

**Purpose:** Repeated lookups for the same IP hit ip-api.com unnecessarily.

**Value:** Reduces external API calls, faster responses for repeated queries.

**Complexity:** Low (`cachetools.TTLCache`, already in requirements).

**Implementation approach:**
`TTLCache(maxsize=256, ttl=300)` keyed by normalized input. Wrap in module-level dict.

---

### P2-02: /short URL Expand Mode

**Purpose:** Users often want to know where a short URL goes before clicking.

**Value:** Safety feature — verify short URL destination without visiting it.

**Complexity:** Medium (HEAD request with redirect follow + SSRF guard).

**Security concerns:** Must apply `is_safe_host()` SSRF guard to destination URL. Never fetch content, only follow redirects and show final domain.

---

### P2-03: /qr Error Correction Level Control

**Purpose:** Higher error correction allows QR codes to be scanned even when partially damaged/obscured.

**Value:** Professional use case (printing on surfaces, logos, etc.)

**Complexity:** Low (`qrcode` library supports this natively).

**Implementation approach:** `/qr H <text>` for HIGH error correction, etc.

---

### P2-04: /hash File Mode

**Purpose:** Hash a document file, not just text.

**Value:** File integrity verification — a common developer task.

**Complexity:** Low (download file, hash bytes).

**Performance concerns:** Files up to 20 MB via Bot API. Hash computation is fast.

---

### P2-05: /password Passphrase Mode

**Purpose:** Generate a memorable passphrase (e.g., `correct-horse-battery-staple` style).

**Value:** Practical — passphrases are both secure and memorable.

**Complexity:** Low (requires local wordlist file, stdlib `secrets.choice`).

**Dependencies:** Local EFF wordlist (~90 KB text file).

---

### P2-06: /b64de Binary Awareness

**Purpose:** When decoded Base64 is binary (non-UTF-8), show hex preview instead of error.

**Value:** Correctness — current behavior silently fails; new behavior tells user what they got.

**Complexity:** Low (try UTF-8, fall back to hex preview).

---

### P2-07: /checkpwd Common Password List

**Purpose:** Flag passwords that appear in common password lists.

**Value:** Materially improves the strength checker's usefulness.

**Complexity:** Low (local file, set lookup O(1)).

**Dependencies:** Local top-10000 common passwords list (~100 KB).

---

### P2-08: /tr Language Detection Mode

**Purpose:** Identify what language a text is in without translating.

**Value:** Useful utility, frequently requested.

**Complexity:** Low (deep_translator supports `detect_language()`).

---

### P2-09: Remove /time or Document It

**Purpose:** Resolve the undocumented `/time` command situation.

**Value:** Cleanliness — either users know about it or it's gone.

**Complexity:** Minimal.

**Options:** Add to HELP_MANUAL_TEXT and cat_dev, or remove handler.

---

### P2-10: /diag Provider Circuit Breaker Status

**Purpose:** Show which providers are currently OPEN/HALF_OPEN/CLOSED in /diag output.

**Value:** Operational visibility — know when OCRSpace or CleanURI is failing.

**Complexity:** Low (expose CircuitBreaker state in ProviderFailoverEngine).

---

## P3 — Experimental / Future

---

### P3-01: HaveIBeenPwned Integration for /checkpwd

**Purpose:** Check if a password appears in known data breaches via k-anonymity API.

**Value:** Real-world breach detection.

**Complexity:** Medium (HTTP call, SHA-1 prefix, parse response).

**Security concerns:** First 5 chars of SHA-1 sent to external API. k-anonymity is mathematically safe but must be explained to users.

**Note:** Make opt-in (`/checkpwd --pwned`), not default behavior.

---

### P3-02: Admin Auto-Alert on Polling Task Death

**Purpose:** If the bot's polling task dies, notify the admin via a fallback mechanism.

**Value:** Operational monitoring without external monitoring service.

**Complexity:** Medium (background health monitor task, bot.send_message to ADMIN_ID).

**Caution:** If the bot is down, it can't send messages via itself. Need a fallback (email, webhook).

---

### P3-03: /qr WiFi QR Generator

**Purpose:** Generate a WiFi configuration QR code.

**Value:** Common real-world use case (guest WiFi sharing).

**Complexity:** Low (format: `WIFI:S:SSID;T:WPA;P:PASSWORD;;`).

**Security concerns:** Password visible in Telegram command history.

---

### P3-04: /qrscan Multi-QR Support

**Purpose:** Decode all QR codes in an image, not just the first.

**Value:** Useful for images with multiple QR codes.

**Complexity:** Low (pyzbar already returns a list).

---

### P3-05: /ip ASN Lookup

**Purpose:** Look up Autonomous System Number details.

**Value:** Developer/security use case.

**Complexity:** Low-Medium (separate API or extend ip-api.com response).

---

### P3-06: /ip Port Checking via Shodan

**Purpose:** Check if specific ports are open on an IP.

**Value:** Security research utility.

**Complexity:** High (Shodan API key, rate limits, ethical concerns).

**Caution:** High potential for misuse. Implement only with strong rate limiting and admin-level logging.

---

### P3-07: /session refresh (new module, not modifying frozen /string)

**Purpose:** Re-authenticate an expired or revoked session and return a new one.

**Value:** Workflow completion for session_manager users.

**Complexity:** High (new module, new FSM, file upload + re-auth flow).

**Architecture note:** Must be a completely new isolated module following the session_manager isolation pattern.
