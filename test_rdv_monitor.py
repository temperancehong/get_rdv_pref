import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdv_monitor import (
    Slot,
    build_email,
    extract_slot_labels_from_text,
    load_seen,
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


if __name__ == "__main__":
    unittest.main()
