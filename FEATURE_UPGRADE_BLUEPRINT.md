# FEATURE_UPGRADE_BLUEPRINT.md
# Shade Utility Platform V8 — Feature Upgrade Blueprint
> PLANNING DOCUMENT ONLY. No implementation. Every "current" description verified from source.
> Every "future" item is a blueprint, not a commitment.

---

## How to Read This Document

Each feature is analyzed across four upgrade levels:
- **Level 1** — Small, safe, high-confidence improvements. Low risk.
- **Level 2** — Meaningful new capability. Moderate risk. Requires testing.
- **Level 3** — Powerful/professional functionality. Higher complexity.
- **Maximum** — Realistic ceiling without becoming a different product.

**Recommendation tiers:**
- ✅ Worth doing
- 🟡 Optional / situational
- ❌ Avoid (complexity/risk not justified)

---

# FEATURE GROUP 1: Developer / Crypto Utilities

## /epoch — Timestamp Converter

### Current Capability
No-arg: current epoch + UTC. With integer: converts to date. With ISO date: converts to epoch. Bidirectional, stdlib only.

### Level 1 ✅
- Fix `datetime.utcfromtimestamp()` deprecation (use `datetime.fromtimestamp(ts, tz=timezone.utc)`)
- Add `/epoch` to the Developer Tools category button description
- Consistent output format using MarkdownV2 or HTML instead of Markdown

### Level 2 ✅
- Support timezone parameter: `/epoch 1700000000 America/New_York`
- Support relative time output: "2 days ago", "in 3 hours"
- Support multiple input formats: `/epoch 2024-01-15 14:30:00`
- Add duration math: `/epoch 1700000000 1700086400` → difference in days/hours/minutes

### Level 3 🟡
- Multi-format output table: Unix, ISO 8601, RFC 2822, human-readable
- Time zone conversion table for common zones
- Calendar week / day-of-year calculation

### Maximum Practical Capability
A complete timestamp utility: convert any representation to any other, with timezone awareness, relative time, and duration arithmetic. Stays within stdlib (`datetime`, `zoneinfo`). No external API needed.

### New Dependencies
- Level 1: None (stdlib `datetime.timezone`)
- Level 2+: stdlib `zoneinfo` (Python 3.9+ standard)

### Performance Cost
CPU: Negligible | RAM: None | Network: None | Storage: None | Concurrency: None

### Security Risks
None — pure stdlib date manipulation, no user-supplied code execution.

### Failure Scenarios
- Invalid timezone string → catch `ZoneInfoNotFoundError`
- Overflow for year values outside 1–9999 → catch `OverflowError`

### Solutions
Wrap all conversions in try/except. Return user-friendly error messages.

### Complexity: Low

### Recommendation: ✅ Level 1+2 worth doing. Level 3 optional.

---

## /hash — Hashing

### Current Capability
MD5 + SHA-256 + SHA-512 of text input. Simultaneous. Stdlib only.

### Level 1 ✅
- Switch output to `parse_mode="HTML"` to eliminate any Markdown risk (hex chars are safe, but consistency matters)
- Add BLAKE2b (stdlib `hashlib.blake2b`)
- Add SHA-3 variants (stdlib: `hashlib.sha3_256`, `hashlib.sha3_512`)

### Level 2 ✅
- Accept file input: reply to a document with `/hash` → hash the file bytes
- Add HMAC mode: `/hash hmac <key> <text>` with selectable algorithm
- Add checksum comparison: `/hash <algo> <expected> <text>` → ✅/❌

### Level 3 🟡
- Hash a URL (fetch content, then hash) — requires SSRF guard applied
- Side-by-side comparison table for multiple algorithms
- Argon2/bcrypt estimation for password hashing (show cost, not hash — bcrypt is slow)

### Maximum Practical Capability
A complete hashing toolkit: text, files, URLs (SSRF-guarded), HMAC, comparison, multiple algorithms including modern (BLAKE2, SHA-3). All within stdlib except Argon2.

### New Dependencies
- Level 1–2: None (all stdlib `hashlib`)
- Level 3: `argon2-cffi` if Argon2 is added

### Performance Cost
CPU: File hashing could be slow for large files (hash in chunks)
RAM: File fully buffered if from Telegram (max 20 MB for bots via Bot API, 2 GB via MTProto)
Network: None for text; one Telegram download for file mode
Concurrency: No issue for text; file downloads block handler if not streamed

