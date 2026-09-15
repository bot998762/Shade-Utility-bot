# COMMAND_REFERENCE.md
# Shade Utility Platform V8 — Complete Command Reference
> All commands verified from actual source. 27 registered commands, 20 callbacks, 3 HTTP routes.

---

## Commands

---

### `/start`

**Purpose:** Display the main menu and welcome banner.
**Input:** None
**Output:** Welcome banner + inline keyboard with category buttons
**Examples:**
- `/start`
**Errors:** None (always succeeds)
**Related buttons:** Generates `main_menu_kb` with all category buttons
**Category:** Core (GeneralTools)
**Dependencies:** `bot_username` from DI middleware

---

### `/help`

**Purpose:** Display the full command manual for all features.
**Input:** None
**Output:** Multi-section Markdown manual text + Back to Main Menu button
**Examples:**
- `/help`
**Errors:** None
**Related buttons:** `category_dev_kb` (Back to Main Menu)
**Category:** Core (GeneralTools)
**Dependencies:** `HELP_MANUAL_TEXT` constant
**Note:** Does not document `/time` (known gap)

---

### `/epoch [value]`

**Purpose:** Convert between Unix timestamp and ISO UTC date, or show current epoch.
**Input:**
- None → current epoch + formatted UTC
- Integer → UTC date for that timestamp
- ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS) → Unix epoch
**Output:** Timestamp ↔ UTC date conversion result
**Examples:**
- `/epoch` → `1700000000` + `2023-11-14 22:13:20 UTC`
- `/epoch 1700000000` → `2023-11-14 22:13:20 UTC`
- `/epoch 2024-01-01` → Unix epoch for that date
**Errors:** `❌ Invalid Date or Timestamp format.` on parse failure
**Related buttons:** None
**Category:** Developer Tools (GeneralTools)
**Dependencies:** stdlib `time`, `datetime`

---

### `/urlen <text>`

**Purpose:** Percent-encode a string for URL transmission.
**Input:** Any text string
**Output:** Percent-encoded string (e.g. `hello world` → `hello%20world`)
**Examples:**
- `/urlen hello world` → `hello%20world`
- `/urlen foo&bar=baz` → `foo%26bar%3Dbaz`
**Errors:** `❌ Usage: /urlen <text>` if no argument
**Related buttons:** None
**Category:** Developer Tools (GeneralTools)
**Dependencies:** `app/utils/crypto.py`, stdlib `urllib.parse`

---

### `/urlde <text>`

