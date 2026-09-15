# FEATURE_CATALOG.md
# Shade Utility Platform V8 — Complete Feature Catalog
> Every feature documented from actual source code. No planned features included.

---

## Feature 1 — GeneralTools

**Module:** `app/features/general/router.py`
**Manifest:** `FeatureManifest(name="GeneralTools", version="1.0.0", category="Core")`

---

### /start

**Current purpose:** Display the main menu with category navigation buttons.
**Commands:** `/start`
**Current UI:** Sends banner text + `main_menu_kb` inline keyboard (5 rows of buttons).
**Current implementation:** Reads `bot_username` from DI middleware, renders greeting with user's first_name, sends `parse_mode="Markdown"`.
**Dependencies:** `main_menu_kb`, `category_dev_kb` (via keyboard module), `bot_username` from DI.
**Input:** None (CommandStart filter).
**Output:** Welcome banner + inline keyboard.
**Current capability:** Static welcome screen with category navigation.
**Current limitations:** Banner text is hardcoded; `bot_username` default is `"ShadeUtilityBot"` (correct fallback).
**Current security:** Uses user's `first_name` in Markdown. First names with `_` or `*` could technically cause rendering issues but are wrapped in `**{first_name}**` bold markers which are less fragile in practice.
**Current performance:** Immediate, no external calls.
**Status:** Working.

---

### /help

**Current purpose:** Display the full command manual.
**Commands:** `/help`
**Current UI:** Sends `HELP_MANUAL_TEXT` (multi-section Markdown block) + `category_dev_kb` (Back to Main Menu).
**Current implementation:** Static string reply with `parse_mode="Markdown"`.
**Dependencies:** `HELP_MANUAL_TEXT` constant, `category_dev_kb`.
**Input:** None.
**Output:** Full manual text with all 25+ documented commands.
**Current capability:** Static reference manual.
**Current limitations:** `/time` command is NOT listed in HELP_MANUAL_TEXT. Manual is a single monolithic string.
**Current security:** Static content only.
**Current performance:** Immediate.
**Status:** Working. Contains one documentation gap (/time missing).

---

### /epoch

**Current purpose:** Convert between Unix timestamp and ISO UTC date, or show current epoch.
**Commands:** `/epoch [timestamp|YYYY-MM-DD]`
**Current UI:** Reply with timestamp↔date result. No buttons.
**Current implementation:** `message.text.split(maxsplit=1)`. If no arg: returns current epoch + formatted UTC. If numeric: converts to UTC date. If ISO string: converts to Unix epoch. Uses `datetime.fromisoformat()` and `datetime.utcfromtimestamp()`.
**Dependencies:** stdlib `time`, `datetime`.
**Input:** Optional timestamp (integer) or date string (ISO format).
**Output:** Epoch integer + UTC formatted string, or vice versa.
**Current capability:** Bidirectional conversion. No-arg mode shows current time.
**Current limitations:** Only handles integers and ISO format. No timezone support. No relative time ("in 2 days"). Uses deprecated `datetime.utcfromtimestamp()` (Python 3.12 deprecation warning).
**Current security:** Input parsed with try/except; invalid input returns user-friendly error.
**Current performance:** Immediate (stdlib only).
**Status:** Working.

---

### /urlen

**Current purpose:** Percent-encode a string for URL query transmission.
**Commands:** `/urlen <text>`
**Current UI:** Reply with encoded string in backtick block.
**Current implementation:** `urllib.parse.quote(text)` via `crypto.url_encode()`. `parse_mode="Markdown"`.
**Dependencies:** `app/utils/crypto.py`, stdlib `urllib.parse`.
**Input:** Any text string.
**Output:** Percent-encoded string (e.g. `hello world` → `hello%20world`).
**Current capability:** Standard URL encoding.
**Current limitations:** Output uses `parse_mode=Markdown` backtick block. Percent-encoded output contains only safe chars (`A-Za-z0-9%`) so Markdown is safe here. No control over `safe` chars parameter.
**Current security:** No injection risk (output is alphanumeric + %).
**Current performance:** Immediate.
**Status:** Working.

---

### /urlde

