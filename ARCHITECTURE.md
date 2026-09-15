# ARCHITECTURE.md
# Shade Utility Platform V8 — Verified Architecture
> Documented from actual source code. No inferred or planned elements.

---

## 1. Entry Point

```
main.py
├── setup_logger()
├── ApplicationBootstrap()
├── bootstrap.create_app() → aiohttp.web.Application
├── app.router.add_get("/health/live", liveness_handler)
├── app.router.add_get("/health/ready", readiness_handler)
├── app.router.add_get("/health", health_check_handler)
└── web.run_app(app, host="0.0.0.0", port=PORT)
```

`web.run_app()` blocks and runs the aiohttp event loop. The Telegram polling task runs inside this same event loop as an `asyncio.Task`.

---

## 2. Bootstrap Sequence

`ApplicationBootstrap.on_startup()` is registered as an aiohttp `on_startup` hook. It runs once before the HTTP server begins accepting connections.

### Startup Contract (ordered, atomic)

```
Step 1: settings.validate_startup()
        → Raises if BOT_TOKEN missing.
        → Logs WARNING if OCR_API_KEY missing.
        
Step 2: aiohttp.ClientSession() opened
        → Shared HTTP client for all outbound requests.
        → Held for the entire process lifetime.
        
Step 3: await bot.get_me()
        → Validates BOT_TOKEN is live.
        → Sets self.bot_username.
        
Step 4: Build provider failover engines
        ProviderFailoverEngine("OCR")
          ├── OCRSpaceProvider (primary)    + CircuitBreaker("OCRSpace", threshold=2)
          └── DummyFallbackOCRProvider (last-resort) + CircuitBreaker("FallbackOCR")
        ProviderFailoverEngine("URLShortener")
          ├── CleanURIProvider (primary)    + CircuitBreaker("CleanURI", threshold=2)
          └── VGdURLProvider (fallback)     + CircuitBreaker("VGdURL", threshold=2)
          
Step 5: Build services
        OCRService(ocr_engine, event_bus)
        ShortenerService(url_engine)
        TranslatorService()
        
Step 6: Register middleware (order matters in aiogram)
        dp.message.middleware(PlatformErrorMiddleware())
        dp.callback_query.middleware(PlatformErrorMiddleware())
        dp.message.middleware(PlatformDIMiddleware(self))
        dp.callback_query.middleware(PlatformDIMiddleware(self))
        
Step 7: load_features(dp, capability_registry)
        → Imports each module in FEATURE_MODULES list (isolated try/except)
        → Validates router + manifest exports
        → Registers manifest in CapabilityRegistry
        → Calls dp.include_router(mod.router)
        → Returns (loaded_names, failed_module_paths)
        
Step 8: await bot.delete_webhook(drop_pending_updates=True)
        → Clears any stale webhook config before polling starts.
        
Step 9: asyncio.create_task(dp.start_polling(bot), name="bot_polling")
        → Bot polling starts in background task.
        
Step 10: set_ready(bot_task=..., http_session=..., features_loaded=N, degraded_features=[...])
         → Stores LIVE object references in _readiness dict.
         → /health/ready now returns 200.
```

**If any step 1–10 raises an exception:** `_rollback_resources()` is called (cancels bot_task if started, closes http_session and bot.session), then `SystemExit` is raised.

---

## 3. Shutdown Sequence

`ApplicationBootstrap.on_shutdown()` is registered as an aiohttp `on_cleanup` hook.

```
Step 1: set_not_ready("shutdown")
        → /health/ready returns 503 immediately.
        
Step 2: bot_task.cancel() + asyncio.wait_for(bot_task, timeout=10.0)
        → Stops polling. Allows up to 10 seconds for graceful stop.
        
Step 3: await shutdown_all_sm_sessions()
        → Disconnects all active Telethon clients in CS_ACTIVE (session_manager).
        
Step 4: await shutdown_all_sessions()
        → Disconnects all active Telethon clients in ACTIVE_CLIENTS (session).
        
Step 5: await _close_http_resources()
        → http_session.close()
        → bot.session.close()
```

**Order is critical.** Polling must be cancelled before Telethon cleanup so no new messages can trigger session creation during cleanup.

---

## 4. Feature Registration

