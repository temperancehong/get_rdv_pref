import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from captcha_ocr import clean_prediction
from rdv_monitor import (
    Slot,
    assist_security_code_with_ocr,
    build_captcha_alert_message,
    build_email,
    env_flag,
    extract_slot_labels_from_text,
    load_seen,
    page_says_blocked,
    parse_args,
    save_seen,
)


class SlotParserTests(unittest.TestCase):
    def test_no_slot_message_returns_empty_list(self):
        text = "Aucun créneau disponible pour cette démarche."
        self.assertEqual(extract_slot_labels_from_text(text), [])

    def test_extracts_date_and_time_lines(self):
        text = """
        Choisissez votre créneau
        Mardi 12 mai 2026 à 09:30
        Mercredi 13 mai 2026 14h00
        """
        self.assertEqual(
            extract_slot_labels_from_text(text),
            ["Mardi 12 mai 2026 à 09:30", "Mercredi 13 mai 2026 14h00"],
        )


class SeenSlotTests(unittest.TestCase):
    def test_seen_slots_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seen_slots.json"
            save_seen(path, {"b", "a", "a"})
            self.assertEqual(load_seen(path), {"a", "b"})


class EmailTests(unittest.TestCase):
    def test_build_email_contains_slot_details(self):
        slot = Slot(
            demarche_id="2246",
            demarche_name="Guichet 12",
            label="Mardi 12 mai 2026 à 09:30",
            page_url="https://example.test/creneau",
        )
        with patch.dict(os.environ, {"SMTP_USER": "sender@example.test"}):
            message = build_email([slot], "recipient@example.test")

        self.assertEqual(message["To"], "recipient@example.test")
        body = message.get_content()
        self.assertIn("Guichet 12", body)
        self.assertIn("Mardi 12 mai 2026 à 09:30", body)


class ArgumentTests(unittest.TestCase):
    def test_captcha_ocr_mode_defaults_to_off(self):
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(["--once"])
        self.assertEqual(args.captcha_ocr_mode, "off")

    def test_captcha_ocr_mode_accepts_fill(self):
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(["--once", "--captcha-ocr-mode", "fill"])
        self.assertEqual(args.captcha_ocr_mode, "fill")

    def test_safety_delays_have_conservative_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(["--once"])
        self.assertEqual(args.demarche_delay_seconds, 30)
        self.assertEqual(args.block_backoff_minutes, 120)

    def test_telegram_captcha_alert_defaults_to_off(self):
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(["--once"])
        self.assertFalse(args.telegram_captcha_alert)

    def test_telegram_captcha_alert_can_read_env(self):
        with patch.dict(os.environ, {"TELEGRAM_CAPTCHA_ALERT": "true"}, clear=True):
            args = parse_args(["--once"])
        self.assertTrue(args.telegram_captcha_alert)


class EnvFlagTests(unittest.TestCase):
    def test_env_flag_handles_common_truthy_values(self):
        with patch.dict(os.environ, {"EXAMPLE_FLAG": "yes"}, clear=True):
            self.assertTrue(env_flag("EXAMPLE_FLAG"))

    def test_env_flag_handles_missing_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(env_flag("EXAMPLE_FLAG"))


class BlockDetectionTests(unittest.TestCase):
    def test_detects_common_block_messages(self):
        self.assertTrue(page_says_blocked("Accès refusé"))
        self.assertTrue(page_says_blocked("Too many requests"))
        self.assertTrue(page_says_blocked("activité suspecte détectée"))

    def test_does_not_treat_no_slot_message_as_block(self):
        self.assertFalse(
            page_says_blocked("Il n'existe plus de plage horaire libre.")
        )


class CaptchaOCRTests(unittest.TestCase):
    def test_clean_prediction_removes_whitespace(self):
        self.assertEqual(clean_prediction(" A b 1 2 \n"), "Ab12")


class TelegramAlertTests(unittest.TestCase):
    def test_captcha_alert_message_contains_demarche_and_url(self):
        message = build_captcha_alert_message(
            {
                "id": "2282",
                "name": "Remise de titre - Palaiseau - Guichet 13",
            },
            "https://example.test/captcha",
        )

        self.assertIn("Guichet 13", message)
        self.assertIn("2282", message)
        self.assertIn("https://example.test/captcha", message)


class FakeElement:
    def __init__(self, *, screenshot_bytes: bytes | None = None):
        self.screenshot_bytes = screenshot_bytes
        self.filled_value = None
        self.clicked = False

    async def is_visible(self, timeout=0):
        return True

    async def screenshot(self, timeout=0):
        return self.screenshot_bytes or b""

    async def fill(self, value, timeout=0):
        self.filled_value = value

    async def click(self, timeout=0):
        self.clicked = True


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    async def count(self):
        return len(self.elements)

    def nth(self, index):
        return self.elements[index]


class FakePage:
    def __init__(self):
        self.image = FakeElement(screenshot_bytes=b"captcha image")
        self.input = FakeElement()
        self.submit = FakeElement()

    def locator(self, selector):
        if selector.startswith("img["):
            return FakeLocator([self.image])
        if selector.startswith("input["):
            return FakeLocator([self.input])
        if selector.startswith("button"):
            return FakeLocator([self.submit])
        return FakeLocator([])


class CaptchaBrowserAssistTests(unittest.IsolatedAsyncioTestCase):
    async def test_fill_mode_screenshots_and_fills_without_submitting(self):
        page = FakePage()

        with patch("captcha_ocr.predict_captcha_bytes", return_value=" A b 1 2 "):
            await assist_security_code_with_ocr(page, "fill")

        self.assertEqual(page.input.filled_value, "Ab12")
        self.assertFalse(page.submit.clicked)


if __name__ == "__main__":
    unittest.main()
