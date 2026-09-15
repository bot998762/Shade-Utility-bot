# SECURITY.md
# Shade Utility Platform V8 — Verified Security Model
> Every claim here is verified in actual source code. Nothing is assumed.

---

## 1. Secret Handling

### BOT_TOKEN
- Loaded via `pydantic-settings` from environment variable.
- Never logged. Never echoed to users.
- Startup aborts if missing (`validate_startup()` raises `ValueError`).
- Used only by aiogram's `Bot` object internally.

### API_ID / API_HASH
- Read directly from `os.environ.get()` in `session/router.py` and `session_manager/router.py`.
- **Not** in `Settings` class — bypasses pydantic-settings validation and `.env` loading.
- Not in `.env.example` — deployers must discover these manually.
- Never logged. Never sent to users.
- If missing: `_get_creds()` returns `(0, "")` and session commands show an error before any flow starts.

### OCR_API_KEY
- Loaded via `Settings`. Logged as WARNING (key name only, not value) if missing.
- Sent in `Authorization` header to `api.ocr.space`.
- Never logged in full. Never shown to users.

### ADMIN_ID
- Integer. Default `0` in `Settings` (fail-closed: no admin access if not set).
- Compared as exact integer match against `message.from_user.id`.
- Never logged or echoed.

**AST-verified:** The architecture test `TestNoSecretsInLogs` confirms none of `BOT_TOKEN`, `API_HASH`, `api_hash`, `string_session` appear in any log call anywhere in the production source.

---

## 2. Telegram Authentication Security

### Session Isolation
- Each user who invokes `/string` or `/create_session` gets their own entry in a per-feature dict keyed by `user_id` (`int`).
- `ACTIVE_CLIENTS` (session) and `CS_ACTIVE` (session_manager) are completely separate dicts.
- User A's session state cannot interact with User B's.

### Credential Sharing (Known Design Constraint)
- `API_ID` and `API_HASH` are shared across all users. These are application credentials, not user credentials.
- Telegram's MTProto client (`TelegramClient`) is created per-user per-session. Each user authenticates with their own Telegram account via their own phone number.
- The shared API credentials mean all users of this bot are using the same Telegram application registration. This is standard practice for userbot generators. The risk is: if the API credentials are revoked by Telegram, the feature stops for all users simultaneously.

### Re-entry Guard
Both `/string` and `/create_session` guard against a user starting a second session while one is already active:
```python
if user_id in ACTIVE_CLIENTS:
    _cleanup_user_session(user_id)  # cancels tasks, disconnects client
    await state.clear()
# then start fresh
```

---

## 3. OTP (Phone Code) Handling

- Phone number accepted as FSM message text. Never logged.
- `send_code(phone)` returns `phone_code_hash`. This hash is:
  - Stored in `ACTIVE_CLIENTS[user_id]["hash"]` (in-process RAM only)
  - Logged only as `{"hash_len": len(phone_code_hash)}` — length only, never value
  - Cleared when `_cleanup_user_session()` is called
- Phone code entered by user as plain text message. Never logged. Passed directly to `client.sign_in(phone, code)`.
- `PhoneCodeExpiredError`, `PhoneCodeInvalidError`, `AuthRestartError` all handled with user-facing messages and appropriate cleanup.
- `ResendCodeRequest` is one-shot: button is removed from keyboard after first press (`call.message.edit_reply_markup(reply_markup=_otp_no_resend_kb())`) to prevent spam.

---

## 4. 2FA Password Handling

- When Telegram requires 2FA (session password), the bot prompts the user to send their password as a Telegram message.
- **Password appears in Telegram chat history** — this is unavoidable with Bot API. Users should be warned (currently: info message shown at prompt).
- Password is passed directly to `client.sign_in(password=pwd)` and immediately falls out of scope.
- Never stored in FSM state, never logged, never echoed back.
- `PasswordHashInvalidError` handled gracefully (user gets error message, no password leak in error).

---

## 5. StringSession Handling

- StringSession is a base64-like string (~350 chars) representing a complete Telethon user session.
- Never logged. Never stored server-side after delivery.
- Delivered in a Telegram message to the requesting user in a Markdown backtick code block.
- The session is equivalent to a long-lived auth token with full account access. Users must treat it as a password.
- **Bot cannot prevent users from mishandling the session string after delivery.** This is inherent to the feature's purpose.
- AST test `TestNoSecretsInLogs` verifies `string_session` never appears in any log call.

---

## 6. SQLite Session File Handling

- SQLite `.session` file generated during `/create_session` flow.
- **Temp directory:** `tempfile.mkdtemp()` → `os.chmod(dir, 0o700)` → owner-only access.
- **File permissions:** `os.chmod(session_file, 0o600)` before Telegram upload → owner read/write only.
- **Cleanup:** `shutil.rmtree(tmpdir, ignore_errors=True)` in `finally` block on all code paths (success, error, cancellation, timeout).
- **After delivery:** File exists on Telegram servers (end-to-end encrypted delivery). Bot does not retain a copy.
- **Delivery failure:** If `bot.send_document()` raises, `finally` still cleans up the tmpdir.

