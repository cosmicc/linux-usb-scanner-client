"""Automatic update workflow for installed systemd deployments."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import AppConfig
from .storage import ScanStore
from .timeutil import utc_timestamp
from .versioning import VersionError, is_newer_version, parse_project_version


class AutoUpdateError(RuntimeError):
    """Raised when an update check or install fails."""


@dataclass(frozen=True)
class AutoUpdateResult:
    """Result from an update check or update application."""

    state: str
    local_version: str
    remote_version: str | None = None
    remote_commit: str | None = None
    update_available: bool = False
    updated: bool = False
    message: str = ""


class AutoUpdater:
    """Check GitHub main for newer versions and apply updates safely."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.store = ScanStore(config.buffer.database_path)

    def run(self, *, check_only: bool = False, force: bool = False) -> AutoUpdateResult:
        """Run an update check, and optionally apply the newer version."""

        try:
            self.store.initialize()
        except OSError as exc:
            raise AutoUpdateError(
                f"Unable to open update status database {self.config.buffer.database_path}: {exc}"
            ) from exc
        if not self.config.updates.enabled and not force:
            result = AutoUpdateResult(
                state="disabled",
                local_version=__version__,
                message="Auto-update is disabled in config.",
            )
            self._persist_result(result)
            return result

        self._set_status(
            {
                "update_state": "checking",
                "last_update_check_at": utc_timestamp(),
                "installed_version": __version__,
                "update_error": "",
            }
        )

        self._require_tool("git")
        checkout_dir = self._refresh_checkout()
        remote_version = self._read_checkout_version(checkout_dir)
        remote_commit = self._git(["rev-parse", "HEAD"], cwd=checkout_dir).stdout.strip()
        update_available = is_newer_version(remote_version, __version__)

        if check_only:
            result = AutoUpdateResult(
                state="update_available" if update_available else "up_to_date",
                local_version=__version__,
                remote_version=remote_version,
                remote_commit=remote_commit,
                update_available=update_available,
                message=(
                    "A newer version is available."
                    if update_available
                    else "Installed version is current."
                ),
            )
            self._persist_result(result)
            return result

        if not update_available and not force:
            result = AutoUpdateResult(
                state="up_to_date",
                local_version=__version__,
                remote_version=remote_version,
                remote_commit=remote_commit,
                update_available=False,
                message="Installed version is current.",
            )
            self._persist_result(result)
            return result

        if os.geteuid() != 0:
            raise AutoUpdateError("Applying updates must be run as root.")
        self._require_tool("systemctl")
        self._require_tool("bash")

        self._set_status(
            {
                "update_state": "updating",
                "update_remote_version": remote_version,
                "update_remote_commit": remote_commit,
            }
        )
        try:
            self._systemctl(["stop", self.config.updates.service_name], check=False)
            install_script = checkout_dir / "scripts" / "install.sh"
            if not install_script.exists():
                raise AutoUpdateError(f"Install script not found: {install_script}")
            self._run(["bash", str(install_script)], cwd=checkout_dir)
        except Exception as exc:
            self._set_status(
                {
                    "update_state": "failed",
                    "update_error": str(exc)[:500],
                    "last_update_error_at": utc_timestamp(),
                }
            )
            self._systemctl(["start", self.config.updates.service_name], check=False)
            raise

        result = AutoUpdateResult(
            state="updated",
            local_version=__version__,
            remote_version=remote_version,
            remote_commit=remote_commit,
            update_available=update_available,
            updated=True,
            message=(
                f"Updated to {remote_version}."
                if update_available
                else f"Reinstalled {remote_version} from configured branch."
            ),
        )
        self._persist_result(result)
        return result

    def _refresh_checkout(self) -> Path:
        update_root = self.config.buffer.database_path.parent / "updates"
        checkout_dir = update_root / "linux-usb-scanner-client"
        update_root.mkdir(parents=True, exist_ok=True)
        try:
            update_root.chmod(0o700)
        except PermissionError:
            pass

        if (checkout_dir / ".git").exists():
            self._git(
                ["remote", "set-url", "origin", self.config.updates.repository_url],
                cwd=checkout_dir,
            )
            self._git(
                ["fetch", "--depth", "1", "origin", self.config.updates.branch],
                cwd=checkout_dir,
            )
            self._git(["reset", "--hard", "FETCH_HEAD"], cwd=checkout_dir)
            return checkout_dir

        if checkout_dir.exists():
            shutil.rmtree(checkout_dir)
        self._git(
            [
                "clone",
                "--depth",
                "1",
                "--branch",
                self.config.updates.branch,
                self.config.updates.repository_url,
                str(checkout_dir),
            ],
            cwd=update_root,
        )
        return checkout_dir

    def _read_checkout_version(self, checkout_dir: Path) -> str:
        pyproject_path = checkout_dir / "pyproject.toml"
        try:
            pyproject_text = pyproject_path.read_text(encoding="utf-8")
            return parse_project_version(pyproject_text)
        except (OSError, VersionError) as exc:
            raise AutoUpdateError(f"Unable to read remote project version: {exc}") from exc

    def _git(
        self, args: list[str], *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self._run(["git", *args], cwd=cwd)

    def _systemctl(self, args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return self._run(["systemctl", *args], check=check)

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise AutoUpdateError(
                f"Command failed ({completed.returncode}): {' '.join(command)}"
                + (f": {message}" if message else "")
            )
        return completed

    def _require_tool(self, name: str) -> None:
        if shutil.which(name) is None:
            raise AutoUpdateError(f"Required command not found: {name}")

    def _persist_result(self, result: AutoUpdateResult) -> None:
        values = {
            "update_state": result.state,
            "installed_version": result.local_version,
            "update_message": result.message,
            "last_update_check_at": utc_timestamp(),
        }
        if result.remote_version:
            values["update_remote_version"] = result.remote_version
        if result.remote_commit:
            values["update_remote_commit"] = result.remote_commit
        self._set_status(values)

    def _set_status(self, values: dict[str, str]) -> None:
        self.store.set_status_many(values)


def format_update_result(result: AutoUpdateResult) -> str:
    """Format an update result for CLI output."""

    lines = [
        f"Update state: {result.state}",
        f"Installed version: {result.local_version}",
    ]
    if result.remote_version:
        lines.append(f"Remote version: {result.remote_version}")
    if result.remote_commit:
        lines.append(f"Remote commit: {result.remote_commit}")
    lines.append(f"Update available: {'yes' if result.update_available else 'no'}")
    lines.append(f"Updated: {'yes' if result.updated else 'no'}")
    if result.message:
        lines.append(f"Message: {result.message}")
    return "\n".join(lines)