### Security Risks
- File hashing: Telegram bot file size limit is 20 MB. Hash computation on large files in RAM is safe but slow.
- URL hashing: Must apply `is_safe_host()` SSRF guard before fetching.

### Failure Scenarios
- Unsupported algorithm string → catch `ValueError` from `hashlib.new()`
- File too large → Telegram's own size limit prevents download

### Solutions
Validate algorithm name against `hashlib.algorithms_available`. Apply SSRF guard for URL mode.

### Complexity: Low (Level 1–2), Medium (Level 3)

### Recommendation: ✅ Level 1–2. Level 3 optional.

---

## /password — Password Generator

### Current Capability
Entropy password, 8–64 chars, fixed charset (letters+digits+`!@#$%^&*`). Uses `secrets`.

### Level 1 ✅
- Add passphrase mode: `/password phrase` → 4 random words (EFF wordlist)
- Expose charset control: `/password 20 symbols` (extra symbols), `/password 20 alpha` (letters only)
- Show entropy bits alongside password

### Level 2 ✅
- Generate multiple passwords at once: `/password 5` → 5 passwords, one per line
- PIN mode: `/password pin 6` → 6-digit numeric PIN
- Pronounceable password: alternating consonant/vowel pattern

### Level 3 🟡
- Integration with a local wordlist for memorable passphrases
- Export as QR code (combines with /qr feature)
- Password policy checker: given a policy (min length, required chars), generate conforming password

### Maximum Practical Capability
A complete credential generation suite: entropy passwords, passphrases, PINs, bulk generation, entropy display, policy-conforming generation. All within stdlib `secrets` + local wordlist.

### New Dependencies
- Level 1–2: None (stdlib `secrets`, optional local wordlist file)
- Level 3: Local EFF wordlist (static file, no network)

### Performance Cost
All: CPU negligible, RAM negligible, no network.

### Security Risks
None — uses `secrets` module (CSPRNG). Output visible in Telegram chat (inherent limitation).

### Failure Scenarios
- User requests bulk (100 passwords) → large message, may hit Telegram's 4096 char limit
- Solution: Cap bulk at 10 passwords per call

### Complexity: Low

### Recommendation: ✅ Level 1–2 worth doing.

---

## /b64en / /b64de — Base64

### Current Capability
Standard Base64 encode/decode. `parse_mode="Markdown"`. `/b64de` has misleading error on backtick-containing decoded output.

### Level 1 ✅ (P2 fix)
- **Critical:** Switch `/b64de` and `/b64en` to `parse_mode="HTML"` + `html.escape()`. Eliminates Markdown rendering bug. This is a bug fix, not an upgrade.
- Add URL-safe Base64 variant: `/b64en url <text>` / `/b64de url <string>`

### Level 2 ✅
- Add binary mode: reply to a document with `/b64en` → Base64 of file bytes
- Detect and display encoding: when decoding, show if result is valid UTF-8, latin-1, or binary
- Add Base32 and Base85 variants: `/b64en 32 <text>`

### Level 3 🟡
- Multi-line / chunked decode for very long Base64 strings
- File mode: reply to Base64 text file → decode and send as document

### Maximum Practical Capability
Complete encoding toolkit: Base16/32/64/85, URL-safe variants, file encode/decode, auto-charset detection on decode. All stdlib.

### New Dependencies
- None (all stdlib `base64`)

### Performance Cost
File encoding/decoding: RAM proportional to file size (up to 20 MB via Bot API).

### Security Risks
Decoded content is arbitrary bytes. Displaying arbitrary bytes in Telegram chat is inherently risky for Markdown mode (resolved by switching to HTML+escape). No code execution risk.

### Failure Scenarios
- Non-UTF-8 decoded output: show hex preview or "binary content, cannot display"
- Solution: try UTF-8 decode, fall back to `repr()` or hex truncation

### Complexity: Low (Level 1), Medium (Level 2+)

### Recommendation: ✅ Level 1 is a bug fix that must be done. Level 2 optional.

---

## /uuid — UUID Generator

### Current Capability
Single UUIDv4 per call.

