"""Keyboard event decoding and scan frame accumulation."""

from __future__ import annotations

from dataclasses import dataclass

SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}
ENTER_KEYS = {"KEY_ENTER", "KEY_KPENTER"}

LETTER_KEYS = {f"KEY_{chr(code)}": chr(code).lower() for code in range(ord("A"), ord("Z") + 1)}

UNSHIFTED_KEYS = {
    **LETTER_KEYS,
    "KEY_1": "1",
    "KEY_2": "2",
    "KEY_3": "3",
    "KEY_4": "4",
    "KEY_5": "5",
    "KEY_6": "6",
    "KEY_7": "7",
    "KEY_8": "8",
    "KEY_9": "9",
    "KEY_0": "0",
    "KEY_MINUS": "-",
    "KEY_EQUAL": "=",
    "KEY_LEFTBRACE": "[",
    "KEY_RIGHTBRACE": "]",
    "KEY_BACKSLASH": "\\",
    "KEY_SEMICOLON": ";",
    "KEY_APOSTROPHE": "'",
    "KEY_GRAVE": "`",
    "KEY_COMMA": ",",
    "KEY_DOT": ".",
    "KEY_SLASH": "/",
    "KEY_SPACE": " ",
    "KEY_TAB": "\t",
    "KEY_KP0": "0",
    "KEY_KP1": "1",
    "KEY_KP2": "2",
    "KEY_KP3": "3",
    "KEY_KP4": "4",
    "KEY_KP5": "5",
    "KEY_KP6": "6",
    "KEY_KP7": "7",
    "KEY_KP8": "8",
    "KEY_KP9": "9",
    "KEY_KPDOT": ".",
    "KEY_KPMINUS": "-",
    "KEY_KPPLUS": "+",
    "KEY_KPSLASH": "/",
    "KEY_KPASTERISK": "*",
}

SHIFTED_KEYS = {
    **{key: value.upper() for key, value in LETTER_KEYS.items()},
    "KEY_1": "!",
    "KEY_2": "@",
    "KEY_3": "#",
    "KEY_4": "$",
    "KEY_5": "%",
    "KEY_6": "^",
    "KEY_7": "&",
    "KEY_8": "*",
    "KEY_9": "(",
    "KEY_0": ")",
    "KEY_MINUS": "_",
    "KEY_EQUAL": "+",
    "KEY_LEFTBRACE": "{",
    "KEY_RIGHTBRACE": "}",
    "KEY_BACKSLASH": "|",
    "KEY_SEMICOLON": ":",
    "KEY_APOSTROPHE": '"',
    "KEY_GRAVE": "~",
    "KEY_COMMA": "<",
    "KEY_DOT": ">",
    "KEY_SLASH": "?",
    "KEY_SPACE": " ",
    "KEY_TAB": "\t",
}


class KeyboardDecoder:
    """Convert Linux key codes into text for keyboard-wedge scanner input."""

    def __init__(self) -> None:
        self._shift_pressed = False
        self._caps_lock = False

    def feed_key(self, keycode: str | list[str], value: int) -> str | None:
        """Feed one evdev key event and return a character, newline, or None.

        `value` follows Linux input semantics: 1 is key down, 0 is key up, and 2
        is key hold/repeat. Repeats are ignored so a held key does not create
        duplicate scan characters.
        """

        normalized = self._normalize_keycode(keycode)
        if normalized in SHIFT_KEYS:
            self._shift_pressed = value in {1, 2}
            return None

        if value != 1:
            return None

        if normalized == "KEY_CAPSLOCK":
            self._caps_lock = not self._caps_lock
            return None

        if normalized in ENTER_KEYS:
            return "\n"

        if normalized == "KEY_BACKSPACE":
            return "\b"

        shifted = self._shift_pressed
        if normalized in LETTER_KEYS and self._caps_lock:
            shifted = not shifted

        mapping = SHIFTED_KEYS if shifted else UNSHIFTED_KEYS
        return mapping.get(normalized)

    @staticmethod
    def _normalize_keycode(keycode: str | list[str]) -> str:
        if isinstance(keycode, list):
            return keycode[0] if keycode else ""
        return keycode


@dataclass(frozen=True)
class CompletedScan:
    """A completed scanner frame."""

    barcode: str
    length: int


class ScanAccumulator:
    """Accumulate decoded keyboard characters until a CR/LF terminator arrives."""

    def __init__(self, max_chars: int, send_empty_scans: bool = False) -> None:
        self.max_chars = max_chars
        self.send_empty_scans = send_empty_scans
        self._buffer: list[str] = []
        self._dropping_oversized = False

    @property
    def buffered_length(self) -> int:
        """Return the current buffered frame length."""

        return len(self._buffer)

    def feed_character(self, character: str) -> CompletedScan | None:
        """Feed one decoded character and return a completed scan when ready."""

        if character == "\b":
            if self._buffer:
                self._buffer.pop()
            return None

        if character == "\n":
            barcode = "".join(self._buffer).strip()
            self._buffer.clear()
            was_dropping = self._dropping_oversized
            self._dropping_oversized = False
            if was_dropping:
                return None
            if barcode or self.send_empty_scans:
                return CompletedScan(barcode=barcode, length=len(barcode))
            return None

        if self._dropping_oversized:
            return None

        self._buffer.append(character)
        if len(self._buffer) > self.max_chars:
            self._buffer.clear()
            self._dropping_oversized = True
        return None

