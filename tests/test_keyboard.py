"""Tests for keyboard decoding and scan accumulation."""

from __future__ import annotations

import unittest

from linux_usb_scanner_client.keyboard import KeyboardDecoder, ScanAccumulator


class KeyboardTests(unittest.TestCase):
    """Keyboard event handling tests."""

    def test_decodes_digits_until_enter(self) -> None:
        decoder = KeyboardDecoder()
        accumulator = ScanAccumulator(max_chars=10)
        completed = None

        for key in ["KEY_1", "KEY_2", "KEY_3", "KEY_ENTER"]:
            char = decoder.feed_key(key, 1)
            if char is not None:
                completed = accumulator.feed_character(char)

        self.assertIsNotNone(completed)
        self.assertEqual(completed.barcode, "123")

    def test_shifted_aim_prefix_characters(self) -> None:
        decoder = KeyboardDecoder()
        chars = []
        decoder.feed_key("KEY_LEFTSHIFT", 1)
        chars.append(decoder.feed_key("KEY_RIGHTBRACE", 1))
        decoder.feed_key("KEY_LEFTSHIFT", 0)
        chars.append(decoder.feed_key("KEY_C", 1))

        self.assertEqual("".join(char for char in chars if char), "}c")

    def test_oversized_scan_is_dropped_until_enter(self) -> None:
        accumulator = ScanAccumulator(max_chars=2)

        self.assertIsNone(accumulator.feed_character("1"))
        self.assertIsNone(accumulator.feed_character("2"))
        self.assertIsNone(accumulator.feed_character("3"))
        self.assertIsNone(accumulator.feed_character("\n"))

        self.assertIsNone(accumulator.feed_character("4"))
        completed = accumulator.feed_character("\n")
        self.assertIsNotNone(completed)
        self.assertEqual(completed.barcode, "4")


if __name__ == "__main__":
    unittest.main()

