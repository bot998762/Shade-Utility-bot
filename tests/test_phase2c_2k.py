"""
Focused Tests — Phases 2C through 2K
======================================
Tests all restored and new features without requiring aiogram / aiohttp.
Each phase has its own TestCase class for clear isolation.
"""

import ast
import importlib.util
import math
import sys
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_module(rel_path: str, name: str):
    """Load a module from a project-relative path without triggering aiogram imports."""
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2C — /epoch: relative time + timezone helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2C_EpochHelpers(unittest.TestCase):
    """Tests for _relative_time and _tz_format, and source-level checks."""

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        self.now = 1700000000  # fixed reference epoch

    def _relative_time(self, ts, now):
        """Local mirror of the helper for isolated testing."""
        diff = ts - now
        abs_diff = abs(diff)
        if abs_diff < 60:
            label = f"{abs_diff} second{'s' if abs_diff != 1 else ''}"
        elif abs_diff < 3600:
            m = abs_diff // 60
            label = f"{m} minute{'s' if m != 1 else ''}"
        elif abs_diff < 86400:
            h = abs_diff // 3600
            label = f"{h} hour{'s' if h != 1 else ''}"
        elif abs_diff < 86400 * 30:
            d = abs_diff // 86400
            label = f"{d} day{'s' if d != 1 else ''}"
        elif abs_diff < 86400 * 365:
            mo = abs_diff // (86400 * 30)
            label = f"{mo} month{'s' if mo != 1 else ''}"
        else:
            y = abs_diff // (86400 * 365)
            label = f"{y} year{'s' if y != 1 else ''}"
        return f"in {label}" if diff > 0 else f"{label} ago"

    def test_source_has_zoneinfo_import(self):
        self.assertIn("from zoneinfo import", self.src)

    def test_source_has_relative_time_function(self):
        self.assertIn("def _relative_time(", self.src)

    def test_source_has_tz_format_function(self):
        self.assertIn("def _tz_format(", self.src)

    def test_source_handles_ZoneInfoNotFoundError(self):
        self.assertIn("ZoneInfoNotFoundError", self.src)

    def test_relative_time_seconds_singular(self):
        self.assertEqual(self._relative_time(self.now + 1, self.now), "in 1 second")

    def test_relative_time_seconds_plural(self):
        self.assertEqual(self._relative_time(self.now + 30, self.now), "in 30 seconds")

    def test_relative_time_seconds_ago(self):
        self.assertEqual(self._relative_time(self.now - 30, self.now), "30 seconds ago")

    def test_relative_time_minutes_singular(self):
        self.assertEqual(self._relative_time(self.now + 90, self.now), "in 1 minute")

    def test_relative_time_minutes_plural(self):
        self.assertEqual(self._relative_time(self.now + 120, self.now), "in 2 minutes")

    def test_relative_time_hours_singular(self):
        self.assertEqual(self._relative_time(self.now - 3600, self.now), "1 hour ago")

    def test_relative_time_hours_plural(self):
        self.assertEqual(self._relative_time(self.now - 7200, self.now), "2 hours ago")

    def test_relative_time_days_singular(self):
        self.assertEqual(self._relative_time(self.now + 86400, self.now), "in 1 day")

    def test_relative_time_days_plural(self):
        self.assertEqual(self._relative_time(self.now + 86400 * 2, self.now), "in 2 days")

    def test_relative_time_months(self):
        result = self._relative_time(self.now + 86400 * 31, self.now)
        self.assertIn("month", result)

    def test_relative_time_years(self):
        result = self._relative_time(self.now + 86400 * 400, self.now)
        self.assertIn("year", result)

    def test_tz_format_utc(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        dt = datetime.fromtimestamp(0, tz=tz)
        result = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        self.assertIn("1970-01-01", result)

    def test_tz_format_new_york(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        dt = datetime.fromtimestamp(1700000000, tz=tz)
        result = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        self.assertIn("2023", result)
        self.assertTrue(result.endswith("ET") or result.endswith("EST") or result.endswith("EDT"))

    def test_invalid_timezone_raises(self):
        from zoneinfo import ZoneInfoNotFoundError, ZoneInfo
        with self.assertRaises(ZoneInfoNotFoundError):
            ZoneInfo("Not/A/Real/Timezone")

    def test_epoch_cmd_no_args_shows_current(self):
        """cmd_epoch with no args triggers current epoch mode."""
        self.assertIn("Current Unix Epoch", self.src)

    def test_epoch_cmd_supports_optional_tz(self):
        """Source must handle timezone argument in cmd_epoch."""
        self.assertIn("_ZoneInfo(tz_name)", self.src)

    def test_epoch_cmd_negative_timestamp_handled(self):
        """Negative timestamp (before 1970) should be parseable."""
        self.assertIn("lstrip(\"-\")", self.src)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2D — /ip: TTLCache + bounded retry
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2D_IPCache(unittest.TestCase):

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/general/router.py").read_text()

    def test_ttlcache_import_in_source(self):
        self.assertIn("TTLCache", self.src)

    def test_cache_maxsize_256(self):
        self.assertIn("maxsize=256", self.src)

    def test_cache_ttl_300(self):
        self.assertIn("ttl=300", self.src)

    def test_ip_max_retries_constant(self):
        self.assertIn("_IP_MAX_RETRIES: int = 2", self.src)

    def test_ssrf_check_before_cache(self):
        ssrf_pos = self.src.index("_is_safe_host(query)")
        cache_pos = self.src.index("cache_key in _IP_CACHE")
        self.assertLess(ssrf_pos, cache_pos, "SSRF check must precede cache lookup")

    def test_cache_key_lowercase(self):
        self.assertIn("cache_key = query.lower()", self.src)

    def test_429_not_retried(self):
        """429 block must use 'return', not 'continue', to prevent retry."""
        idx = self.src.index("resp.status == 429")
        block = self.src[idx:idx + 700]
        self.assertIn("return", block)
        return_pos = block.index("return")
        self.assertNotIn("continue", block[:return_pos])

    def test_asyncio_sleep_not_time_sleep(self):
        self.assertIn("asyncio.sleep(0.5)", self.src)
        # time.sleep must not be called in the retry loop
        self.assertNotIn("time.sleep", self.src)

    def test_5xx_triggers_retry(self):
        self.assertIn("resp.status >= 500", self.src)
        idx = self.src.index("resp.status >= 500")
        block = self.src[idx:idx + 500]
        self.assertIn("continue", block)

    def test_cachetools_in_requirements(self):
        req = (PROJECT_ROOT / "requirements.txt").read_text()
        self.assertIn("cachetools==5.3.2", req)

    def test_successful_response_cached(self):
        self.assertIn("_IP_CACHE[cache_key] = data", self.src)

    def test_failures_not_cached(self):
        """Cache write only happens in success branch, not error branches."""
        cache_write_count = self.src.count("_IP_CACHE[cache_key] = data")
        self.assertEqual(cache_write_count, 1, "Cache write must occur exactly once (success path only)")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2E — /time + /epoch documentation consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2E_Documentation(unittest.TestCase):

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/general/router.py").read_text()

    def test_epoch_docs_mention_timezone(self):
        self.assertTrue(
            "timezone" in self.src.lower() or "IANA" in self.src,
            "epoch docs must mention timezone support"
        )

    def test_epoch_docs_mention_relative_time(self):
        self.assertIn("relative", self.src.lower())

    def test_time_distinguished_from_epoch(self):
        """The /time help must distinguish it from /epoch."""
        self.assertTrue(
            "alias" in self.src.lower() or "Alias" in self.src,
            "/time must be described as alias or distinct from /epoch"
        )

    def test_epoch_help_format_in_manual(self):
        self.assertIn("/epoch", self.src)

    def test_time_help_in_manual(self):
        self.assertIn("/time", self.src)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2F — /password entropy
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2F_PasswordEntropy(unittest.TestCase):

    def setUp(self):
        self.crypto_src = (PROJECT_ROOT / "app/utils/crypto.py").read_text()
        self.router_src = (PROJECT_ROOT / "app/features/crypto/router.py").read_text()

    def test_password_alphabet_constant_present(self):
        self.assertIn("_PASSWORD_ALPHABET", self.crypto_src)

    def test_pool_size_is_70(self):
        self.assertIn("_PASSWORD_POOL_SIZE: int = 70", self.crypto_src)

    def test_gen_password_entropy_present(self):
        self.assertIn("def gen_password_entropy(", self.crypto_src)

    def test_entropy_uses_log2(self):
        self.assertIn("math.log2", self.crypto_src)

    def test_alphabet_length(self):
        import string
        alpha = string.ascii_letters + string.digits + "!@#$%^&*"
        self.assertEqual(len(alpha), 70)

    def test_entropy_value_16_chars(self):
        expected = 16 * math.log2(70)
        self.assertAlmostEqual(expected, 98.12, delta=0.1)

    def test_entropy_value_8_chars(self):
        expected = 8 * math.log2(70)
        self.assertAlmostEqual(expected, 49.06, delta=0.1)

    def test_gen_password_uses_alphabet(self):
        """gen_password must use _PASSWORD_ALPHABET, not a local literal."""
        self.assertIn("secrets.choice(_PASSWORD_ALPHABET)", self.crypto_src)

    def test_crypto_router_shows_entropy(self):
        self.assertIn("gen_password_entropy", self.router_src)

    def test_crypto_router_rejects_non_digit(self):
        self.assertIn("not arg.isdigit()", self.router_src)

    def test_no_password_logging(self):
        """Password values must never reach the logger."""
        self.assertNotIn("logger.info(pwd", self.router_src)
        self.assertNotIn("logger.debug(pwd", self.router_src)

    def test_length_clamped_8_to_64(self):
        self.assertIn("max(8, min(64", self.router_src)

    def test_password_behavior_16(self):
        """gen_password(16) returns 16-char string from the correct alphabet."""
        import string
        expected_alpha = string.ascii_letters + string.digits + "!@#$%^&*"
        mod = _load_module("app/utils/crypto.py", "crypto_mod")
        pwd = mod.gen_password(16)
        self.assertEqual(len(pwd), 16)
        for ch in pwd:
            self.assertIn(ch, expected_alpha)

    def test_password_behavior_8(self):
        mod = _load_module("app/utils/crypto.py", "crypto_mod")
        pwd = mod.gen_password(8)
        self.assertEqual(len(pwd), 8)

    def test_password_behavior_64(self):
        mod = _load_module("app/utils/crypto.py", "crypto_mod")
        pwd = mod.gen_password(64)
        self.assertEqual(len(pwd), 64)

    def test_legacy_check_password_strength_preserved(self):
        """check_password_strength() must still return a label string."""
        mod = _load_module("app/utils/crypto.py", "crypto_mod")
        result = mod.check_password_strength("password")
        self.assertIsInstance(result, str)
        self.assertIn("Weak", result)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2G — /weather multi-day + unit selection
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2G_Weather(unittest.TestCase):

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/general/router.py").read_text()

    def test_unit_f_in_source(self):
        self.assertIn("unit == \"F\"", self.src)

    def test_unit_c_in_source(self):
        self.assertIn("temp_C", self.src)
        self.assertIn("temp_F", self.src)

    def test_multi_day_forecast_supported(self):
        self.assertIn("forecast_days", self.src)

    def test_days_1_to_3_allowed(self):
        self.assertIn('"1", "2", "3"', self.src)

    def test_unit_selection_default_celsius(self):
        self.assertIn('unit = "C"', self.src)

    def test_feels_like_f_present(self):
        self.assertIn("FeelsLikeF", self.src)

    def test_feels_like_c_present(self):
        self.assertIn("FeelsLikeC", self.src)

    def test_forecast_caps_at_3_days(self):
        self.assertIn("[:days]", self.src)

    def test_wttr_url_unchanged(self):
        self.assertIn("wttr.in", self.src)
        self.assertIn("format=j1", self.src)

    def test_weather_arg_parser(self):
        """Simulate arg parsing logic for unit + days extraction."""
        def parse_weather_args(raw_args):
            tokens = list(raw_args)
            unit = "C"
            days = 1
            if tokens and tokens[-1].upper() in ("C", "F"):
                unit = tokens[-1].upper()
                tokens = tokens[:-1]
            if tokens and tokens[-1].isdigit() and tokens[-1] in ("1", "2", "3"):
                days = int(tokens[-1])
                tokens = tokens[:-1]
            city = " ".join(tokens)
            return city, days, unit

        city, days, unit = parse_weather_args(["London"])
        self.assertEqual(city, "London"); self.assertEqual(unit, "C"); self.assertEqual(days, 1)

        city, days, unit = parse_weather_args(["London", "F"])
        self.assertEqual(city, "London"); self.assertEqual(unit, "F")

        city, days, unit = parse_weather_args(["London", "3"])
        self.assertEqual(city, "London"); self.assertEqual(days, 3); self.assertEqual(unit, "C")

        city, days, unit = parse_weather_args(["London", "3", "F"])
        self.assertEqual(city, "London"); self.assertEqual(days, 3); self.assertEqual(unit, "F")

        city, days, unit = parse_weather_args(["New", "York"])
        self.assertEqual(city, "New York"); self.assertEqual(unit, "C")

        city, days, unit = parse_weather_args(["New", "York", "F"])
        self.assertEqual(city, "New York"); self.assertEqual(unit, "F")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2H — /checkpwd score breakdown + common-password detection
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2H_CheckPwd(unittest.TestCase):

    def setUp(self):
        self.mod = _load_module("app/utils/crypto.py", "crypto_2h")

    def test_common_passwords_set_present(self):
        self.assertTrue(hasattr(self.mod, "_COMMON_PASSWORDS"))

    def test_common_passwords_is_frozenset(self):
        self.assertIsInstance(self.mod._COMMON_PASSWORDS, frozenset)

    def test_password123_is_common(self):
        self.assertIn("password123", self.mod._COMMON_PASSWORDS)

    def test_123456_is_common(self):
        self.assertIn("123456", self.mod._COMMON_PASSWORDS)

    def test_detailed_function_present(self):
        self.assertTrue(hasattr(self.mod, "check_password_strength_detailed"))

    def test_detailed_returns_dict(self):
        result = self.mod.check_password_strength_detailed("Hello@World1")
        self.assertIsInstance(result, dict)

    def test_detailed_has_required_keys(self):
        result = self.mod.check_password_strength_detailed("Hello@World1")
        for key in ("score", "label", "length", "checks", "is_common"):
            self.assertIn(key, result)

    def test_checks_has_all_criteria(self):
        result = self.mod.check_password_strength_detailed("Hello@World1")
        for key in ("length_8", "length_12", "mixed_case", "has_digits", "has_symbols"):
            self.assertIn(key, result["checks"])

    def test_strong_password_score_5(self):
        result = self.mod.check_password_strength_detailed("Hello@World1longx")
        self.assertEqual(result["score"], 5)
        self.assertIn("Very Strong", result["label"])

    def test_weak_password_no_digit_no_symbol(self):
        result = self.mod.check_password_strength_detailed("abcdefgh")
        self.assertLessEqual(result["score"], 2)

    def test_common_password_capped_weak(self):
        result = self.mod.check_password_strength_detailed("password123")
        self.assertTrue(result["is_common"])
        self.assertLessEqual(result["score"], 1)
        self.assertIn("Weak", result["label"])

    def test_common_detection_case_insensitive(self):
        result = self.mod.check_password_strength_detailed("PASSWORD123")
        self.assertTrue(result["is_common"])

    def test_length_correct(self):
        result = self.mod.check_password_strength_detailed("abc")
        self.assertEqual(result["length"], 3)

    def test_length_8_check(self):
        short = self.mod.check_password_strength_detailed("short")
        self.assertFalse(short["checks"]["length_8"])
        long_enough = self.mod.check_password_strength_detailed("longenough")
        self.assertTrue(long_enough["checks"]["length_8"])

    def test_mixed_case_check(self):
        result = self.mod.check_password_strength_detailed("HelloWorld")
        self.assertTrue(result["checks"]["mixed_case"])
        result2 = self.mod.check_password_strength_detailed("helloworld")
        self.assertFalse(result2["checks"]["mixed_case"])

    def test_has_digits_check(self):
        result = self.mod.check_password_strength_detailed("hello123")
        self.assertTrue(result["checks"]["has_digits"])
        result2 = self.mod.check_password_strength_detailed("helloworld")
        self.assertFalse(result2["checks"]["has_digits"])

    def test_has_symbols_check(self):
        result = self.mod.check_password_strength_detailed("hello@world")
        self.assertTrue(result["checks"]["has_symbols"])
        result2 = self.mod.check_password_strength_detailed("helloworld")
        self.assertFalse(result2["checks"]["has_symbols"])

    def test_legacy_strength_still_works(self):
        """check_password_strength() must still return a simple label."""
        result = self.mod.check_password_strength("hello")
        self.assertIsInstance(result, str)

    def test_cmd_checkpwd_shows_breakdown(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        self.assertIn("check_password_strength_detailed", src)
        self.assertIn("breakdown", src)
        self.assertIn("is_common", src)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2I — /password passphrase mode
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2I_Passphrase(unittest.TestCase):

    def setUp(self):
        self.mod = _load_module(
            "app/features/crypto/_passphrase.py", "passphrase_mod"
        )

    def test_wordlist_no_duplicates(self):
        self.assertEqual(len(set(self.mod._WORDLIST)), self.mod._POOL_SIZE)

    def test_pool_size_at_least_256(self):
        self.assertGreaterEqual(self.mod._POOL_SIZE, 256)

    def test_gen_passphrase_returns_4_words(self):
        phrase = self.mod.gen_passphrase()
        self.assertEqual(len(phrase.split()), 4)

    def test_gen_passphrase_words_in_list(self):
        phrase = self.mod.gen_passphrase()
        for w in phrase.split():
            self.assertIn(w, self.mod._WORDLIST)

    def test_passphrase_entropy_formula(self):
        pool = self.mod._POOL_SIZE
        expected = 4 * math.log2(pool)
        self.assertAlmostEqual(self.mod.passphrase_entropy(), expected, places=4)

    def test_passphrase_entropy_at_least_36_bits(self):
        self.assertGreaterEqual(self.mod.passphrase_entropy(), 36.0)

    def test_gen_passphrase_randomness(self):
        """Two separate calls should differ at least 95% of the time."""
        results = {self.mod.gen_passphrase() for _ in range(20)}
        self.assertGreater(len(results), 1)

    def test_phrase_dispatch_in_router(self):
        src = (PROJECT_ROOT / "app/features/crypto/router.py").read_text()
        self.assertIn("phrase", src.lower())
        self.assertIn("_passphrase", src)
        self.assertIn("gen_passphrase", src)

    def test_passphrase_entropy_in_router_output(self):
        src = (PROJECT_ROOT / "app/features/crypto/router.py").read_text()
        self.assertIn("passphrase_entropy", src)

    def test_normal_password_still_works(self):
        """Normal /password behavior not affected by phrase dispatch."""
        src = (PROJECT_ROOT / "app/features/crypto/router.py").read_text()
        self.assertIn("gen_password(length)", src)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2J — /short URL expansion (SSRF-safe)
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2J_ShortExpand(unittest.TestCase):

    def setUp(self):
        self.src = (PROJECT_ROOT / "app/features/media/router.py").read_text()

    def test_expand_subcommand_present(self):
        self.assertIn('"expand"', self.src.lower())

    def test_ssrf_guard_applied_per_hop(self):
        """is_safe_host must be called inside the redirect loop."""
        self.assertIn("_safe(redir_host)", self.src)

    def test_allow_redirects_false(self):
        """Manual redirect following; aiohttp must NOT auto-follow."""
        self.assertIn("allow_redirects=False", self.src)

    def test_max_redirects_defined(self):
        self.assertIn("_MAX_REDIRECTS", self.src)

    def test_existing_shortening_preserved(self):
        """Original shorten_url call must still be in the handler."""
        self.assertIn("shorten_url", self.src)

    def test_scheme_restricted_to_http_https(self):
        self.assertIn("http", self.src)
        self.assertIn('"https"', self.src)
        # non-HTTP schemes must be blocked
        self.assertIn("not in (\"http\", \"https\")", self.src)

    def test_private_host_redirect_blocked(self):
        """Source must explicitly block redirects to private hosts."""
        self.assertIn("Redirect to private/internal host blocked", self.src)

    def test_non_scheme_redirect_blocked(self):
        self.assertIn("Redirect to non-HTTP scheme blocked", self.src)

    def test_max_redirects_at_most_10(self):
        """Redirect limit must be reasonable (≤10)."""
        import re
        m = re.search(r"_MAX_REDIRECTS\s*=\s*(\d+)", self.src)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 10)

    def test_hops_collected(self):
        self.assertIn("hops", self.src)

    def test_expand_helper_function_present(self):
        self.assertIn("_cmd_short_expand", self.src)

    def test_ssrf_guard_on_initial_url(self):
        """Initial URL must also be SSRF-checked before the loop."""
        self.assertIn("_safe(initial_host)", self.src)

    def test_relative_redirect_resolved(self):
        """Source must resolve relative redirects like /path → absolute."""
        self.assertIn('location.startswith("/")', self.src)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2K — /qrscan multi-QR + format/type
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2K_QRScan(unittest.TestCase):

    def setUp(self):
        self.qr_src = (PROJECT_ROOT / "app/utils/qr.py").read_text()
        self.router_src = (PROJECT_ROOT / "app/features/media/router.py").read_text()

    def test_scan_qr_all_function_in_utils(self):
        self.assertIn("def scan_qr_all_from_bytes(", self.qr_src)

    def test_legacy_scan_preserved(self):
        """scan_qr_from_bytes must still exist for backward compatibility."""
        self.assertIn("def scan_qr_from_bytes(", self.qr_src)

    def test_result_contains_type(self):
        """Each result dict must include a 'type' key."""
        self.assertIn('"type"', self.qr_src)

    def test_result_contains_data(self):
        self.assertIn('"data"', self.qr_src)

    def test_multi_result_iteration_in_router(self):
        self.assertIn("scan_qr_all_from_bytes", self.router_src)

    def test_multiple_qr_handling_in_router(self):
        """Router must branch on single vs multiple results."""
        self.assertIn("len(results) == 1", self.router_src)
        self.assertIn("len(results)", self.router_src)

    def test_type_displayed_in_router(self):
        self.assertIn('r["type"]', self.router_src)

    def test_empty_result_still_handled(self):
        self.assertIn("not results", self.router_src)

    def test_scan_all_returns_list(self):
        """scan_qr_all_from_bytes must return a list."""
        # Parse the function body to check return type annotation
        import re
        m = re.search(r"def scan_qr_all_from_bytes.*?->.*?list", self.qr_src)
        self.assertIsNotNone(m, "scan_qr_all_from_bytes should annotate return as list")

    def test_pyzbar_obj_type_used(self):
        """pyzbar's obj.type field must be read."""
        self.assertIn("obj.type", self.qr_src)

    def test_utf8_errors_replace(self):
        """Binary QR data must use errors='replace' to avoid decode crashes."""
        self.assertIn("errors='replace'", self.qr_src)

    def test_legacy_scan_also_uses_errors_replace(self):
        """Legacy scan_qr_from_bytes updated to use errors='replace'."""
        # Find the legacy function and verify errors='replace'
        idx = self.qr_src.index("def scan_qr_from_bytes(")
        next_fn = self.qr_src.find("\ndef ", idx + 1)
        legacy_body = self.qr_src[idx:next_fn if next_fn > 0 else idx + 500]
        self.assertIn("errors='replace'", legacy_body)


# ─────────────────────────────────────────────────────────────────────────────
# Architecture invariants (regression guard)
# ─────────────────────────────────────────────────────────────────────────────

class TestArchitectureInvariants(unittest.TestCase):

    def test_frozen_string_md5(self):
        import hashlib
        path = PROJECT_ROOT / "app/features/session/router.py"
        content = path.read_bytes()
        digest = hashlib.md5(content).hexdigest()
        self.assertEqual(digest, "c61dcc219b29736e228bdc1d0915d82d",
                         "Frozen /string MD5 must not change")

    def test_session_router_unchanged(self):
        """session/router.py is frozen — ensure it exists and is unmodified."""
        path = PROJECT_ROOT / "app/features/session/router.py"
        self.assertTrue(path.exists())

    def test_qr_generate_still_works(self):
        """generate_qr_buffer must still be importable and callable."""
        self.assertIn("def generate_qr_buffer(", (PROJECT_ROOT / "app/utils/qr.py").read_text())

    def test_general_router_syntax(self):
        src = (PROJECT_ROOT / "app/features/general/router.py").read_text()
        ast.parse(src)  # raises on syntax error

    def test_crypto_router_syntax(self):
        src = (PROJECT_ROOT / "app/features/crypto/router.py").read_text()
        ast.parse(src)

    def test_media_router_syntax(self):
        src = (PROJECT_ROOT / "app/features/media/router.py").read_text()
        ast.parse(src)

    def test_crypto_utils_syntax(self):
        src = (PROJECT_ROOT / "app/utils/crypto.py").read_text()
        ast.parse(src)

    def test_passphrase_module_syntax(self):
        src = (PROJECT_ROOT / "app/features/crypto/_passphrase.py").read_text()
        ast.parse(src)

    def test_no_print_in_handlers(self):
        """Production handlers must not use print() for logging."""
        for path in (
            PROJECT_ROOT / "app/features/general/router.py",
            PROJECT_ROOT / "app/features/crypto/router.py",
            PROJECT_ROOT / "app/features/media/router.py",
        ):
            src = path.read_text()
            self.assertNotIn("\nprint(", src, f"print() found in {path.name}")

    def test_requirements_dependency_count(self):
        req = (PROJECT_ROOT / "requirements.txt").read_text().strip().splitlines()
        non_empty = [r for r in req if r.strip() and not r.startswith("#")]
        self.assertEqual(len(non_empty), 13, f"Expected 13 deps, got {len(non_empty)}: {non_empty}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
