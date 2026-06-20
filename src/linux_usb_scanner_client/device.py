"""Linux input-device discovery for USB keyboard-wedge scanners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ScannerConfig


class DeviceError(RuntimeError):
    """Raised when input devices cannot be inspected."""


@dataclass(frozen=True)
class KeyboardDeviceInfo:
    """Metadata for a keyboard-like Linux input device."""

    path: str
    name: str
    phys: str
    vendor_id: int
    product_id: int
    version: int
    is_keyboard_like: bool

    @property
    def vendor_hex(self) -> str:
        """Return the vendor ID as a four-digit hex string."""

        return f"0x{self.vendor_id:04x}"

    @property
    def product_hex(self) -> str:
        """Return the product ID as a four-digit hex string."""

        return f"0x{self.product_id:04x}"


def list_keyboard_devices() -> list[KeyboardDeviceInfo]:
    """Return keyboard-like Linux input devices visible to the current user."""

    evdev = _load_evdev()
    devices: list[KeyboardDeviceInfo] = []
    for path in evdev.list_devices():
        device = None
        try:
            device = evdev.InputDevice(path)
            info = _device_info(evdev, device)
        except OSError:
            continue
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass
        if info.is_keyboard_like:
            devices.append(info)
    return sorted(devices, key=lambda item: item.path)


def find_matching_devices(config: ScannerConfig) -> list[KeyboardDeviceInfo]:
    """Return keyboard devices matching the configured scanner selector."""

    if not config.has_matcher:
        return []
    return [
        device
        for device in list_keyboard_devices()
        if matches_device(device, config)
    ]


def matches_device(device: KeyboardDeviceInfo, config: ScannerConfig) -> bool:
    """Return whether a discovered device matches scanner config."""

    if config.device_path and Path(device.path) != Path(config.device_path):
        return False
    if config.vendor_id is not None and device.vendor_id != config.vendor_id:
        return False
    if config.product_id is not None and device.product_id != config.product_id:
        return False
    if config.device_name and config.device_name.lower() not in device.name.lower():
        return False
    return True


def open_input_device(path: str) -> Any:
    """Open an evdev InputDevice by path."""

    evdev = _load_evdev()
    return evdev.InputDevice(path)


def categorize_key_event(event: Any) -> Any:
    """Convert a raw evdev event to a categorized key event."""

    evdev = _load_evdev()
    return evdev.categorize(event)


def is_key_event(event: Any) -> bool:
    """Return whether an evdev event is a key event."""

    evdev = _load_evdev()
    return event.type == evdev.ecodes.EV_KEY


def _load_evdev() -> Any:
    try:
        import evdev
    except ImportError as exc:
        raise DeviceError(
            "The evdev package is required. Install dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return evdev


def _device_info(evdev: Any, device: Any) -> KeyboardDeviceInfo:
    capabilities = device.capabilities().get(evdev.ecodes.EV_KEY, [])
    keys = set(capabilities)
    keyboard_like = evdev.ecodes.KEY_ENTER in keys and any(
        key in keys
        for key in (
            evdev.ecodes.KEY_0,
            evdev.ecodes.KEY_1,
            evdev.ecodes.KEY_KP0,
            evdev.ecodes.KEY_KP1,
        )
    )
    return KeyboardDeviceInfo(
        path=device.path,
        name=device.name or "",
        phys=device.phys or "",
        vendor_id=int(device.info.vendor),
        product_id=int(device.info.product),
        version=int(device.info.version),
        is_keyboard_like=keyboard_like,
    )
