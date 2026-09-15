# FROZEN_COMPONENTS.md
# Shade Utility Platform V8 — Frozen Components
> These components must not be modified casually. Each entry explains what is frozen, why, and what constitutes a safe boundary.

---

## FROZEN-01: `app/features/session/router.py` — Entire File

**Status: FULLY FROZEN**

**What is frozen:**
- The entire file: all handlers, helpers, FSM states, background tasks, keyboards, cleanup logic, shutdown hook
- `StringSessionState` (3 states: `choosing_method`, `waiting_for_qr`, `waiting_for_phone`, `waiting_for_code`)
- `ACTIVE_CLIENTS: dict` — per-user session state
- All callback handlers: `cb_method_qr`, `cb_method_otp`, `cb_qr_refresh`, `cb_otp_resend`, `cb_start_qr_from_otp`, `cb_cancel`
- `shutdown_all_sessions()` — exported, called by bootstrap shutdown

**Why frozen:**
1. The QR+OTP+2FA flow is complex, fully working, and security-sensitive. Any modification introduces regression risk.
2. This module's version is 4.0.0 — it has gone through significant iteration to reach stability. That stability must be preserved.
3. The isolation architecture depends on this file's internals not changing. `session_manager` is isolated from it by design; changing the internals of `session/router.py` could accidentally break that isolation.
4. The shutdown hook (`shutdown_all_sessions`) is called by name in `bootstrap.py`. Renaming, removing, or changing its signature breaks the shutdown contract.

**What constitutes a safe boundary:**
- Bug fixes ONLY if a confirmed production crash or data leak is found — and even then, the fix must be minimal and targeted.
- Do NOT refactor for cleanliness.
- Do NOT merge with session_manager.
- Do NOT add new features to this file.
- Do NOT modify the `ses_*` callback prefix namespace.
- Do NOT add new imports that could create circular dependencies.

**If you need a new session feature:**
Create a new isolated module (e.g., `app/features/session_v2/router.py`) following the same isolation pattern. Never modify this file.

---

## FROZEN-02: `ses_*` Callback Prefix Namespace

**Status: FROZEN**

**What is frozen:**
All callback data strings starting with `ses_`:
- `ses_method_qr`
- `ses_method_otp`
- `ses_qr_refresh`
- `ses_otp_resend`
- `ses_start_qr`
- `ses_cancel`

**Why frozen:**
These callback strings are bound to live keyboard buttons sent to users. If a button was sent before a deployment and the handler is removed or renamed after the deployment, pressing that button would produce no response (dead button) for any user who received the old keyboard. Beyond deployment concerns, these exact strings are the contract between the keyboard generator functions and the handler registration.

**What constitutes a safe boundary:**
- No new `ses_*` callbacks may be added to any file other than `session/router.py`.
- No existing `ses_*` callback may be removed or renamed.
- If a new session module needs cancel/refresh functionality, it must use a different prefix (as `session_manager` correctly uses `sm_*` and `lsess_*`).

---

## FROZEN-03: Bootstrap Shutdown Order

**Status: FROZEN**

**What is frozen:**
The exact sequence in `ApplicationBootstrap.on_shutdown()`:
1. `set_not_ready("shutdown")`
2. `bot_task.cancel()` + `asyncio.wait_for(bot_task, timeout=10.0)`
3. `await shutdown_all_sm_sessions()` ← session_manager
4. `await shutdown_all_sessions()` ← session (FROZEN module)
5. `await _close_http_resources()`

**Why frozen:**
The shutdown order is critical for safe resource cleanup:
- Health check must return 503 FIRST (step 1) so no new traffic is routed during shutdown
- Polling must stop BEFORE Telethon cleanup (steps 2→3,4) so no new messages can trigger session creation during cleanup
- SM sessions before string sessions (steps 3→4) so both types of cleanup happen while the event loop is still running, before HTTP resources are torn down (step 5)
- HTTP resources last (step 5) because Telethon cleanup may make HTTP calls internally

Changing this order can cause:
- New sessions being created during cleanup (if order 2 comes after 3/4)
- Telethon cleanup failing because the event loop is closed (if order 5 comes before 3/4)
- Health probe returning 200 during shutdown (if order 1 comes after any other step)