```python
# app/features/__init__.py
FEATURE_MODULES = [
    "app.features.general.router",
    "app.features.crypto.router",
    "app.features.media.router",
    "app.features.session.router",
    "app.features.session_manager.router",
    "app.features.admin.router",
]
```

For each module:
1. `importlib.import_module(module_path)` — dynamic import
2. Validate `router` attribute (aiogram Router)
3. Validate `manifest` attribute (FeatureManifest)
4. `registry.register(manifest)` — adds to CapabilityRegistry
5. `dp.include_router(mod.router)` — registers handlers with Dispatcher

**Failure isolation:** If any module raises (import error, missing export, runtime error), only that module is skipped. The rest continue loading. Failed modules appear in `degraded_features` in the health readiness response.

---

## 5. Middleware Chain

aiogram middleware executes in this order for every message/callback_query:

```
Incoming update
     ↓
PlatformErrorMiddleware.__call__()
     ↓
PlatformDIMiddleware.__call__()    ← injects: registry, event_bus, bootstrap_ref,
     ↓                                          ocr_service, shortener_service,
     ↓                                          translator_service, bot_username
Handler function
     ↑
PlatformDIMiddleware (return)
     ↑
PlatformErrorMiddleware (catches: FeatureDisabledError, NoProvidersAvailableError, Exception)
```

**PlatformErrorMiddleware catches:**
- `FeatureDisabledError` → `🔒 {message}` reply
- `NoProvidersAvailableError` → `⚠️ Service is temporarily unavailable.` reply
- All other `Exception` → logs `unhandled_error` + `⚠️ Internal system error occurred.` reply

**Note:** `TelegramBadRequest` from `parse_mode=Markdown` rendering failures is caught here as a generic Exception, producing the generic internal error message.

---

## 6. Handler Flow (Message)

```
Telegram Update (message)
        ↓
aiogram Dispatcher
        ↓
Router filter matching (Command filter, F.func, StateFilter)
        ↓
Middleware chain (Error → DI)
        ↓
Handler function (receives Message, State, injected services)
        ↓
[optional] FSM state transitions
        ↓
[optional] background asyncio.Task creation
        ↓
Telegram API calls (message.reply, message.edit_text, etc.)
```

---

## 7. Callback Query Flow

```
Telegram Update (callback_query)
        ↓
aiogram Dispatcher
        ↓
Router filter: F.data == "callback_data_string"
        ↓
Middleware chain (Error → DI)
        ↓
Callback handler (receives CallbackQuery, State, injected services)
        ↓
call.message.edit_text() or call.message.edit_caption()
        ↓
call.answer() (required to dismiss loading indicator)
```

---

## 8. FSM State Flow

Three independent FSM state groups. All use aiogram's default `MemoryStorage` (in-process RAM).

### StringSessionState (session/router.py)

```
[None]
  ↓ /string
[StringSessionState.choosing_method]
  ↓ ses_method_qr           ↓ ses_method_otp
[waiting_for_qr]       [waiting_for_phone]
  ↓ QR scanned             ↓ phone entered
[done / cleared]       [waiting_for_code]
                            ↓ code entered (+ optional 2FA)
                           [done / cleared]
```

All paths → `state.clear()` on success, cancel, timeout, or error.

### CreateSessionState (session_manager/router.py)

```
[None]
  ↓ sm_create
[CreateSessionState.choosing_method]
  ↓ sm_method_qr              ↓ sm_method_otp
[waiting_for_qr_scan]    [waiting_for_phone]
  ↓ QR scanned                ↓ phone entered
[done / cleared]          [waiting_for_code]
                               ↓ code + optional 2FA
                              [done / cleared]
```

### LoginSessionState (session_manager/router.py)

```
[None]
  ↓ sm_login
[LoginSessionState.waiting_for_file]
  ↓ .session file received
[done / cleared]
```

---

## 9. Platform Services

### OCRService
```
ocr_service.extract_text(photo_bytes, user_id)
  → ProviderFailoverEngine.execute("parse_image", photo_bytes)
      → OCRSpaceProvider.parse_image()    [CircuitBreaker(threshold=2, recovery=60s)]
          → POST api.ocr.space/parse/image (text-first read, 15s timeout)
      → [on failure] DummyFallbackOCRProvider.parse_image() → ""
      → [both fail] NoProvidersAvailableError
  → event_bus.publish("ocr_processed", {...})   [no current subscribers]
  → returns extracted_text
```