### Level 1 ✅
- Bulk mode: `/uuid 5` → 5 UUIDs
- Nil UUID display: `/uuid nil` → `00000000-0000-0000-0000-000000000000`

### Level 2 🟡
- UUIDv3/v5 (namespace + name): `/uuid v5 url https://example.com`
- ULID generation (time-sorted UUID alternative, requires `python-ulid`)
- UUID inspection: `/uuid info <uuid>` → parse version, variant, timestamp (for v1)

### Level 3 ❌
- UUID database/storage: not appropriate for a stateless utility bot

### Maximum Practical Capability
Multi-version UUID generation with bulk support and UUID parsing/inspection. Simple, self-contained.

### New Dependencies
- Level 1: None (stdlib `uuid`)
- Level 2: `python-ulid` for ULID (optional, ~5 KB package)

### Complexity: Low

### Recommendation: ✅ Level 1. Level 2 optional.

---

# FEATURE GROUP 2: Security Utilities

## /checkpwd — Password Strength

### Current Capability
5-point heuristic: length, mixed case, digits, symbols → Weak/Moderate/Strong/Very Strong.

### Level 1 ✅
- Show score breakdown: which criteria passed/failed
- Add minimum entropy calculation (log2(charset_size^length))

### Level 2 ✅
- zxcvbn-style scoring: dictionary check, pattern detection (dates, keyboard walks)
- Estimated crack time at different attack speeds (offline fast hash, offline slow hash)
- Common password list check: compare against top-10,000 passwords (local list)

### Level 3 🟡
- HaveIBeenPwned k-anonymity API: send SHA-1 prefix, check if hash appears in breach database
  - Hash first 5 chars of SHA-1, send to `api.pwnedpasswords.com/range/{prefix}`
  - Parse response for full hash suffix match
  - **Requires network call to external API**

### Maximum Practical Capability
Real-world password strength assessment: entropy, pattern detection, common-password check, and optional breach database lookup (k-anonymity, never sends full hash). Would be genuinely useful.

### New Dependencies
- Level 2: `zxcvbn` Python package, or implement subset locally
- Level 3: `api.pwnedpasswords.com` (no auth required, k-anonymity model, safe)

### Performance Cost
Level 1–2: CPU only (dictionary lookup is fast with a set)
Level 3: One HTTPS call to pwnedpasswords.com (15s timeout)

