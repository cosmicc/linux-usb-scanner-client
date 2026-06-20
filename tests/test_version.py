"""Tests for release version consistency."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from linux_usb_scanner_client import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VersionTests(unittest.TestCase):
    """Version consistency tests."""

    def test_project_version_matches_package_version(self) -> None:
        pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_version = _project_version(pyproject_text)

        self.assertEqual(project_version, "0.1.0")
        self.assertEqual(__version__, project_version)

    def test_cli_prints_package_version(self) -> None:
        from linux_usb_scanner_client.cli import main

        original_stdout = sys.stdout
        try:
            from io import StringIO

            captured = StringIO()
            sys.stdout = captured
            exit_code = main(["--version"])
        finally:
            sys.stdout = original_stdout

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured.getvalue().strip(), __version__)


def _project_version(pyproject_text: str) -> str:
    in_project_section = False
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project_section = True
            continue
        if in_project_section and stripped.startswith("["):
            break
        if in_project_section and stripped.startswith("version"):
            _, value = stripped.split("=", 1)
            return value.strip().strip('"')
    raise AssertionError("project.version not found in pyproject.toml")


if __name__ == "__main__":
    unittest.main()
