# CURRENT_STATE.md
# Shade Utility Platform V8 — Verified Current State
> Source of truth: actual repository source code (forensic read, September 2025)
> Status: READ-ONLY BASELINE. Do not treat any item here as a change target.

---

## 1. Project Identity

| Field | Value |
|---|---|
| Name | Shade Utility Platform V8 |
| Type | Telegram utility bot |
| Framework | aiogram 3.4.1 (async, Python) |
| Runtime | Python 3.11 (Dockerfile) |
| HTTP server | aiohttp 3.9.1 (webhook health + aiohttp session) |
| Telegram client | aiogram (bot API) + Telethon 1.34.0 (user API, session features) |
| Entry point | `main.py` |
| Bootstrap | `app/core/bootstrap.py` (`ApplicationBootstrap`) |
| Deployment | Render / Heroku via `Procfile: web: python main.py` |
| Port | `PORT` env var (default 10000) |

---

## 2. Architecture Summary

```
main.py
└── ApplicationBootstrap.create_app()
    ├── aiohttp web.Application
    ├── on_startup hook
    │   ├── Config validation
    │   ├── aiohttp.ClientSession (shared, lifetime-scoped)
    │   ├── bot.get_me() token check
    │   ├── ProviderFailoverEngine × 2 (OCR, URLShortener)
    │   ├── CircuitBreaker per provider (5 total)
    │   ├── OCRService / ShortenerService / TranslatorService
    │   ├── PlatformErrorMiddleware (message + callback_query)
    │   ├── PlatformDIMiddleware (message + callback_query)
    │   ├── load_features() → 6 feature modules, isolated
    │   ├── bot.delete_webhook(drop_pending_updates=True)
    │   ├── asyncio.create_task(dp.start_polling(bot))
    │   └── set_ready(bot_task, http_session, ...)
    └── on_cleanup hook (ordered shutdown)
```

---

## 3. Framework and Runtime

- **aiogram 3.4.1** — async Telegram Bot API framework. Uses `Router` per feature module.
- **Telethon 1.34.0** — MTProto client for user-API session generation.
- **aiohttp 3.9.1** — HTTP client (shared session) + HTTP server (health routes).
- **Python 3.11** — declared in Dockerfile.
- **pydantic-settings 2.1.0** — config/env loading via `Settings(BaseSettings)`.
- **prometheus_client 0.19.0** — metrics counter (partially wired).

---

## 4. Feature Modules

Six feature modules, all registered in `app/features/__init__.py` in this exact order:

| # | Module path | Manifest name | Category | Premium |
|---|---|---|---|---|
| 1 | `app.features.general.router` | GeneralTools | Core | No |
| 2 | `app.features.crypto.router` | CryptoTools | Utility | No |
| 3 | `app.features.media.router` | MediaTools | Utility | No |
| 4 | `app.features.session.router` | session | Auth | No |
| 5 | `app.features.session_manager.router` | SessionManager | Session | No |
| 6 | `app.features.admin.router` | AdminControl | System | Yes |

Loading is **isolated per module**: a broken module is logged and skipped; remaining modules continue loading.

---

## 5. Command System

27 registered commands total. No duplicate command names exist.

| Command | Module | Category |
|---|---|---|
| `/start` | general | Core |
| `/help` | general | Core |
| `/epoch` | general | Dev |
| `/urlen` | general | Dev |
| `/urlde` | general | Dev |
| `/checkpwd` | general | Dev |
| `/ua` | general | Network |
| `/jsonfmt` | general | Dev |
| `/ip` | general | Network |
| `/weather` | general | Network |
| `/id` | general | Network |
| `/info` | general | Network |
| `/uuid` | crypto | Dev |
| `/password` | crypto | Dev |
| `/hash` | crypto | Dev |
| `/b64en` | crypto | Dev |
| `/b64de` | crypto | Dev |
| `/time` | crypto | Dev (undocumented) |
| `/ocr` | media | Media |
| `/short` | media | URL |
| `/tr` | media | Media |
| `/qr` | media | Media |
| `/qrscan` | media | Media |
| `/string` | session | Auth (FROZEN) |
| `/create_session` | session_manager | Auth |
| `/login_session` | session_manager | Auth |
| `/diag` | admin | System |
| `/health` | admin | System |

---

## 6. Menu Structure

### Main Menu (`/start` → `main_menu_kb`)

```
⚡ SHADE UTILITY PLATFORM V8
[🛠️ Developer Tools]  [🔑 String Session]
[📸 Media & OCR]      [🌐 Web & Utilities]
       [🔐 Session Manager]
       [📘 Full Manual (/help)]
  [➕ Add Bot to Telegram Group 👥]
```

### Category Views (all use `category_dev_kb` for back navigation)