**What constitutes a safe boundary:**
- New Telethon-using modules MUST add their `shutdown_all_*()` calls between steps 2 and 5 (alongside steps 3 and 4).
- The shutdown function exported from any new session module must be registered in bootstrap exactly as `shutdown_all_sm_sessions` and `shutdown_all_sessions` are.
- The `set_not_ready()` call must always remain first.
- `_close_http_resources()` must always remain last.

---

## FROZEN-04: `is_safe_host()` SSRF Guard

**Status: FROZEN / Must Not Be Weakened**

**Location:** `app/utils/network.py`

**What is frozen:**
All 15 blocked IP categories in `is_safe_host()`:
- Private ranges (RFC 1918)
- Loopback
- Link-local
- CGNAT (RFC 6598)
- Benchmarking (RFC 2544)
- Test-net ranges (RFC 5737)
- Multicast
- Reserved
- Decimal integer IP encoding
- Octal encoded IP
- Hex encoded IP
- Known internal hostnames

**Why frozen:**
The SSRF guard protects against server-side request forgery attacks targeting internal network resources. Weakening or removing any category means that specific attack vector becomes possible. All 15 categories are verified by passing tests.

**What constitutes a safe boundary:**
- New blocked categories may be ADDED (more restrictive = safe).
- Existing categories may NEVER be weakened or removed.
- Any new command that takes a user-supplied URL/IP as input MUST call `is_safe_host()` before making any network request.
- Tests for new blocked categories must be added alongside the code.

---

## FROZEN-05: `CS_ACTIVE` / `ACTIVE_CLIENTS` Separation

**Status: FROZEN**

**What is frozen:**
- `ACTIVE_CLIENTS` in `session/router.py` handles `/string` sessions exclusively
- `CS_ACTIVE` in `session_manager/router.py` handles `/create_session` sessions exclusively
- These are in separate Python modules and must never be unified into a single dict

**Why frozen:**
User isolation depends on each session type having its own dict. If merged:
- A `/string` cancel callback could clean up a `/create_session` session (or vice versa)
- Session state for one flow could bleed into the other
- The shutdown hooks (`shutdown_all_sessions` vs `shutdown_all_sm_sessions`) would need to be merged, breaking the shutdown contract

**What constitutes a safe boundary:**
- Any new auth feature must have its OWN separate dict (e.g., `V2_ACTIVE` in a new module)
- The existing dicts may be read (for counting active sessions) but must never be written to by code outside their owning module

---

## FROZEN-06: `shutdown_all_sessions()` and `shutdown_all_sm_sessions()` Export Contract

**Status: FROZEN**

**What is frozen:**
- Both functions are exported from their respective modules
- Both are imported by name in `bootstrap.py`
- Both are called in a specific order during shutdown (SM before string)
- Their signatures: `async def shutdown_all_*() -> None`

**Why frozen:**
Bootstrap's shutdown hook calls these by name. Renaming or removing them requires modifying `bootstrap.py`, which should only happen when intentionally modifying the shutdown contract. The async signature must be maintained (awaitable).

**What constitutes a safe boundary:**
- The functions' names and signatures must not change.
- Their internal behavior (disconnect all Telethon clients in their respective dicts) must not change.
- Adding logging or metrics to them is acceptable.
- New modules must export a similarly named function and have it registered in bootstrap.

---

## Summary

| Component | Location | Reason | Modification allowed? |
|---|---|---|---|
| `/string` full implementation | `session/router.py` | Stable, security-sensitive, working | Bug fixes only, minimal |
| `ses_*` callback prefix | `session/router.py` keyboards | Live button contract | Never rename/remove |
| Bootstrap shutdown order | `bootstrap.py` `on_shutdown()` | Resource cleanup sequence critical | Add new steps only between steps 2–5 |
| `is_safe_host()` guard | `utils/network.py` | SSRF protection | Add categories only; never remove |
| ACTIVE_CLIENTS/CS_ACTIVE separation | Two separate modules | User isolation contract | Never merge |
| `shutdown_all_*()` signatures | Two separate modules | Bootstrap shutdown contract | Never rename/remove |