**Purpose:** Decode a percent-encoded URL string.
**Input:** Percent-encoded string
**Output:** Decoded plain text in Markdown backtick block
**Examples:**
- `/urlde hello%20world` → `hello world`
- `/urlde foo%60bar` → `` `foo`bar` `` (⚠️ backtick in output breaks Markdown)
**Errors:**
- `❌ Usage: /urlde <text>` if no argument
- Generic internal error if decoded output contains backtick (TelegramBadRequest swallowed by PlatformErrorMiddleware)
**Related buttons:** None
**Category:** Developer Tools (GeneralTools)
**Dependencies:** `app/utils/crypto.py`
**Known issue:** Markdown rendering breaks for decoded strings containing backticks, asterisks, or underscores

---

### `/checkpwd <password>`

**Purpose:** Evaluate password strength using character composition scoring.
**Input:** Password string
**Output:** Strength label: "Very Strong 🔒", "Strong ✅", "Moderate ⚠️", or "Weak ❌"
**Examples:**
- `/checkpwd abc` → `Weak ❌`
- `/checkpwd MyP@ssw0rd!2024` → `Very Strong 🔒`
**Errors:** `❌ Usage: /checkpwd <password>` if no argument
**Related buttons:** None
**Category:** Developer Tools (GeneralTools)
**Dependencies:** `app/utils/crypto.py`

---

### `/ua`

**Purpose:** Display Telegram client metadata (user ID, username, chat type, language code).
**Input:** None
**Output:** HTML-formatted client inspector card
**Examples:**
- `/ua` → shows your user ID, @username, chat type, language
**Errors:** None (always succeeds)
**Related buttons:** None
**Category:** Web & Utilities (GeneralTools)
**Dependencies:** None (reads message object)

---

### `/jsonfmt <json_string>`

**Purpose:** Validate and pretty-print a JSON string.
**Input:** Raw JSON string (up to ~4080 chars due to Telegram message limit)
**Output:** Formatted JSON in ` ```json ``` ` code block
**Examples:**
- `/jsonfmt {"key":"value","num":42}` → indented JSON block
**Errors:**
- `❌ Usage: /jsonfmt <json_string>` if no argument
- `❌ Invalid JSON: <error detail>` on parse failure
**Related buttons:** None
**Category:** Developer Tools (GeneralTools)
**Dependencies:** stdlib `json`
**Known issue:** Triple-backtick in JSON string values can break Markdown code fence

---

### `/ip <ip_address_or_domain>`

**Purpose:** Geo-locate an IP address or domain name.
**Input:** IPv4 address, IPv6 address, or domain name
**Output:** Country, city, region, ISP, timezone (HTML-formatted)
**Examples:**
- `/ip 8.8.8.8` → Google LLC, Mountain View, California, US
- `/ip example.com` → domain geo-lookup
**Errors:**
- `❌ Usage: /ip <ip_address_or_domain>` if no argument
- `❌ Private/reserved addresses are not allowed.` for SSRF-blocked inputs
- `⏳ IP lookup service is temporarily rate-limited.` on HTTP 429
- `❌ IP lookup service is temporarily unavailable.` on non-200
- `⏱️ IP lookup timed out.` on 10s timeout
- `❌ Cannot reach IP lookup service.` on connection error
**Related buttons:** None
**Category:** Web & Utilities (GeneralTools)
**Dependencies:** `is_safe_host()`, `bootstrap_ref.http_session`, `ip-api.com` (HTTP free tier)

---

### `/weather <city_name>`

**Purpose:** Show current weather conditions for a city.
**Input:** City name (max 100 characters)
**Output:** Temperature (°C), feels-like, condition, humidity, wind speed (HTML-formatted)
**Examples:**
- `/weather London` → weather card for London
- `/weather New York` → weather for New York
- `/weather London, UK` → more specific (recommended for ambiguous names)
**Errors:**
- `❌ Usage: /weather <city_name>` if no argument
- `❌ City name too long.` if > 100 chars
- `❌ Location not found.` on non-JSON response (city not found)
- `❌ Unexpected response from weather service.` on schema mismatch
- `⏱️ Weather service timed out.` on 10s timeout
**Related buttons:** None
**Category:** Web & Utilities (GeneralTools)
**Dependencies:** `bootstrap_ref.http_session`, `wttr.in`

---

### `/id`

**Purpose:** Show numeric Telegram IDs for user, chat, thread, or replied message.
**Input:** None (optionally reply to a message)
**Output:** User ID, chat ID, chat type, thread ID (if in topic), replied-user ID + name (if replying)
**Examples:**
- `/id` → your IDs
- Reply to a message + `/id` → also shows replied user's ID and name
- Reply to anonymous/channel message + `/id` → shows Message ID, "Anonymous / Channel"
**Errors:** None (handles all cases including None from_user)
**Related buttons:** None
**Category:** Web & Utilities (GeneralTools)
**Dependencies:** None

---

### `/info`

**Purpose:** Show Telegram profile metadata for yourself or a replied user.
**Input:** None (optionally reply to a user's message)
**Output:** First name, last name, username, ID, Premium status, entity type (HTML-formatted)
**Examples:**
- `/info` → your profile
- Reply to a message + `/info` → that user's profile
**Errors:**
- `❌ Cannot inspect this message type.` if replying to anonymous/channel post
**Related buttons:** None
**Category:** Web & Utilities (GeneralTools)
**Dependencies:** None

---

### `/uuid`

**Purpose:** Generate a cryptographically secure random UUIDv4.
**Input:** None
**Output:** UUIDv4 string (e.g. `550e8400-e29b-41d4-a716-446655440000`)
**Examples:**
- `/uuid` → `7c9e6679-7425-40de-944b-e07fc1f90ae7`
**Errors:** None
**Related buttons:** None
**Category:** Developer Tools (CryptoTools)
**Dependencies:** `app/utils/crypto.py`, stdlib `uuid`

---

### `/password [length]`

**Purpose:** Generate a high-entropy random password.
**Input:** Optional integer length (8–64, default 16)
**Output:** Password string (letters + digits + `!@#$%^&*`)
**Examples:**
- `/password` → 16-char password
- `/password 32` → 32-char password
- `/password 5` → clamped to 8-char password
**Errors:** None (invalid length falls back to default 16)
**Related buttons:** None
**Category:** Developer Tools (CryptoTools)
**Dependencies:** `app/utils/crypto.py`, stdlib `secrets`