**Current purpose:** Decode a percent-encoded URL string.
**Commands:** `/urlde <text>`
**Current UI:** Reply in backtick block, `parse_mode="Markdown"`.
**Current implementation:** `urllib.parse.unquote(text)` via `crypto.url_decode()`.
**Dependencies:** `app/utils/crypto.py`, stdlib `urllib.parse`.
**Input:** Percent-encoded string.
**Output:** Decoded plain text.
**Current capability:** Standard URL decoding.
**Current limitations:** ⚠️ Decoded output may contain backticks (`%60`), asterisks (`%2A`), underscores (`%5F`) — these break `parse_mode="Markdown"` in backtick span. `TelegramBadRequest` is caught by `PlatformErrorMiddleware` but user receives generic internal error message. Valid input can silently fail.
**Current security:** No injection risk (output shown in chat only).
**Current performance:** Immediate.
**Status:** Working with known UX bug for backtick-containing decoded output.

---

### /checkpwd

**Current purpose:** Evaluate password strength by character composition scoring.
**Commands:** `/checkpwd <password>`
**Current UI:** Reply with strength label.
**Current implementation:** Scores 0–5 based on: length≥8, length≥12, mixed case, digits, special chars. Returns "Very Strong", "Strong", "Moderate", or "Weak" label with emoji.
**Dependencies:** `app/utils/crypto.py`.
**Input:** Any password string.
**Output:** Strength label string.
**Current capability:** Basic 5-point heuristic scoring.
**Current limitations:** No entropy calculation. No breach database check. No dictionary attack simulation. No zxcvbn-style analysis. The password itself is visible in chat (unavoidable in Telegram).
**Current security:** Password appears in chat message. This is inherent to Telegram bot interaction — cannot be hidden.
**Current performance:** Immediate.
**Status:** Working.

---

### /ua