| Button | Callback | Shows |
|---|---|---|
| 🛠️ Developer Tools | `cat_dev` | /epoch /urlen /urlde /b64en /b64de /hash /password /checkpwd /uuid /jsonfmt |
| 🔑 String Session | `cat_session` | /string usage (currently shows stale args) |
| 📸 Media & OCR | `cat_media` | /ocr /qr /qrscan /tr |
| 🌐 Web & Utilities | `cat_web` | /ip /weather /short /ua /info /id |
| 🔐 Session Manager | `cat_session_mgr` | Sub-menu with Create/Login/Back |
| 📘 Full Manual | `menu_help` | HELP_MANUAL_TEXT inline |

### Session Manager Sub-menu (`_session_menu_kb`)

```
[📁 Create Session]  [📂 Login Session]
       [🔙 Back]
```

### /string Flow Keyboard (`_method_kb`)

```
[📱 QR Login]  [🔢 OTP Login]
     [❌ Cancel]
```

### QR Active (`_qr_kb`)

```
[🔄 Refresh QR]  [❌ Cancel]
```

### OTP Active (`_otp_kb`)

```
[📲 Resend Code]  [📱 Use QR Login]
      [❌ Cancel]
```

### Create Session Method (`_cs_method_kb`)

```
[📱 QR Login]  [🔢 OTP Login]
     [❌ Cancel]
```

### Session Manager QR Active (`_cs_qr_kb`)

```
[🔄 Refresh QR]  [❌ Cancel]
```

### Login Session Cancel (`_login_cancel_kb`)

```
[❌ Cancel]
```

---

## 7. Callback Structure

All registered `callback_data` values:

| Callback data | Handler function | Module |
|---|---|---|
| `cat_dev` | `handle_dev_cat` | general |
| `cat_session` | `handle_session_cat` | general |
| `cat_media` | `handle_media_cat` | general |
| `cat_web` | `handle_web_cat` | general |
| `cat_session_mgr` | `handle_session_mgr_cat` | session_manager |
| `menu_help` | `handle_utils_menu` | general |
| `back_main` | `back_to_main` | general |
| `ses_method_qr` | `cb_method_qr` | session |
| `ses_method_otp` | `cb_method_otp` | session |
| `ses_qr_refresh` | `cb_qr_refresh` | session |
| `ses_otp_resend` | `cb_otp_resend` | session |
| `ses_start_qr` | `cb_start_qr_from_otp` | session |
| `ses_cancel` | `cb_cancel` | session |
| `sm_create` | `cb_sm_create` | session_manager |
| `sm_login` | `cb_sm_login` | session_manager |
| `sm_method_qr` | `cb_sm_method_qr` | session_manager |
| `sm_method_otp` | `cb_sm_method_otp` | session_manager |
| `sm_qr_refresh` | `cb_sm_qr_refresh` | session_manager |
| `sm_cancel` | `cb_sm_cancel` | session_manager |
| `lsess_cancel` | `cb_lsess_cancel` | session_manager |

**No callback data collisions exist.**

---

## 8. Current Integrations

| Service | Usage | Auth | Protocol | Fallback |
|---|---|---|---|---|
| Telegram Bot API | All bot operations | `BOT_TOKEN` env | HTTPS via aiogram | None (required) |
| Telegram MTProto | Session generation | `API_ID`/`API_HASH` env | Telethon | None |
| OCRSpace API | `/ocr` image text extraction | `OCR_API_KEY` env | HTTPS | DummyFallback (empty string) |
| CleanURI | `/short` URL shortening | None (public) | HTTPS | VGd fallback |
| v.gd | `/short` URL shortening (fallback) | None (public) | HTTPS | NoProviders error |
| ip-api.com | `/ip` geo-lookup | None (free tier) | **HTTP** (intentional) | None |
| wttr.in | `/weather` forecast | None (public) | HTTPS | None |
| Google Translate (unofficial) | `/tr` translation | None (unofficial) | HTTPS via deep_translator | TimeoutError |

---

## 9. Storage and State

**No persistent database.** The bot is stateless across restarts.

| Storage type | What stores | Scope | Persistence |
|---|---|---|---|
| aiogram FSM (MemoryStorage) | OTP phone entry, session state | Per-user, per-chat | In-process RAM only |
| `ACTIVE_CLIENTS` dict | `{user_id: {client, task, state}}` for `/string` | In-process RAM | Lost on restart |
| `CS_ACTIVE` dict | `{user_id: {client, task, state}}` for `/create_session` | In-process RAM | Lost on restart |
| `tempfile.mkdtemp()` | SQLite `.session` files during create/login | Filesystem, per-operation | Deleted in `finally` |
| `_readiness` dict | Health probe state | In-process RAM | Set at startup |

---

## 10. Authentication Features