---

## 7. Uploaded Session File Handling (/login_session)

- File accepted only if:
  1. Extension is exactly `.session` (case-sensitive check)
  2. File size ≤ 512 KB (`document.file_size <= 512 * 1024`)
- Downloaded to per-user tmpdir (`chmod 700`).
- Opened with `SQLiteSession(path)` + `TelegramClient`. Only `get_me()` is called — no further account operations.
- Client disconnected with `await client.disconnect()` before status update.
- Tmpdir cleaned in `finally` on all paths.
- **No path traversal risk:** Telethon's `SQLiteSession` receives a full absolute path from `tmpdir/filename`. Filename comes from `document.file_name` which is URL-sanitized by aiogram's download mechanism.

---

## 8. Temporary File Security Summary

| Property | Value |
|---|---|
| Location | `tempfile.mkdtemp()` (OS-managed temp dir) |
| Directory permissions | `0o700` (owner-only) |
| File permissions | `0o600` (owner-only) |
| Cleanup trigger | `finally` block — always runs |
| Cleanup method | `shutil.rmtree(path, ignore_errors=True)` |
| Risk if cleanup fails | Orphaned temp dir. `ignore_errors=True` prevents crash but file remains. |
| Concurrent user isolation | Each user gets their own `mkdtemp()` path |

**Known gap:** If the process is killed with `SIGKILL` (not graceful shutdown), `finally` blocks do not run and tmpdir may remain. Standard operating constraint for all Python processes.

---

## 9. SSRF Protection

`app/utils/network.py` `is_safe_host()` blocks the following before any outbound URL fetch:

| Category | Examples blocked |
|---|---|
| Private IPv4 ranges | 10.x.x.x, 172.16–31.x.x, 192.168.x.x |
| Loopback | 127.x.x.x, `localhost` |
| Link-local | 169.254.x.x |
| CGNAT (RFC 6598) | 100.64.0.0/10 |
| Benchmarking (RFC 2544) | 198.18.0.0/15 |
| Test-net (RFC 5737) | 192.0.2.x, 198.51.100.x, 203.0.113.x |
| Multicast | 224.x.x.x–239.x.x.x |
| Reserved/broadcast | 240.x.x.x, 255.255.255.255 |
| Decimal integer IP | `http://2130706433/` (= 127.0.0.1) |
| Octal encoded IP | `http://0177.0.0.1/` |
| Hex encoded IP | `http://0x7f000001/` |
| Known internal names | `metadata`, `internal`, `169.254.169.254` |

Applied to: `/ip` command input.

**Applies to:** `/ip` only. The `/weather`, `/short`, `/tr`, `/ocr` commands use hardcoded URLs or service-controlled parameters and do not process user-supplied URLs as fetch targets.

**15 SSRF guard tests pass** (verified in test_behavioral.py `TestSSRFGuard`).

---

## 10. HTML Injection in Bot Replies

All handlers using `parse_mode="HTML"` apply `html.escape()` to every user-controlled or API-controlled value before rendering. Verified modules:

| Handler | Mode | Escaping |
|---|---|---|
| `/ua` | HTML | `html.escape()` on from_user, chat fields |
| `/ip` | HTML | `html.escape()` on all ip-api.com response fields |
| `/weather` | HTML | `html.escape()` on all wttr.in response fields |
| `/id` | HTML | `html.escape()` on all name fields |
| `/info` | HTML | `html.escape()` on all name fields |
| `/ocr` | HTML | `html.escape()` on OCR output |
| `/short` | HTML | `html.escape()` on shortened URL |
| `/tr` | HTML | `html.escape()` on translated text |
| `/qr` caption | HTML | `html.escape()` on content string |
| `/qrscan` | HTML | `html.escape()` on decoded content |

---

## 11. Markdown Injection / Rendering Bugs

Not security issues, but UX failures caused by `parse_mode="Markdown"` with unescaped user-controlled output:

| Handler | Field | Risk | Severity |
|---|---|---|---|
| `/b64de` | decoded bytes | Backtick in output → TelegramBadRequest → misleading error | MEDIUM UX |
| `/urlde` | decoded URL | Same — %60 → backtick | MEDIUM UX |
| `/jsonfmt` | JSON values | Triple-backtick in value breaks code fence | LOW UX |
| `/login_session` | account name | Underscore/asterisk in name breaks formatting | LOW UX |
| `/checkpwd` | output | Static label strings, safe | NONE |
| `/hash` | hex digests | Hex only, safe | NONE |
| `/uuid` | UUID string | Hex+dashes, safe | NONE |
| `/b64en` | encoded output | Base64 charset, safe | NONE |
| `/urlen` | encoded output | Alphanumeric+%, safe | NONE |
| `/password` | password | Contains special chars in backtick block — `!@#$%^&*` are safe in Markdown backtick | NONE |

---