**Current purpose:** Display user's Telegram client metadata (ID, username, chat type, language).
**Commands:** `/ua`
**Current UI:** HTML-formatted reply with escaped fields.
**Current implementation:** Reads `message.from_user` and `message.chat`. All user-controlled fields escaped with `html.escape()`. Uses `parse_mode="HTML"`.
**Dependencies:** None (stdlib `html` module).
**Input:** None.
**Output:** User ID, username (escaped), chat type, language code.
**Current capability:** Client identity inspector.
**Current limitations:** Shows only what Telegram Bot API exposes (no actual HTTP UA string — it's a Telegram bot, not a web server). Name is slightly misleading.
**Current security:** HTML escaping applied to all user-controlled fields. Correct.
**Current performance:** Immediate.
**Status:** Working.

---

### /jsonfmt

**Current purpose:** Validate and pretty-print a JSON payload.
**Commands:** `/jsonfmt <json_string>`
**Current UI:** Reply with formatted JSON in triple-backtick code block. `parse_mode="Markdown"`.
**Current implementation:** `json.loads()` then `json.dumps(..., indent=4)`. Errors caught with try/except.
**Dependencies:** stdlib `json`.
**Input:** Raw JSON string (max ~4080 chars due to Telegram message limit).
**Output:** Pretty-printed JSON in ` ```json ``` ` code block.
**Current capability:** JSON validation and formatting.
**Current limitations:** ⚠️ Triple-backtick code fence breaks if JSON value contains ` ``` `. Generic `parse_mode=Markdown` risk for edge-case JSON values. No size limit enforcement (Telegram's 4096 char message limit is the de facto cap).
**Current security:** `json.loads()` is safe. No code execution.
**Current performance:** Immediate.
**Status:** Working with edge-case rendering risk for ` ``` ` in values.

---

### /ip

**Current purpose:** Geo-locate an IP address or domain.
**Commands:** `/ip <ip_address_or_domain>`
**Current UI:** "Executing..." status message → edited with HTML result.
**Current implementation:** SSRF guard via `is_safe_host()`, then `aiohttp GET` to `http://ip-api.com/json/{query}`. All response fields escaped with `html.escape()`. Handles 429, non-200, non-JSON, and API-level failures distinctly. `parse_mode="HTML"`.
**Dependencies:** `app/utils/network.py` (`is_safe_host`), `bootstrap_ref.http_session`, `ip-api.com` (HTTP, free tier).
**Input:** IP address or domain name.
**Output:** Country, city, region, ISP, timezone.
**Current capability:** Public IP geo-lookup with SSRF protection.
**Current limitations:** HTTP only (free tier). 45 req/min rate limit. No retry/backoff on failure. No caching. Domains are not DNS-resolved before SSRF check (relies on ip-api.com to handle domains).
**Current security:** SSRF guard blocks private/reserved ranges, loopback, link-local, CGNAT, decimal-int encoding, octal, hex. All output HTML-escaped.
**Current performance:** 10s timeout. Single request. No retry.
**Status:** Working.

---

### /weather

**Current purpose:** Show live weather for a city.
**Commands:** `/weather <city_name>`
**Current UI:** "Fetching..." status → edited with HTML weather card.
**Current implementation:** City name length-capped at 100 chars. `aiohttp GET` to `https://wttr.in/{city}?format=j1`. JSON parsed manually with KeyError/IndexError guard. All fields escaped with `html.escape()`. `parse_mode="HTML"`.
**Dependencies:** `bootstrap_ref.http_session`, `wttr.in`.
**Input:** City name string (max 100 chars).
**Output:** Temperature (C), feels-like, condition, humidity, wind speed.
**Current capability:** Live weather via wttr.in.
**Current limitations:** wttr.in is a public service with no API key or SLA. Non-JSON response (404/city not found) is handled as "city not found." No SSRF risk (URL is hardcoded). No unit selection (always Celsius). No forecast — current conditions only.
**Current security:** City name is `quote_plus`-encoded before use in URL. Response fields HTML-escaped. No injection risk.
**Current performance:** 10s timeout. Single request.
**Status:** Working.

---

### /id

**Current purpose:** Show numeric Telegram IDs for user, chat, thread, and replied message.
**Commands:** `/id`
**Current UI:** HTML reply with all available IDs.
**Current implementation:** Reads `message.from_user`, `message.chat`, `message.message_thread_id`, `message.reply_to_message`. Handles `from_user=None` (channel posts/anonymous) — shows "Anonymous / Channel" instead of crashing. All names escaped with `html.escape()`.
**Dependencies:** None.
**Input:** None (optionally reply to a message).
**Output:** User ID, chat ID, chat type, optional thread ID, optional replied-user ID/name/message ID.
**Current capability:** Complete Telegram identity inspector including thread and channel post handling.
**Current limitations:** None significant.
**Current security:** HTML escaping on all name fields. `from_user=None` guard exists (BUG-07 regression fix).
**Current performance:** Immediate.
**Status:** Working.

---

### /info

**Current purpose:** Show Telegram profile metadata for self or replied user.
**Commands:** `/info`
**Current UI:** HTML reply.
**Current implementation:** Uses `message.reply_to_message.from_user` if reply, else `message.from_user`. Guards `target is None` (channel post). Escapes all user-controlled fields. Shows first/last name, username, ID, premium status, bot/user type. `parse_mode="HTML"`.
**Dependencies:** None.
**Input:** None (optionally reply to a user).
**Output:** Profile card with name, username, ID, Premium rank, entity type.
**Current capability:** Profile metadata inspector.
**Current limitations:** Cannot show profile photo, bio, or restricted fields not exposed by Bot API.
**Current security:** All output HTML-escaped. `from_user=None` handled.
**Current performance:** Immediate.
**Status:** Working.

---

### Category Callbacks (general)

**Handlers:** `handle_dev_cat`, `handle_session_cat`, `handle_media_cat`, `handle_web_cat`, `handle_utils_menu`, `back_to_main`
**Purpose:** Display category information screens; navigate back to main menu.
**Note:** `handle_session_cat` shows stale usage text `` `/string <API_ID> <API_HASH>` `` which is incorrect — `/string` takes no arguments.

---

## Feature 2 — CryptoTools

**Module:** `app/features/crypto/router.py`
**Manifest:** `FeatureManifest(name="CryptoTools", version="1.0.0", category="Utility")`

---

### /uuid

**Current purpose:** Generate a cryptographically secure UUIDv4.
**Commands:** `/uuid`
**Current implementation:** `uuid.uuid4()` via `crypto.gen_uuid()`. Output in Markdown backtick block.
**Dependencies:** `app/utils/crypto.py`, stdlib `uuid`.
**Input:** None.
**Output:** UUIDv4 string (e.g. `550e8400-e29b-41d4-a716-446655440000`).
**Current capability:** Single UUID generation.
**Current limitations:** One UUID per call. No bulk generation. No namespace/v3/v5 variants.
**Current security:** Uses `uuid.uuid4()` (cryptographically random). Output is hex+dashes — safe in Markdown backtick.
**Current performance:** Immediate.
**Status:** Working.

---

### /password

**Current purpose:** Generate a high-entropy random password.
**Commands:** `/password [length]`
**Current implementation:** `secrets.choice()` over alphabet (`ascii_letters + digits + "!@#$%^&*"`). Length clamped to 8–64. Default 16.
**Dependencies:** `app/utils/crypto.py`, stdlib `secrets`, `string`.
**Input:** Optional integer length (8–64).
**Output:** Password string in Markdown backtick block.
**Current capability:** Single password with length control.
**Current limitations:** Fixed character set. No custom charset. No passphrase mode. No pronounceable mode. Password visible in chat.
**Current security:** Uses `secrets` module (cryptographically secure PRNG).
**Current performance:** Immediate.
**Status:** Working.

---

### /hash

**Current purpose:** Compute MD5, SHA-256, and SHA-512 hashes simultaneously.
**Commands:** `/hash <text>`
**Current implementation:** `hashlib.md5/sha256/sha512` on UTF-8 encoded input. All three hashes returned in one reply. `parse_mode="Markdown"`.
**Dependencies:** `app/utils/crypto.py`, stdlib `hashlib`.
**Input:** Any text string.
**Output:** Three hex digest strings.
**Current capability:** Three simultaneous hash algorithms.
**Current limitations:** Text only (not file hashing). No HMAC. No SHA-3. No BLAKE2. Hex digests are alphanumeric — safe in Markdown backticks.
**Current security:** No code execution. Input is hashed, not evaluated.
**Current performance:** Immediate (all stdlib).
**Status:** Working.

---

### /b64en

**Current purpose:** Encode text to Base64.
**Commands:** `/b64en <text>`
**Current implementation:** `base64.b64encode(text.encode('utf-8')).decode('utf-8')`. Output in Markdown backtick block.
**Dependencies:** `app/utils/crypto.py`, stdlib `base64`.
**Input:** Any text string.
**Output:** Standard Base64 string (A-Za-z0-9+/= — safe in Markdown backtick).
**Current capability:** Standard Base64 encoding.
**Current limitations:** No URL-safe Base64. No binary input.
**Current security:** Output charset is safe for Markdown backtick rendering.
**Current performance:** Immediate.
**Status:** Working.

---

### /b64de

**Current purpose:** Decode a Base64 string back to plain text.
**Commands:** `/b64de <string>`
**Current implementation:** `base64.b64decode(text.encode()).decode('utf-8')`. Wrapped in `try/except Exception` which also catches `TelegramBadRequest`.
**Dependencies:** `app/utils/crypto.py`, stdlib `base64`.
**Input:** Base64 encoded string.
**Output:** Decoded text in Markdown backtick block.
**Current capability:** Standard Base64 decoding.
**Current limitations:** ⚠️ Decoded output placed in Markdown backtick block. If decoded text contains backtick character, `TelegramBadRequest` is thrown, caught by inner `except Exception`, and user receives `❌ Error: Invalid Base64 string payload.` — which is **factually incorrect** (payload was valid; the display failed). No way for user to know the real reason.
**Current security:** No code execution. Exception caught.
**Current performance:** Immediate.
**Status:** Working with misleading error message for valid inputs that decode to backtick-containing text.

---

### /time

**Current purpose:** Return current Unix epoch timestamp.
**Commands:** `/time`
**Current implementation:** `int(time.time())` via `crypto.current_time()`. Output in Markdown backtick block.
**Dependencies:** `app/utils/crypto.py`, stdlib `time`.
**Input:** None.
**Output:** Current Unix epoch integer.
**Current capability:** Current timestamp only (subset of `/epoch` with no-arg mode).
**Current limitations:** ⚠️ Completely undocumented — not in `/help`, not in any category button, not in `HELP_MANUAL_TEXT`. Functional overlap with `/epoch` (no-arg mode). No formatted UTC date (unlike `/epoch`).
**Current security:** N/A.
**Current performance:** Immediate.
**Status:** Working but undocumented. Functionally redundant with `/epoch`.

---

## Feature 3 — MediaTools

**Module:** `app/features/media/router.py`
**Manifest:** `FeatureManifest(name="MediaTools", version="1.0.0", category="Utility")`
**Note:** All handlers in this module use `parse_mode="HTML"` with `html.escape()` on all dynamic content.

---

### /ocr

**Current purpose:** Extract text from an image using OCR.
**Commands:** Reply to a photo with `/ocr`
**Current UI:** "Processing..." status → edited with extracted text in `<code>` block.
**Current implementation:** Downloads highest-res photo from Telegram (`photo[-1]`). Posts to `api.ocr.space` via `ProviderFailoverEngine`. Falls back to `DummyFallbackOCRProvider` (returns `""`) if OCRSpace fails. All output `html.escape()`'d. Uses `parse_mode="HTML"`.
**Dependencies:** `OCRService`, `OCRSpaceProvider`, `DummyFallbackOCRProvider`, `CapabilityRegistry` (require check), `OCR_API_KEY` env var, `bootstrap_ref.http_session`.
**Input:** Photo (must be replied-to message, not direct attachment to `/ocr`).
**Output:** Extracted text or "No optical text detected."
**Current capability:** Single-image OCR with automatic failover and feature gating.
**Current limitations:** Photo fully buffered in RAM (Telegram max: 20 MB for bots). OCRSpace free tier limitations. Fallback returns empty string (no meaningful degradation message). No language hint. No page segmentation options.
**Current security:** All extracted text HTML-escaped before display. `registry.require("MediaTools")` gate. No file stored locally after processing.
**Current performance:** 15s timeout to OCRSpace. Photo downloaded from Telegram first. Memory: up to ~20 MB per request.
**Status:** Working.

---

### /short

**Current purpose:** Shorten a URL using a multi-provider failover engine.
**Commands:** `/short <url>`
**Current UI:** HTML reply with shortened URL.
**Current implementation:** `ShortenerService` → `ProviderFailoverEngine` → `CleanURIProvider` (primary) → `VGdURLProvider` (fallback). Both use text-first response reading (avoids `ContentTypeError`). Result validated to start with `http`. HTML-escaped before display.
**Dependencies:** `ShortenerService`, `CleanURIProvider`, `VGdURLProvider`, `bootstrap_ref.http_session`.
**Input:** URL string.
**Output:** Shortened URL.
**Current capability:** URL shortening with automatic failover. Two providers.
**Current limitations:** No input validation (any string accepted, providers may reject). No custom alias. No click tracking. `/short` is registered in `media/router.py` (MediaTools) but shown under Web & Utilities in the menu — category mismatch.
**Current security:** No SSRF risk (bot sends URL to shortener, doesn't fetch it). Shortened URL HTML-escaped in display.
**Current performance:** 15s timeout. Single request per provider attempt.
**Status:** Working. Category label mismatch (cosmetic, not functional).

---

### /tr

**Current purpose:** Translate text to a target language.
**Commands:** `/tr <lang>` (reply to text) or `/tr <lang> <text>`
**Current UI:** HTML reply with translated text.
**Current implementation:** `TranslatorService.translate()` → `GoogleTranslator(source="auto", target=code)` in thread executor with 15s `asyncio.wait_for()` timeout. `LANG_ALIASES` dict maps common names to ISO codes. Output HTML-escaped. `parse_mode="HTML"`.
**Dependencies:** `TranslatorService`, `deep_translator`, `deep_translator.exceptions.LanguageNotSupportedException`.
**Input:** Language code (e.g. `hi`, `es`, `fr`) + text (reply or inline).
**Output:** Translated text.
**Current capability:** Auto-detect source + translate to target. 8 pre-aliased languages.
**Current limitations:** Uses unofficial Google Translate API (no key, no SLA). Sync HTTP wrapped in executor (correct but adds thread overhead). No batch translation. No detect-only mode.
**Current security:** Output HTML-escaped. TimeoutError and ValueError both caught and shown to user.
**Current performance:** 15s timeout. Thread executor overhead. Network-bound.
**Status:** Working.

---

### /qr

**Current purpose:** Generate a QR code PNG from text or URL.
**Commands:** `/qr <text_or_url>`
**Current UI:** Reply with PNG photo + caption.
**Current implementation:** `qrcode.make(content)` → `io.BytesIO` → `BufferedInputFile` → `message.reply_photo()`. Caption HTML-escaped. `parse_mode="HTML"`. BytesIO closed in `finally`.
**Dependencies:** `app/utils/qr.py`, `qrcode`, `Pillow`.
**Input:** Any text or URL.
**Output:** PNG QR code image.
**Current capability:** QR code generation for any text content.
**Current limitations:** ⚠️ `qrcode.exceptions.DataOverflowError` not caught in `generate_qr_buffer()`. If content exceeds QR Version 40 capacity (~2953 bytes binary), error propagates to `PlatformErrorMiddleware` → generic "Internal system error" message to user with no guidance. No QR error correction level selection. No size/color options.
**Current security:** Content HTML-escaped in caption. BytesIO always closed.
**Current performance:** Immediate (local PNG generation). Image size: small PNG (~5–20 KB typically).
**Status:** Working with unhelpful error for oversized input.

---

### /qrscan

**Current purpose:** Decode a QR code from an image.
**Commands:** Reply to a QR photo with `/qrscan`
**Current UI:** "Scanning..." status → edited with decoded text.
**Current implementation:** Downloads photo. `Image.open(BytesIO(bytes))` → `pyzbar.decode()` → first result's `data.decode('utf-8')`. Output HTML-escaped.
**Dependencies:** `app/utils/qr.py`, `pyzbar`, `Pillow`, `libzbar0` (system).
**Input:** Photo containing a QR code (must be replied-to).
**Output:** Decoded QR content or "No QR code detected."
**Current capability:** Decodes first QR code found in image.
**Current limitations:** Only first QR code decoded (multi-QR images return only first). Requires `libzbar0` system library. No barcode support (only QR). UTF-8 decode may fail for binary QR content.
**Current security:** Output HTML-escaped. No file stored.
**Current performance:** Immediate after photo download. pyzbar is fast (C extension).
**Status:** Working.

---

## Feature 4 — session (FROZEN)

**Module:** `app/features/session/router.py`
**Manifest:** `FeatureManifest(name="session", version="4.0.0", category="Auth")`
**⚠️ FROZEN — DO NOT MODIFY**

---

### /string

**Current purpose:** Generate a Telethon StringSession for use in userbot/automation scripts.
**Commands:** `/string` (no arguments)
**Current UI:** Method selection keyboard → QR photo or OTP flow → result string.
**Current implementation:** Full QR+OTP Telethon auth flow. See ARCHITECTURE.md for complete flow. Isolated from session_manager via separate `ACTIVE_CLIENTS` dict, `StringSessionState` FSM, and `ses_*` callback prefix.
**Dependencies:** `Telethon`, `API_ID`/`API_HASH` env, `qrcode`, `Pillow`, FSM.
**Input:** None (all input via interactive Telegram flow).
**Output:** Telethon StringSession string in backtick code block.
**Current capability:** Full MTProto auth (QR + OTP + 2FA + resend + QR↔OTP switch).
**Current limitations:** API_ID/API_HASH come from environment (shared across all users). No per-user API credentials. String session is a long-lived credential (treat as password).
**Current security:** Session string not logged. Phone code hash logged by length only. 2FA password not logged. Temp client disconnected and removed from ACTIVE_CLIENTS on all exit paths. Background tasks guard against self-cancellation.
**Current performance:** Network-bound (MTProto). Background countdown + wait tasks per session. 120s timeout.
**Status:** Working. FROZEN.

---

## Feature 5 — SessionManager

**Module:** `app/features/session_manager/router.py`
**Manifest:** `FeatureManifest(name="SessionManager", version="1.0.0", category="Session")`

---

### /create_session

**Current purpose:** Authenticate via Telegram and export a SQLite `.session` file.
**Commands:** `/create_session`
**Current UI:** Session Manager sub-menu → method selection → auth flow → file delivery.
**Current implementation:** Same QR+OTP auth flows as `/string`. After successful auth, converts StringSession to SQLite file in `tempfile.mkdtemp()` (chmod 700), sets file permissions to 600, sends as Telegram document, cleans up in `finally`. Uses `CS_ACTIVE` dict (separate from session/ACTIVE_CLIENTS).
**Dependencies:** `Telethon`, `API_ID`/`API_HASH` env, `qrcode`, `Pillow`, FSM (`CreateSessionState`), `tempfile`, `shutil`, `sqlite3` (via Telethon).
**Input:** None (interactive auth flow).
**Output:** SQLite `.session` file as Telegram document.
**Current capability:** Full MTProto auth → SQLite file export.
**Current limitations:** File delivered over Telegram (end-to-end encrypted but passes through Telegram servers). Same shared API_ID/API_HASH as /string.
**Current security:** tmpdir chmod 700, file chmod 600, always deleted in finally. File size limited by Telethon output (typically <32 KB). Session file not logged.
**Current performance:** Network-bound. Additional SQLite conversion step after auth.
**Status:** Working.

---

### /login_session

**Current purpose:** Validate an uploaded Telethon `.session` file and show account info.
**Commands:** `/login_session`
**Current UI:** Prompts for file upload → validates → shows account summary.
**Current implementation:** Accepts `.session` document only (extension check + 512 KB size limit). Downloads to per-user tmpdir (chmod 700). Opens with Telethon SQLiteSession, calls `client.get_me()`. Shows non-sensitive account summary. Cleans up in `finally`.
**Dependencies:** `Telethon`, `API_ID`/`API_HASH` env, `tempfile`, `shutil`, FSM (`LoginSessionState`).
**Input:** `.session` file uploaded as document.
**Output:** Account summary (name, username, ID, tier, type) or error.
**Current capability:** Session file validation with account display.
**Current limitations:** ⚠️ Account name (`full_name`, `uname`) shown in `parse_mode="Markdown"` without `html.escape()`. Names with `_` or `*` could cause Markdown rendering issues. Not a security issue, but a UX rendering bug. Validation is "can we get_me()" — does not test specific permissions or scopes.
**Current security:** Extension + size guard. tmpdir chmod 700. Client disconnected before status edit. Cleanup in finally.
**Current performance:** Network-bound (one MTProto connection). Single `get_me()` call.
**Status:** Working with minor Markdown rendering bug for special-char account names.

---

## Feature 6 — AdminControl

**Module:** `app/features/admin/router.py`
**Manifest:** `FeatureManifest(name="AdminControl", version="1.0.0", category="System", is_premium=True)`

---

### /diag

**Current purpose:** Show platform diagnostics (feature count, HTTP status, RAM, CPU, uptime).
**Commands:** `/diag` (admin only)
**Current UI:** Markdown reply with platform report.
**Current implementation:** `F.func(_is_admin)` filter. Reads `registry.features`, `bootstrap_ref.http_session`, `psutil.Process()`. Shows loaded/disabled feature counts, HTTP pool status, RAM (RSS MB), CPU %, uptime seconds.
**Dependencies:** `psutil`, `CapabilityRegistry`, `bootstrap_ref`.
**Input:** None.
**Output:** Platform diagnostics report.
**Current capability:** Process-level health snapshot.
**Current limitations:** CPU `interval=None` gives instant reading (may be 0.0% most of the time). No history. No per-feature status. No Telethon session count.
**Current security:** Fail-closed: `ADMIN_ID==0` denies everyone. Exact integer match. No error reply to non-admins (silent non-match).
**Current performance:** `psutil.Process()` is fast but not zero-cost.
**Status:** Working.

---

### /health (Telegram command)

**Current purpose:** Show quick platform health status via Telegram message.
**Commands:** `/health` (admin only)
**Current UI:** Markdown reply.
**Current implementation:** `F.func(_is_admin)` filter. Checks `bootstrap_ref.http_session.closed`, reads `psutil.Process()` for RAM.
**Dependencies:** `psutil`, `bootstrap_ref`.
**Input:** None.
**Output:** Operational/Degraded status, RAM, HTTP client status.
**Current capability:** Quick health check via Telegram (complements HTTP health routes).
**Current limitations:** No bot_task alive check. No feature degradation list. No Telethon status.
**Current security:** Same fail-closed admin guard.
**Current performance:** Fast.
**Status:** Working.

---

## HTTP Health Routes

**Registered in:** `main.py`

| Route | Handler | Purpose |
|---|---|---|
| `GET /health/live` | `liveness_handler` | Always 200 — process alive |
| `GET /health/ready` | `readiness_handler` | 200/503 — checks live bot_task + http_session |
| `GET /health` | `health_check_handler` | Backward-compat alias for `/health/ready` |

**Readiness checks (live object references, not cached booleans):**
- `bot_task.done()` — polling task still running
- `http_session.closed` — aiohttp session open
- `degraded_features` — partial feature failures at load time

Returns 503 if either critical subsystem is down. Returns 200 with `"status": "degraded"` if optional features failed to load.