---

### `/hash <text>`

**Purpose:** Compute MD5, SHA-256, and SHA-512 hashes of a string.
**Input:** Any text string
**Output:** Three hex digest strings (MD5, SHA-256, SHA-512)
**Examples:**
- `/hash hello` → three hash digests
**Errors:** `❌ Usage: /hash <text>` if no argument
**Related buttons:** None
**Category:** Developer Tools (CryptoTools)
**Dependencies:** `app/utils/crypto.py`, stdlib `hashlib`

---

### `/b64en <text>`

**Purpose:** Encode text to standard Base64.
**Input:** Any text string
**Output:** Base64-encoded string
**Examples:**
- `/b64en Hello World` → `SGVsbG8gV29ybGQ=`
**Errors:** `❌ Usage: /b64en <text>` if no argument
**Related buttons:** None
**Category:** Developer Tools (CryptoTools)
**Dependencies:** `app/utils/crypto.py`, stdlib `base64`

---

### `/b64de <string>`

**Purpose:** Decode a Base64 string.
**Input:** Base64-encoded string
**Output:** Decoded plain text
**Examples:**
- `/b64de SGVsbG8gV29ybGQ=` → `Hello World`
- `/b64de aGVsbG9gd29ybGQ=` → decodes to `hello\`world` — ⚠️ will show misleading error
**Errors:**
- `❌ Usage: /b64de <string>` if no argument
- `❌ Error: Invalid Base64 string payload.` on decode error **or** on `TelegramBadRequest` (misleading — can indicate valid Base64 that decoded to backtick-containing text)
**Related buttons:** None
**Category:** Developer Tools (CryptoTools)
**Dependencies:** `app/utils/crypto.py`, stdlib `base64`
**Known issue:** Valid Base64 decoding to text containing backticks shows misleading "Invalid Base64" error

---

### `/time`

**Purpose:** Return current Unix epoch timestamp.
**Input:** None
**Output:** Current Unix epoch integer
**Examples:**
- `/time` → `1700000000`
**Errors:** None
**Related buttons:** None
**Category:** Developer Tools (CryptoTools) — **UNDOCUMENTED**
**Dependencies:** `app/utils/crypto.py`, stdlib `time`
**Note:** Not in `/help`, not in any category button, not in `HELP_MANUAL_TEXT`. Functionally a subset of `/epoch` with no arguments.

---

### `/ocr`

**Purpose:** Extract text from a photo using OCR.
**Input:** Must be sent as a reply to a photo message
**Output:** Extracted text in HTML `<code>` block, or "No optical text detected."
**Examples:**
- Reply to a screenshot + `/ocr` → extracted text
**Errors:**
- `❌ Reply to an image message with /ocr.` if not a reply to photo
- `⚠️ Service is temporarily unavailable.` if both OCR providers fail (via PlatformErrorMiddleware)
**Related buttons:** None
**Category:** Media & OCR (MediaTools)
**Dependencies:** `OCRService`, `OCRSpaceProvider`, `DummyFallbackOCRProvider`, `OCR_API_KEY`, `Bot`

---

### `/short <url>`

**Purpose:** Shorten a URL using a multi-provider failover shortener.
**Input:** URL string
**Output:** Shortened URL (HTML-formatted)
**Examples:**
- `/short https://www.example.com/very/long/path?with=params` → `https://cleanuri.com/xyz`
**Errors:**
- `❌ Usage: /short <url>` if no argument
- `⚠️ Service is temporarily unavailable.` if both providers fail
**Related buttons:** None
**Category:** Web & Utilities (shown in menu) / MediaTools (actual module)
**Dependencies:** `ShortenerService`, `CleanURIProvider`, `VGdURLProvider`

---

### `/tr <lang> [text]`