### /string (FROZEN)
- Generates Telethon `StringSession` (base64 string)
- QR login path: Telethon QR, displayed as PNG via `qrcode`, auto-refresh before expiry
- OTP login path: phone → phone code → optional 2FA password
- Resend code (one-shot via `ResendCodeRequest`)
- Switch OTP → QR mid-flow
- Output: session string in Markdown backtick block
- Concurrent user isolation via `ACTIVE_CLIENTS[user_id]`
- Timeout: 120 seconds

### /create_session (session_manager)
- Same auth flows (QR + OTP) as `/string`
- Output: SQLite `.session` file sent as document
- Delivered via `_convert_and_deliver`: connects with StringSession, exports to SQLite in tmpdir, sends file
- tmpdir: `chmod 700`, file: `chmod 600`
- Timeout: 120 seconds

### /login_session (session_manager)
- Accepts uploaded `.session` document (max 512 KB, `.session` extension only)
- Downloads to per-user tmpdir (`chmod 700`)
- Opens with Telethon, calls `client.get_me()` to verify authorization
- Shows non-sensitive account summary (name, username, ID, tier, type)
- tmpdir cleaned in `finally`

---

## 11. Current Tests

| Suite | Total | Pass | Fail | Skip |
|---|---|---|---|---|
| test_architecture.py | 46 | 46 | 0 | 0 |
| test_behavioral.py | 62 | 62 | 0 | 0 |
| test_markdown_safety.py | 46 | 25 | 0 | 21 |
| test_session_manager.py | 60 | 37 | 0 | 23 |
| **TOTAL** | **214** | **170** | **0** | **44** |

Skips are guarded by `@needs_aiogram` and `@needs_telethon` — not failures.

**Known broken test (not yet skipped):** `TestHealthEndpoints` uses stale `set_ready(bot_task_ok=True, ...)` signature. These tests currently skip because `@needs_aiohttp` decorator guards them, but they would fail if run with aiohttp installed.

---

## 12. Current Limitations

1. No persistent storage — all session state lost on restart
2. No per-user rate limiting at bot level
3. No maximum concurrent Telethon session limit
4. `API_ID`/`API_HASH` not in `.env.example` or `Settings` — discovery gap for new deployers
5. `/time` command is completely undocumented
6. `cat_session` button shows stale `/string <API_ID> <API_HASH>` usage text
7. `/b64de` and `/urlde` use `parse_mode=Markdown` with unescaped output — break on backtick/asterisk content
8. `/login_session` displays account names in Markdown mode without html.escape()
9. `cachetools` listed in requirements but not imported anywhere
10. `deep_translator` uses unofficial Google API — no SLA
11. `ip-api.com` free tier: HTTP only, 45 req/min limit, no retry/backoff
12. QR token lifetime controlled by Telegram (not bot)
13. `TestHealthEndpoints` would fail if aiohttp were installed during test run

---

## 13. Deployment and Runtime Assumptions

- Deployed to Render or Heroku (Procfile present)
- Single process, single worker (`web: python main.py`)
- `PORT` env var used by aiohttp (default 10000)
- Bot polling mode (not webhook mode)
- `libzbar0` system library required (Dockerfile installs it for pyzbar)
- `.session` files excluded from version control via `.gitignore`
- No `.env` file shipped — `.env.example` documents required vars

Required env vars:
- `BOT_TOKEN` — required, startup aborts without it
- `OCR_API_KEY` — optional, /ocr degrades to empty-string fallback
- `ADMIN_ID` — optional (0 = all admin commands locked)
- `API_ID` — required for /string, /create_session, /login_session (undocumented in .env.example)
- `API_HASH` — required for /string, /create_session, /login_session (undocumented in .env.example)
- `PORT` — optional (default 10000)

---

## 14. Frozen Components

The following must not be modified:

| Component | Location | Reason |
|---|---|---|
| `/string` full implementation | `app/features/session/router.py` | Working QR+OTP flow, verified stable, security-sensitive |
| `StringSessionState` FSM | `app/features/session/router.py` | Used by working flow |
| `ACTIVE_CLIENTS` dict | `app/features/session/router.py` | Per-user isolation anchor |
| `ses_*` callback prefix namespace | session/router.py keyboards | Collision would break live sessions |
| `shutdown_all_sessions()` | session/router.py | Called by bootstrap shutdown contract |
| Session Manager isolation architecture | `app/features/session_manager/router.py` | Separate CS_ACTIVE, separate FSM, separate prefix |
| Bootstrap shutdown order | `app/core/bootstrap.py` `on_shutdown()` | Sequence critical: poll cancel → Telethon → HTTP |
| `is_safe_host()` SSRF guard | `app/utils/network.py` | Security-critical, all 15 blocked categories tested |
