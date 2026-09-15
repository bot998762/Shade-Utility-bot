# UPGRADE_RISK_MATRIX.md
# Shade Utility Platform V8 — Upgrade Risk Matrix
> Every proposed upgrade evaluated on five dimensions.
> Rating scale: LOW / MEDIUM / HIGH / CRITICAL

---

| # | Upgrade | Benefit | Complexity | Security Risk | Performance Risk | Conflict Risk | Recommendation |
|---|---|---|---|---|---|---|---|
| U01 | Fix TestHealthEndpoints tests | HIGH | LOW | NONE | NONE | LOW | ✅ Do first |
| U02 | Add API_ID/API_HASH to .env.example + Settings | HIGH | LOW | NONE | NONE | LOW | ✅ Do first |
| U03 | Fix /b64de + /urlde Markdown bug (→HTML) | HIGH | LOW | NONE | NONE | LOW | ✅ Do first |
| U04 | Fix /login_session account name Markdown | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 1 |
| U05 | Fix cat_session stale usage text | LOW | LOW | NONE | NONE | LOW | ✅ Phase 1 |
| U06 | Document /time or remove it | LOW | LOW | NONE | NONE | LOW | ✅ Phase 1 |
| U07 | Per-user rate limiting middleware | HIGH | MEDIUM | LOW | LOW | LOW | ✅ Phase 2 |
| U08 | Max concurrent Telethon session limit | MEDIUM | LOW | NONE | LOW | LOW | ✅ Phase 2 |
| U09 | /ip HTTPS + retry + TTLCache | MEDIUM | LOW | LOW | NONE | LOW | ✅ Phase 2 |
| U10 | /epoch timezone support | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U11 | /qr DataOverflowError user message | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U12 | Tesseract local OCR fallback | HIGH | MEDIUM | LOW | MEDIUM | LOW | ✅ Phase 2 |
| U13 | Wire api_failures counter | LOW | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U14 | Remove cachetools from requirements | LOW | LOW | NONE | NONE | LOW | ✅ Phase 1 |
| U15 | /hash + SHA-3 + BLAKE2 | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U16 | /b64de URL-safe Base64 variant | LOW | LOW | NONE | NONE | LOW | 🟡 Phase 3 |
| U17 | /password passphrase mode | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U18 | /checkpwd score breakdown + entropy | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U19 | /checkpwd common password list | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U20 | /checkpwd HaveIBeenPwned (k-anon) | HIGH | MEDIUM | MEDIUM | LOW | LOW | 🟡 Phase 3 |
| U21 | /weather unit selection (C/F) | LOW | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U22 | /weather multi-day forecast | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U23 | /short URL expand mode | HIGH | MEDIUM | MEDIUM | LOW | LOW | ✅ Phase 2 |
| U24 | /short input URL validation | MEDIUM | LOW | LOW | NONE | LOW | ✅ Phase 1 |
| U25 | /short category fix (move to URL module) | LOW | LOW | NONE | NONE | MEDIUM | 🟡 Phase 3 |
| U26 | /qr error correction level | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U27 | /qrscan multi-QR decode | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U28 | /tr official API (DeepL/LibreTranslate) | HIGH | MEDIUM | LOW | NONE | LOW | 🟡 Phase 3 |
| U29 | /tr language detection mode | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U30 | /hash file mode (document input) | HIGH | MEDIUM | LOW | MEDIUM | LOW | ✅ Phase 2 |
| U31 | /ip multi-field (ASN, proxy, hosting flags) | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U32 | /ip batch mode (multiple IPs) | MEDIUM | MEDIUM | LOW | LOW | LOW | 🟡 Phase 3 |
| U33 | /create_session bug fix (HTML mode) | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 1 |
| U34 | /diag circuit breaker status | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U35 | /diag active session count | LOW | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U36 | Admin auto-alert on polling death | MEDIUM | MEDIUM | LOW | NONE | LOW | 🟡 Phase 4 |
| U37 | Event bus subscribers (audit/rate limit) | MEDIUM | MEDIUM | NONE | LOW | LOW | 🟡 Phase 4 |
| U38 | CapabilityRegistry /diag toggle commands | LOW | MEDIUM | LOW | NONE | MEDIUM | 🟡 Phase 4 |
| U39 | /qr WiFi QR mode | LOW | LOW | LOW | NONE | LOW | 🟡 Phase 3 |
| U40 | /b64de binary hex preview fallback | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U41 | /epoch relative time ("2 days ago") | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U42 | /epoch duration between timestamps | MEDIUM | LOW | NONE | NONE | LOW | ✅ Phase 2 |
| U43 | Extract shared session task utils | LOW | MEDIUM | NONE | NONE | MEDIUM | 🟡 Phase 4 |
| U44 | /ip Shodan port check | LOW | HIGH | HIGH | MEDIUM | LOW | ❌ Avoid |
| U45 | /session refresh (new frozen module) | MEDIUM | HIGH | HIGH | LOW | HIGH | 🟡 Phase 5 |
| U46 | PDF OCR support (/ocr on documents) | MEDIUM | HIGH | MEDIUM | HIGH | LOW | 🟡 Phase 4 |

---

## Highest-Risk Upgrades

### U44 — /ip Shodan Port Check
**Risk:** Enables port scanning tool in a public Telegram bot. High misuse potential. Requires Shodan API key management. Cannot be rate-limited sufficiently to prevent abuse.
**Decision:** Avoid.

### U45 — /session refresh (new module)
**Risk:** New MTProto auth flow touching session lifecycle. The isolation pattern (new module, new FSM, new dict, new prefix) is established but the implementation complexity is high and a regression could affect existing session features.
**Decision:** Phase 5 with full regression suite requirement.

### U46 — PDF OCR
**Risk:** `pdf2image` and `poppler-utils` shell out to system binaries processing untrusted PDF files. Malformed PDFs could crash the converter or exploit poppler vulnerabilities. RAM consumption for multi-page PDFs can be significant.
**Decision:** Phase 4 with strict page limit (5 pages max), file size limit (5 MB), and timeout.

### U20 — HaveIBeenPwned
**Risk:** Sends SHA-1 prefix (5 chars) to external API. Mathematically safe but requires user trust. Must be opt-in to avoid sending data the user didn't expect to be transmitted.
**Decision:** Phase 3, opt-in only, with clear in-bot explanation.

---

## Lowest-Risk High-Value Upgrades (Do These First)

In priority order, the highest benefit / lowest risk upgrades:

1. **U01** — Fix TestHealthEndpoints (test only, no app code)
2. **U02** — Add API_ID/API_HASH to .env.example (config only)
3. **U03** — Fix /b64de+/urlde Markdown bug (mode switch + html.escape)
4. **U04** — Fix /login_session account name Markdown
5. **U14** — Remove cachetools from requirements
6. **U11** — /qr DataOverflowError user message
7. **U15** — /hash SHA-3 + BLAKE2 (stdlib, no new deps)
8. **U21** — /weather unit selection (wttr.in already supports it)