**Purpose:** Translate text to a target language.
**Input:**
- Reply to a text message + `/tr <lang>` → translates replied text
- `/tr <lang> <inline text>` → translates inline text
**Output:** Translated text (HTML-formatted)
**Examples:**
- Reply to English text + `/tr hi` → Hindi translation
- `/tr es Hello, how are you?` → Spanish translation
- `/tr french Hello` → alias-resolved to `fr`
**Supported aliases:** hin/hindi, eng/english, sp/spanish, ur/urdu, fr/french, ar/arabic, ru/russian, ja/japanese, de/german
**Errors:**
- `❌ Reply to text or format: /tr <lang> <text>` if no text found
- `⏱️ Translation timed out...` on 15s timeout
- `❌ Language code 'X' is not supported.` on invalid lang
**Related buttons:** None
**Category:** Media & OCR (MediaTools)
**Dependencies:** `TranslatorService`, `deep_translator`

---

### `/qr <text_or_url>`

**Purpose:** Generate a QR code PNG image from text or a URL.
**Input:** Any text or URL string
**Output:** PNG image of QR code with content caption
**Examples:**
- `/qr https://example.com` → QR image
- `/qr Hello World` → QR encoding text
**Errors:**
- `❌ Usage: /qr <text_or_url>` if no argument
- `⚠️ Internal system error occurred.` if content exceeds QR capacity (~2953 bytes binary) — unhelpful, see known issue
**Related buttons:** None
**Category:** Media & OCR (MediaTools)
**Dependencies:** `app/utils/qr.py`, `qrcode`, `Pillow`
**Known issue:** `DataOverflowError` from qrcode library gives generic error message, no guidance to user

---

### `/qrscan`

**Purpose:** Decode a QR code from an image.
**Input:** Must be sent as a reply to a photo containing a QR code
**Output:** Decoded QR content in HTML `<code>` block, or "No QR code detected."
**Examples:**
- Reply to QR image + `/qrscan` → decoded URL or text
**Errors:**
- `❌ Reply to a QR photo message with /qrscan.` if not a reply to photo
**Related buttons:** None
**Category:** Media & OCR (MediaTools)
**Dependencies:** `app/utils/qr.py`, `pyzbar`, `Pillow`, `libzbar0` (system)

---

### `/string`

**Purpose:** Generate a Telethon StringSession credential via interactive Telegram authentication.
**Input:** None (all input via interactive buttons and messages during FSM flow)
**Output:** Telethon StringSession string in backtick code block (base64-like, ~350 chars)
**Flow:**
1. `/string` → method selection keyboard (QR / OTP / Cancel)
2a. QR: → QR code PNG → scan → auto-refresh → session string
2b. OTP: → phone number → code → optional 2FA password → session string
**Errors:**
- Credential missing: error shown before flow starts
- FloodWaitError: handled with wait message
- PhoneCodeExpiredError: handled, QR fallback offered
- AuthRestartError: handled at send_code and sign_in
- 120s global timeout
**Related buttons:** `ses_method_qr`, `ses_method_otp`, `ses_qr_refresh`, `ses_otp_resend`, `ses_start_qr`, `ses_cancel`
**Category:** Telegram Authentication (session — FROZEN)
**Dependencies:** `Telethon`, `API_ID`/`API_HASH` env, `qrcode`, `Pillow`, `StringSessionState` FSM

---

### `/create_session`

**Purpose:** Authenticate via Telegram and export a SQLite `.session` file.
**Input:** None (interactive flow)
**Output:** SQLite `.session` file sent as Telegram document
**Flow:** Same as `/string` but delivers `.session` file instead of string
**Errors:** Same auth errors as `/string` + file delivery errors
**Related buttons:** `sm_create`, `sm_method_qr`, `sm_method_otp`, `sm_qr_refresh`, `sm_cancel`
**Category:** Session Manager (session_manager)
**Dependencies:** `Telethon`, `API_ID`/`API_HASH`, `CreateSessionState` FSM, `tempfile`

---

### `/login_session`

