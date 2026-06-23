"""Tests for automatic update behavior that does not touch systemd."""

from __future__ import annotations

import tempfile
import unittest
import subprocess
import shutil
from pathlib import Path

from linux_usb_scanner_client.auto_update import AutoUpdater, format_update_result
from linux_usb_scanner_client.config import load_config


class AutoUpdateTests(unittest.TestCase):
    """Auto-update tests."""

    def test_disabled_update_does_not_require_git_or_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _write_config(Path(temp_dir))
            result = AutoUpdater(config).run()

        self.assertEqual(result.state, "disabled")
        self.assertFalse(result.update_available)
        self.assertFalse(result.updated)

    def test_format_update_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _write_config(Path(temp_dir))
            result = AutoUpdater(config).run()

        output = format_update_result(result)

        self.assertIn("Update state: disabled", output)
        self.assertIn("Installed version: 0.1.4", output)

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_check_only_detects_newer_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "remote"
            repo.mkdir()
            _git(["init", "-b", "main"], cwd=repo)
            (repo / "pyproject.toml").write_text(
                """
[project]
version = "0.1.5"
""",
                encoding="utf-8",
            )
            _git(["add", "pyproject.toml"], cwd=repo)
            _git(
                [
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=repo,
            )
            config = _write_config(root, updates_enabled=True, repository_url=str(repo))

            result = AutoUpdater(config).run(check_only=True)

        self.assertEqual(result.state, "update_available")
        self.assertEqual(result.remote_version, "0.1.5")
        self.assertTrue(result.update_available)


def _write_config(
    temp_dir: Path,
    *,
    updates_enabled: bool = False,
    repository_url: str = "https://github.com/cosmicc/linux-usb-scanner-client.git",
):
    path = temp_dir / "client.conf"
    path.write_text(
        f"""
[scanner]
device_path = /dev/input/event9

[buffer]
database_path = {temp_dir / "queue.sqlite3"}

[logging]
log_file = {temp_dir / "client.log"}

[updates]
enabled = {"true" if updates_enabled else "false"}
repository_url = {repository_url}
branch = main
""",
        encoding="utf-8",
    )
    return load_config(path)


def _git(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