### Security Risks
- **Level 3:** Password hash prefix (first 5 chars of SHA-1) sent to external API. k-anonymity model means the full password or full hash is never transmitted. Mathematically safe but users may not understand this.
- Password still visible in Telegram chat (inherent, can't fix).

### Failure Scenarios
- Level 3: pwnedpasswords.com down → degrade gracefully (show "breach check unavailable")

### Solutions
Make breach check opt-in: `/checkpwd <password> --pwned`. Show clear explanation of k-anonymity.

### Complexity: Low (Level 1), Medium (Level 2–3)

### Recommendation: ✅ Level 1–2 worth doing. Level 3 requires user education messaging.

---

# FEATURE GROUP 3: Network Utilities

## /ip — IP Geo-Lookup

### Current Capability
ip-api.com (HTTP, free tier). One request, no retry, no cache. Shows country/city/ISP/timezone.

### Level 1 ✅
- Switch to HTTPS tier (requires paid ip-api.com key, or switch to a free HTTPS provider)
- Add retry on timeout (1 retry with 2s delay)
- Add basic response caching (TTL 300s per IP) — prevents duplicate lookups

### Level 2 ✅
- Multi-field display: ASN, organization, is_proxy flag, is_hosting flag, is_mobile flag
- Reverse DNS lookup: show PTR record alongside geo data
- Batch mode: `/ip 8.8.8.8 1.1.1.1 9.9.9.9` → three cards
- Add ASN lookup: `/ip asn AS15169` → ASN details

### Level 3 🟡
- Multiple provider failover (ip-api.com → ipinfo.io → MaxMind GeoLite2 local db)
- Port scan via public API (e.g. Shodan free tier) — requires API key
- Whois lookup: `/ip whois 8.8.8.8` → registration info

### Maximum Practical Capability
A complete IP intelligence toolkit: geo-location, ASN, reverse DNS, proxy detection, Whois, failover across providers, response caching. All with SSRF guard maintained.

### New Dependencies
- Level 1: `cachetools.TTLCache` (already in requirements, currently unused)
- Level 2: `dnspython` for PTR records
- Level 3: `shodan` SDK or raw aiohttp to Shodan API

### Performance Cost
CPU: Negligible
RAM: TTLCache adds small fixed overhead
Network: Multiple providers in parallel possible
Storage: None (in-memory cache only)
Concurrency: Cache is not thread-safe without locks (see Circuit Breaker note)

### Security Risks
- SSRF guard must remain for user-supplied IP/domain (currently verified correct)
- Shodan API key would be another secret to manage
- DNS PTR lookups must use a safe DNS resolver (not user-controlled)

### Failure Scenarios
- Provider down → failover (already implemented pattern via ProviderFailoverEngine)
- Cache poisoning → impossible with TTLCache on immutable IP keys
- PTR spoofing → not a risk (display only, not trusted for security decisions)

### Solutions
Apply existing ProviderFailoverEngine pattern. Use `cachetools.TTLCache` (already in requirements).

### Complexity: Low (Level 1), Medium (Level 2), High (Level 3)

### Recommendation: ✅ Level 1 (switch to HTTPS + cache). Level 2 useful. Level 3 situational.

---

## /weather — Weather

### Current Capability
wttr.in JSON API. Current conditions only. One city at a time.

### Level 1 ✅
- Unit selection: `/weather London C` (Celsius) or `/weather London F` (Fahrenheit) — wttr.in supports both
- Better "city not found" error (wttr.in sometimes returns data for wrong city)
- Add input normalization (strip extra spaces, handle city+country: `London, UK`)

### Level 2 ✅
- Multi-day forecast: `/weather London 3` → 3-day forecast (wttr.in supports `?format=j1` with daily data)
- UV index, sunrise/sunset, moon phase (all available in wttr.in response)
- Add wind direction (currently shows speed only)

### Level 3 🟡
- Multiple provider failover (wttr.in → OpenWeatherMap free tier)
- Persistent weather subscription (would require database — major architecture addition)

### Maximum Practical Capability
Current conditions + 3-day forecast with extended data (UV, wind direction, sunrise/sunset, moon). All available from wttr.in without API key changes.

### New Dependencies
- Level 1–2: None (wttr.in already used, response has all needed fields)
- Level 3: `openweathermap` API key for fallback

### Performance Cost
Level 1–2: Same as current (single wttr.in request)

### Security Risks
City name is already `quote_plus`-encoded and used in a hardcoded URL pattern. No SSRF risk (URL is not user-controlled).

### Failure Scenarios
- wttr.in schema change → update field parsing
- City ambiguity → wttr.in returns best-guess city; add "showing results for {city}" confirmation

### Complexity: Low

### Recommendation: ✅ Level 1–2 easy wins. Level 3 only if wttr.in reliability proves insufficient.

---

# FEATURE GROUP 4: URL Utilities

## /short — URL Shortener

### Current Capability
Two-provider failover (CleanURI → v.gd). HTML output. Category mismatch (media module, web menu).

### Level 1 ✅
- Fix category placement: move `/short` to a URL/Web module (separate from MediaTools)
- Add input validation: check URL starts with `http://` or `https://` before sending to providers
- Show which provider was used ("Shortened via CleanURI")

### Level 2 ✅
- Add preview/expand mode: `/short expand <short_url>` → show where a short URL leads (HEAD request with redirect follow)
  - Apply SSRF guard before expanding
  - Show final destination domain, do not fetch content
- Add third provider for additional redundancy

### Level 3 🟡
- Custom short link (requires a self-hosted shortener or paid API — significant infra addition)
- Click tracking (requires database — major architecture addition)
- QR code of shortened URL (combines /short + /qr)

### Maximum Practical Capability
Reliable URL shortening with 3-provider failover, input validation, expand/preview mode, and composability with QR generation.

### New Dependencies
- Level 1–2: None
- Level 3: Database (if click tracking), self-hosted shortener

### Performance Cost
Level 1–2: Same as current (provider HTTP calls)

### Security Risks
- Expand mode: Must apply `is_safe_host()` SSRF guard to target URL before any fetch
- Short URL content is user-controlled. Never fetch or render the destination content — only show the destination domain

### Failure Scenarios
- Expand redirect loop → cap redirect follows at 5
- Expand to private IP → blocked by SSRF guard

### Solutions
Reuse existing `is_safe_host()`. Use HEAD requests only (no content download).

### Complexity: Low (Level 1), Medium (Level 2)

### Recommendation: ✅ Level 1 (fix category + validation). Level 2 expand mode is genuinely useful.

---

# FEATURE GROUP 5: Media / OCR Utilities

## /ocr — Optical Character Recognition

### Current Capability
OCRSpace API via ProviderFailoverEngine. DummyFallback (empty string). Photo must be replied-to.

### Level 1 ✅
- Add language hint: `/ocr en`, `/ocr ar` — pass language to OCRSpace API
- Improve fallback: DummyFallback shows "OCR service temporarily unavailable" instead of empty string
- Show character count in output

### Level 2 ✅
- Add Tesseract as local fallback provider: install `tesseract-ocr` + `pytesseract`
  - Pure local fallback, no API key, no external call
  - Would replace DummyFallback as meaningful second tier
- Support document photos (improve preprocessing with Pillow: grayscale, threshold)

### Level 3 🟡
- PDF OCR: reply to a PDF document + `/ocr` → extract text from all pages
- Multi-page document support
- Table extraction mode (OCRSpace supports structured table output)

### Maximum Practical Capability
Multi-tier OCR: OCRSpace (primary, cloud) → Tesseract (local fallback, always available) → "unavailable" (last resort). Language-hinted, with PDF support.

### New Dependencies
- Level 2: `tesseract-ocr` (system package), `pytesseract` (Python), `Pillow` (already present)
- Level 3: `pdf2image`, `poppler-utils` (system)
- Dockerfile additions for Level 2: `apt-get install tesseract-ocr`

### Performance Cost
CPU: Tesseract is CPU-heavy for large images (seconds, not milliseconds)
RAM: Pillow preprocessing of 20 MB image could use 60–100 MB transiently
Network: Level 2 eliminates external call for fallback path
Storage: None

### Security Risks
- Tesseract subprocess: `pytesseract.image_to_string()` shells out to `tesseract`. The image comes from Telegram's servers — the actual pixel data, not a user-controlled path. No shell injection risk.
- PDF processing: `pdf2image` shells out to `pdftoppm`. Malformed PDFs could potentially crash the conversion. Wrap in try/except.

### Failure Scenarios
- Tesseract OOM on huge image → wrap in asyncio.wait_for() with timeout
- PDF with many pages → add page limit (e.g. first 5 pages only)

### Complexity: Low (Level 1), Medium (Level 2), High (Level 3)

### Recommendation: ✅ Level 1 (easy wins). Level 2 strongly recommended (eliminates empty-string fallback). Level 3 situational.

---

## /qr — QR Code Generator

### Current Capability
Generates PNG QR code. DataOverflowError gives generic error.

### Level 1 ✅
- Catch `qrcode.exceptions.DataOverflowError` in `generate_qr_buffer()` — show helpful message: "Content too large for QR code. Max ~2953 bytes."
- Switch caption to already-used HTML mode for consistency

### Level 2 ✅
- Error correction level selection: `/qr L`, `/qr M`, `/qr Q`, `/qr H` (L=7%, M=15%, Q=25%, H=30%)
- Custom colors: `/qr blue <text>` — dark module color (Pillow supports this)
- Size control: `/qr large <text>` → larger box_size parameter
- Output both QR and shortened URL: `/qr short <url>` → shorten then QR

### Level 3 🟡
- Logo embedding: place a small image in QR center (requires PIL paste operation)
- Styled QR (rounded modules, gradient) — `qrcode[pil]` or `segno` library
- WiFi QR: `/qr wifi SSID PASSWORD` → generates `WIFI:S:SSID;T:WPA;P:PASSWORD;;` encoded QR

### Maximum Practical Capability
Configurable QR with error correction levels, colors, sizes, WiFi shortcuts, and logo embedding. All local (no external API).

### New Dependencies
- Level 1–2: None (`qrcode` + `Pillow` already present)
- Level 3: `segno` for styled QR (optional)

### Performance Cost
CPU: Logo embedding and styling add minor overhead
RAM: Slightly larger PNG output
Network: None (all local)

### Security Risks
- WiFi QR: password embedded in QR data. Password is visible in the QR and in the command text. Warn user.
- Logo embedding: if logo comes from a user-supplied URL, apply SSRF guard before fetching.

### Failure Scenarios
- Level 1: DataOverflowError now caught with helpful message ✅
- Logo URL fetch fails → fall back to QR without logo

### Complexity: Low (Level 1), Low-Medium (Level 2)

### Recommendation: ✅ Level 1 (bug fix). Level 2 useful. Level 3 optional.

---

## /qrscan — QR Code Decoder

### Current Capability
Decodes first QR code from image. pyzbar. Returns decoded text.

### Level 1 ✅
- Add barcode support (pyzbar already supports EAN-13, UPC, Code128, etc. — just show type)
- Show QR code type/format in output

### Level 2 ✅
- Multi-QR: decode all QR codes found in image (pyzbar returns a list — current code only takes `[0]`)
- Auto-detect and classify output: URL, WiFi config, vCard, plain text
- For URL outputs: show SSRF-safe domain preview ("Points to: example.com")

### Level 3 🟡
- Image preprocessing for better decode rates: grayscale, adaptive threshold, rotation attempts
- PDF support: extract QR codes from PDF pages

### Maximum Practical Capability
Multi-QR and multi-barcode decoder with content classification and image preprocessing. All local.

### New Dependencies
- Level 1–2: None (`pyzbar` + `Pillow` already present)
- Level 3: `pypdf2` or `pdf2image` for PDF mode

### Security Risks
- Decoded URL classification: never fetch the URL — only parse and display the domain. Apply SSRF guard check as a warning display (not as a fetch).
- Decoded WiFi credentials: shown in chat, user-facing only. No risk.

### Complexity: Low (Level 1–2)

### Recommendation: ✅ Level 1–2 easy wins (pyzbar already returns full list and type info).

---

## /tr — Translation

### Current Capability
deep_translator (unofficial Google Translate). Auto-detect source. 8 pre-aliased languages. 15s timeout in executor.

### Level 1 ✅
- Expand language alias list (currently 8 aliases — add more common ones)
- Show detected source language in output: "Detected: English → Hindi"
- Better error message for unsupported language codes

### Level 2 ✅
- Switch to official LibreTranslate (self-hosted) or DeepL free tier API for reliability
  - LibreTranslate: open source, can be self-hosted, has official Python client
  - DeepL: free tier (500K chars/month), official API, reliable
- Language detection only mode: `/tr detect <text>` → "Detected: Spanish (es)"
- Multi-language output: `/tr en+fr+de <text>` → translate to three languages at once

### Level 3 🟡
- Reply-to-message language detection (identify what language a message is in without translating)
- Glossary support (DeepL supports custom terminology glossaries)

### Maximum Practical Capability
Reliable translation with official API, auto-detection display, multi-target, and language identification. Requires API key for DeepL or self-hosted LibreTranslate.

### New Dependencies
- Level 1: None (deep_translator already present)
- Level 2: `deepl` SDK or `libretranslate` client, or raw aiohttp + API key

### Performance Cost
Level 2 (official API): Similar to current — network-bound, executor pattern maintained

### Security Risks
- DeepL API key: another secret to manage
- LibreTranslate self-hosted: infrastructure overhead
- Multi-language output: rate limit risk for 3+ simultaneous API calls

### Failure Scenarios
- Official API rate limit → ProviderFailoverEngine pattern (official → unofficial fallback)
- Multi-language: one fails, others succeed → partial result

### Solutions
Apply existing ProviderFailoverEngine pattern to translation providers.

### Complexity: Low (Level 1), Medium (Level 2)

### Recommendation: ✅ Level 1. Level 2 strongly recommended if `deep_translator` reliability proves insufficient.

---

# FEATURE GROUP 6: Telegram Authentication

## /string — StringSession Generator (FROZEN)

### Current Capability
Full QR+OTP+2FA Telethon auth → StringSession string. FROZEN.

### ⚠️ FROZEN — NO CHANGES

The existing implementation is complete, tested, and working. It should not be modified.

If a new capability is needed (e.g., different output format, different auth flow, different credential scope), **create a new module** following the isolation pattern of `session_manager`.

### What Could Be Added in a NEW Module (not modifying /string)

- `/pyrogram_session` — generate a Pyrogram `StringSession` (different format, same auth flow)
- `/telethon_session_v2` — generate session with specific API layer pinned
- Any new auth flow should be a separate module with separate FSM, separate dict, separate prefix

### Recommendation: ❌ Do not modify. ✅ New modules follow the isolation pattern.

---

# FEATURE GROUP 7: Session Manager

## /create_session — SQLite Session Creator

### Current Capability
Auth flow (QR+OTP) → SQLite `.session` file sent as document. Known issue: account name in Markdown mode without escaping.

### Level 1 ✅ (bug fix)
- Fix account name display: switch to `parse_mode="HTML"` + `html.escape()` on `full_name` and `uname`
- Show delivery confirmation: "Session file delivered. Delete this message after saving."
- Show session expiry info: SQLite sessions are long-lived; inform user.

### Level 2 ✅
- Session metadata in delivery message: account ID, creation timestamp, API layer version
- Offer to also send the session as a StringSession (for scripts that prefer string format)
- Validation step before delivery: verify the session actually works (do `get_me()` before send)

### Level 3 🟡
- Multiple API_ID/API_HASH configurations: allow users to supply their own credentials for the session (requires per-user credential input flow — significant security review needed)
- Session re-authentication: `/refresh_session` — accepts expired session, prompts reauth, returns refreshed session

### Maximum Practical Capability
Reliable session generation with metadata, validation-before-delivery, and dual output (SQLite + StringSession). Stays within current auth architecture.

### New Dependencies
Level 1–2: None

### Security Risks
- Level 3 (user-supplied credentials): Users providing `API_ID`/`API_HASH` creates new attack surface. These credentials could be malicious (rate-abusing bots, spam). Requires per-user credential validation.

### Complexity: Low (Level 1), Low-Medium (Level 2), High (Level 3)

### Recommendation: ✅ Level 1 (bug fix). ✅ Level 2. ❌ Level 3 unless clear use case.

---

## /login_session — Session Validator

### Current Capability
Upload `.session` → validate via get_me() → show account info. Known issues: Markdown rendering on account names.

### Level 1 ✅ (bug fix)
- Fix account name display: switch to `parse_mode="HTML"` + `html.escape()`
- Add session info: show authorized scopes/permissions if available via Telethon

### Level 2 ✅
- Session health check: verify the session can perform basic operations (get_me + get_dialogs(1))
- Show session metadata: creation date if stored in SQLite, phone hash, dc_id
- Session export: `/login_session` → validate → offer StringSession export option

### Level 3 🟡
- Session revocation: connect with session, call `Log Out()` to revoke it — then confirm
- Batch validation: accept multiple session files (zip archive)

### Maximum Practical Capability
Full session lifecycle tool: validate, inspect, export to different format, optionally revoke.

### New Dependencies
Level 1–2: None

### Complexity: Low (Level 1), Medium (Level 2)

### Recommendation: ✅ Level 1 (bug fix). Level 2 adds real value.

---

# FEATURE GROUP 8: Admin / Diagnostics

## /diag and /health (Admin)

### Current Capability
`/diag`: feature count, HTTP status, RAM, CPU%, uptime.
`/health`: operational status, RAM, HTTP status.

### Level 1 ✅
- Add active Telethon session count from `ACTIVE_CLIENTS` and `CS_ACTIVE`
- CPU reading: use `interval=0.1` instead of `None` for a non-zero reading
- Show `degraded_features` list if any

### Level 2 ✅
- Show provider circuit breaker states: which providers are OPEN/HALF_OPEN/CLOSED
- Show per-feature `is_enabled()` status from CapabilityRegistry
- Add `/diag reset` to reset all circuit breakers (admin action)
- Wire `metrics.api_failures` counter — show in diag output

### Level 3 🟡
- Periodic background health task that logs platform state every N minutes
- Auto-alert to admin Telegram ID if polling task dies

### Maximum Practical Capability
Full operational dashboard: CPU/RAM, feature status, circuit breaker states, active session counts, API failure metrics, auto-alerting. All within existing psutil + internal state.

### New Dependencies
Level 1–2: None

### Complexity: Low (Level 1–2)

### Recommendation: ✅ Level 1–2. Level 3 requires background task — add to roadmap later.