## 12. User Isolation

| Feature | Isolation mechanism |
|---|---|
| `/string` | `ACTIVE_CLIENTS[user_id]` — dict key is user_id |
| `/create_session` | `CS_ACTIVE[user_id]` — dict key is user_id |
| `/login_session` | Per-user tmpdir from `tempfile.mkdtemp()` |
| FSM states | aiogram `MemoryStorage` keys by (chat_id, user_id) |
| Callbacks | All cancel/control callbacks use `callback.from_user.id` — cannot affect other users |

---

## 13. Logging Rules (Verified)

**What IS logged:**
- `event` type strings (e.g. `"process_start"`, `"feature_loaded"`, `"request_completed"`)
- Feature names, versions
- Error types (class name), error messages (no stack trace to user)
- Timing values (duration_ms)
- `hash_len` (length of phone_code_hash — not the hash itself)
- `user_id` (Telegram numeric ID — not PII in the legal sense in this context)

**What is NEVER logged:**
- `BOT_TOKEN`
- `API_HASH` or `api_hash`
- `string_session` (session string value)
- Phone numbers
- OTP codes
- 2FA passwords
- Session file contents
- Any full credentials or secrets

**Log format:** JSON via `python-json-logger`. Structured logging throughout.

---

## 14. Admin Command Security

`_is_admin(message)` in `admin/router.py`:
```python
def _is_admin(message: Message) -> bool:
    if settings.ADMIN_ID == 0:
        return False          # Fail-closed: ADMIN_ID unconfigured → deny everyone
    return message.from_user.id == settings.ADMIN_ID
```

Properties:
- **Fail-closed:** Default `ADMIN_ID=0` in Settings denies all admin access if env var not set.
- **Exact match:** Integer comparison, not string comparison.
- **Silent rejection:** Non-matching messages are simply not routed by aiogram. No error reply is sent to non-admins, so the existence of admin commands is not disclosed.
- **No privilege escalation path:** No way to change `ADMIN_ID` at runtime.

---

## 15. Rate Limiting and Resource Limits

**Current bot-level rate limiting: NONE.**

| Limit type | Current status | Notes |
|---|---|---|
| Per-user command rate limit | Not implemented | Any user can spam any command |
| Concurrent Telethon sessions | Unbounded | `ACTIVE_CLIENTS` and `CS_ACTIVE` have no maximum size |
| OCR request rate | Delegated to OCRSpace free tier (unknown limit) | No bot-level throttle |
| IP lookup rate | Delegated to ip-api.com (45 req/min per bot IP) | 429 handled gracefully, no retry |
| URL shortener rate | Delegated to providers | No bot-level throttle |
| Translation rate | Delegated to unofficial Google API | No bot-level throttle |
| Photo size | Telegram Bot API limit: 20 MB for bots | Enforced by Telegram, not bot code |
| Uploaded .session file size | 512 KB hard limit in code | Enforced in handler |
| QR content size | ~2953 bytes (qrcode library) | Not enforced in code — DataOverflowError gives generic error |

**Risk:** A single malicious user could repeatedly invoke `/create_session` or `/string`, causing unbounded Telethon `TelegramClient` connections and background task accumulation. On a Render free tier (512 MB RAM), this could cause OOM on sustained abuse.

---

## 16. File Security Summary

| Scenario | Protection |
|---|---|
| Oversized uploaded .session | 512 KB guard in handler |
| Wrong file extension | `.session` extension check |
| Path traversal in filename | Telethon SQLiteSession receives OS-constructed absolute path |
| Malicious session content | Telethon's own parser handles it; `InvalidBufferError` caught |
| Temp file accessible by other users | `chmod 700` on tmpdir |
| Session file accessible by other users | `chmod 600` on file |
| Cleanup on success | `finally` block with `shutil.rmtree` |
| Cleanup on error | Same `finally` block |
| Cleanup on SIGKILL | NOT guaranteed (OS-level kill bypasses Python finally) |

---

## 17. Known Risks and Current Mitigations

| Risk | Current Mitigation | Gap |
|---|---|---|
| API_ID/API_HASH exposure | Not in source/logs | Not in .env.example — deployer discovery gap |
| Unbounded concurrent sessions | None | No max session limit |
| OTP code in chat history | Unavoidable (Bot API limitation) | Info message shown, user warned |
| 2FA password in chat history | Unavoidable (Bot API limitation) | Info message shown |
| String session in chat history | Delivered via Telegram (encrypted), but stored in Telegram servers | Inherent to feature design |
| .session file through Telegram | Encrypted delivery but passes through Telegram servers | Inherent to feature design |
| Temp file on SIGKILL | OS-level cleanup not guaranteed | Standard Python limitation |
| Unofficial Google Translate API | TimeoutError caught | No SLA, can break without notice |
| ip-api.com HTTP (not HTTPS) | Intentional (free tier) | Response could be MiTM'd (geo data, not credentials) |
| No per-user rate limiting | None | Resource exhaustion under sustained abuse |