**Purpose:** Validate an uploaded Telethon `.session` file and display account information.
**Input:** `.session` file uploaded as Telegram document (max 512 KB)
**Output:** Account summary (name, username, ID, tier, type) or validation error
**Flow:**
1. `/login_session` → upload prompt
2. User sends `.session` file
3. Bot validates, shows account info
**Errors:**
- `❌ Please upload a .session file as a document attachment.` if no file
- `❌ Only .session files are accepted.` if wrong extension
- `❌ Session is not authorized.` if session exists but logged out
- `❌ Invalid session file.` if not a valid Telethon session
- `❌ Invalid or corrupt session file.` on other Telethon errors
**Related buttons:** `sm_login`, `lsess_cancel`
**Category:** Session Manager (session_manager)
**Dependencies:** `Telethon`, `API_ID`/`API_HASH`, `LoginSessionState` FSM, `tempfile`
**Known issue:** Account name/username displayed in Markdown mode without html.escape() — rendering bug for names with `_` or `*`

---

### `/diag`

**Purpose:** Display platform diagnostics. Admin only.
**Input:** None
**Output:** Feature count, HTTP pool status, RAM (MB), CPU%, uptime (Markdown)
**Examples:** `/diag` (only works if sender's ID matches `ADMIN_ID` env var)
**Errors:** Silent non-match for non-admins (no error reply)
**Related buttons:** None
**Category:** System / Admin (AdminControl)
**Dependencies:** `psutil`, `CapabilityRegistry`, `bootstrap_ref`

---

### `/health` (Telegram command)

**Purpose:** Quick health check via Telegram message. Admin only.
**Input:** None
**Output:** Operational/Degraded status, RAM, HTTP client status
**Examples:** `/health` (admin only)
**Errors:** Silent non-match for non-admins
**Related buttons:** None
**Category:** System / Admin (AdminControl)
**Dependencies:** `psutil`, `bootstrap_ref`
**Note:** Distinct from the HTTP `GET /health` route

---

## Button-Only Features (no direct command)

| Button | Callback | What it does |
|---|---|---|
| 🛠️ Developer Tools | `cat_dev` | Shows dev/crypto command list |
| 🔑 String Session | `cat_session` | Shows /string usage (stale text) |
| 📸 Media & OCR | `cat_media` | Shows media command list |
| 🌐 Web & Utilities | `cat_web` | Shows network command list |
| 🔐 Session Manager | `cat_session_mgr` | Shows create/login sub-menu |
| 📘 Full Manual | `menu_help` | Shows HELP_MANUAL_TEXT inline |
| 🔙 Back to Main Menu | `back_main` | Returns to /start main menu |

---

## Internal Handlers (no direct user invocation)

| Handler | Callback/State | Module | Purpose |
|---|---|---|---|
| `cb_method_qr` | `ses_method_qr` | session | Start QR flow in /string |
| `cb_method_otp` | `ses_method_otp` | session | Start OTP flow in /string |
| `cb_qr_refresh` | `ses_qr_refresh` | session | Refresh QR code in /string |
| `cb_otp_resend` | `ses_otp_resend` | session | Resend OTP code (one-shot) |
| `cb_start_qr_from_otp` | `ses_start_qr` | session | Switch OTP→QR mid-flow |
| `cb_cancel` | `ses_cancel` | session | Cancel /string flow |
| `handle_session_mgr_cat` | `cat_session_mgr` | session_manager | Show SM sub-menu |
| `cb_sm_create` | `sm_create` | session_manager | Start create_session flow |
| `cb_sm_login` | `sm_login` | session_manager | Start login_session flow |
| `cb_sm_method_qr` | `sm_method_qr` | session_manager | Start QR flow in create_session |
| `cb_sm_method_otp` | `sm_method_otp` | session_manager | Start OTP flow in create_session |
| `cb_sm_qr_refresh` | `sm_qr_refresh` | session_manager | Refresh QR in create_session |
| `cb_sm_cancel` | `sm_cancel` | session_manager | Cancel create_session flow |
| `cb_lsess_cancel` | `lsess_cancel` | session_manager | Cancel login_session flow |
| `ls_recv_file` | State: LoginSessionState.waiting_for_file | session_manager | Receive and validate .session file |

---

## HTTP Routes

| Method | Path | Handler | Returns |
|---|---|---|---|
| GET | `/health/live` | `liveness_handler` | 200 `{"status":"alive"}` always |
| GET | `/health/ready` | `readiness_handler` | 200/503 based on live bot_task + http_session |
| GET | `/health` | `health_check_handler` | Alias for `/health/ready` |