### ShortenerService
```
shortener_service.shorten_url(url)
  → ProviderFailoverEngine.execute("create_short_url", url)
      → CleanURIProvider.create_short_url()  [CircuitBreaker(threshold=2, recovery=60s)]
          → POST cleanuri.com/api/v1/shorten (text-first read, 15s timeout)
      → [on failure] VGdURLProvider.create_short_url()  [CircuitBreaker(threshold=2)]
          → GET v.gd/create.php?format=simple&url=... (text response, 15s timeout)
      → [both fail] NoProvidersAvailableError
```

### TranslatorService
```
translator_service.translate(text, target_lang)
  → LANG_ALIASES.get(target_lang.lower(), target_lang.lower())
  → asyncio.wait_for(
        loop.run_in_executor(None, _do_translate),
        timeout=15.0
    )
  → GoogleTranslator(source="auto", target=code).translate(text)
  → raises TimeoutError on 15s
  → raises ValueError on LanguageNotSupportedException
```

### CircuitBreaker
```
States: CLOSED → OPEN → HALF_OPEN → CLOSED

CLOSED:   Normal operation. Counts failures.
OPEN:     After failure_threshold failures (2 for OCR/URL, 3 for fallbacks).
          Raises CircuitOpenError immediately (no call attempted).
          After recovery_timeout (60s): transitions to HALF_OPEN.
HALF_OPEN: One probe attempt. Success → CLOSED (reset failures).
           Failure → back to OPEN (reset timer).
```

---

## 10. Shared Utilities

### `app/utils/crypto.py`
Pure Python functions: `gen_uuid`, `gen_password`, `check_password_strength`, `gen_hashes`, `b64_encode`, `b64_decode`, `url_encode`, `url_decode`, `current_time`. No external dependencies. No state.

### `app/utils/network.py`
`is_safe_host(host)` — SSRF guard. Blocks: private IP ranges, loopback, link-local, CGNAT (RFC 6598), benchmarking (RFC 2544), test-net ranges (RFC 5737), multicast, reserved, decimal-integer encoding, octal prefix, hex prefix, named internal hosts. No external dependencies.

### `app/utils/qr.py`
`generate_qr_buffer(data)` → `io.BytesIO` containing PNG. `scan_qr_from_bytes(image_bytes)` → decoded string. Uses `qrcode`, `pyzbar`, `Pillow`.

### `app/core/logger.py`
`setup_logger()` → JSON-formatted logger using `python-json-logger`. Named `"ShadePlatform"`. Idempotent (checks `logger.handlers` before adding).

### `app/core/metrics.py`
`MetricsRegistry` with two Prometheus `Counter` objects: `events_total` (used by EventBus), `api_failures_total` (defined but never incremented).

### `app/platform/capability.py`
`FeatureManifest` dataclass + `CapabilityRegistry`. Supports `register()`, `is_enabled()`, `toggle()`, `require()`. `toggle()` has no current callers. Only `OCRService` calls `require()`.

### `app/platform/event_bus.py`
`EventBus` with `subscribe(event_type, callback)` and `publish(event_type, payload)`. Publish increments `metrics.events_published`. No current subscribers to any event.

---

## 11. Temporary File Handling

Only `session_manager/router.py` uses temporary files.

```
_rmtmpdir(path):
    shutil.rmtree(path, ignore_errors=True)

For /create_session:
    tmpdir = tempfile.mkdtemp()     # system temp, e.g. /tmp/abc123
    os.chmod(tmpdir, 0o700)         # owner-only access
    session_path = tmpdir/user_id.session
    [... write SQLite session file ...]
    os.chmod(session_path, 0o600)   # owner-only read/write
    [... send file to Telegram ...]
    finally: _rmtmpdir(tmpdir)      # always cleaned up

For /login_session:
    tmpdir = tempfile.mkdtemp()
    os.chmod(tmpdir, 0o700)
    session_path = tmpdir/uploaded_file_name
    [... download file from Telegram to session_path ...]
    [... open with Telethon, get_me() ...]
    finally: _rmtmpdir(tmpdir)      # always cleaned up
```

---

## 12. Background Tasks

Both session features create two background `asyncio.Task` objects per active session:

**Session (FROZEN) — per `/string` user:**
- `_wait_for_qr(user_id, ...)` — awaits QR scan result from Telegram
- `_qr_countdown(user_id, ...)` — refreshes QR before expiry, cancels wait on timeout

**Session Manager — per `/create_session` user:**
- `_cs_wait_for_qr(user_id, ...)` — same pattern
- `_cs_qr_countdown(user_id, ...)` — same pattern

**Self-cancellation guard (both):**
```python
if task is not asyncio.current_task():
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
```
This prevents a background task from cancelling itself when `_cleanup_user_session()` is called from within that same task.

---

## 13. Key Architectural Boundaries

### /string vs Session Manager — Why They Must Remain Isolated

These two authentication subsystems share the same Telegram MTProto credentials (`API_ID`/`API_HASH`) and the same underlying auth flow (QR + OTP), but they are **completely isolated** by design:

| Dimension | /string (FROZEN) | Session Manager |
|---|---|---|
| Module | `session/router.py` | `session_manager/router.py` |
| Active client dict | `ACTIVE_CLIENTS` | `CS_ACTIVE` |
| FSM state class | `StringSessionState` | `CreateSessionState` / `LoginSessionState` |
| Callback prefix | `ses_*` | `sm_*` / `lsess_*` |
| Shutdown hook | `shutdown_all_sessions()` | `shutdown_all_sm_sessions()` |
| Background task names | `_qr_countdown`, `_wait_for_qr` | `_cs_qr_countdown`, `_cs_wait_for_qr` |
| Output | StringSession string | SQLite `.session` file |

**Why isolation is critical:**

1. **Bug containment:** A regression in session_manager cannot corrupt an active `/string` session. Each user's session state is keyed to their user_id in a separate dict.

2. **FSM independence:** If `StringSessionState` were merged with `CreateSessionState`, an OTP code message intended for `/string` could be captured by the `/create_session` handler, or vice versa.

3. **Callback namespace collision:** If `ses_cancel` and `sm_cancel` shared a handler, pressing cancel on a `/string` session would also cancel any simultaneous `/create_session` session for the same user (since both use `user_id` as the key).

4. **Shutdown ordering:** The shutdown contract explicitly calls `shutdown_all_sm_sessions()` before `shutdown_all_sessions()`. These are separate exported functions. Merging them would require modifying the shutdown contract in `bootstrap.py`.

5. **The frozen constraint:** `session/router.py` must not change. Any new authentication feature must be a new isolated module, not a modification of the frozen module.

**Rule:** If you need a new authentication output format or flow, add a new module. Do not modify `session/router.py`.

---

## 14. Config and Settings

```python
# app/core/config.py
class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OCR_API_KEY: str = os.getenv("OCR_API_KEY", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    REQUEST_TIMEOUT: int = 15
    MAX_RETRIES: int = 3
```

**Not in Settings (read directly from env in router files):**
- `API_ID` — `int(os.environ.get("API_ID", 0))` in session routers
- `API_HASH` — `os.environ.get("API_HASH", "")` in session routers

`MAX_RETRIES` is defined but never used — no retry logic implemented anywhere.

---

## 15. Health Check Architecture

```
GET /health/live
  → Always 200 {"status": "alive", "service": "Shade Utility Platform"}
  → No external checks. Stateless. Tests only: can the process respond?

GET /health/ready
  → Reads _readiness dict (set by set_ready() at startup)
  → If ready=False: 503 {"status": "not_ready", "reason": "initializing"|"shutdown"}
  → If ready=True:
      bot_alive = bot_task is not None and not bot_task.done()
      http_ok   = http_session is not None and not http_session.closed
      → If both OK and no degraded features: 200 {"status": "ready"}
      → If both OK but degraded features: 200 {"status": "degraded"}
      → If either critical subsystem down: 503 {"status": "unhealthy"}
```

**Design principle:** Readiness checks live object state, not a cached snapshot. If the polling task dies between health checks, the next `/health/ready` probe will catch it and return 503.
