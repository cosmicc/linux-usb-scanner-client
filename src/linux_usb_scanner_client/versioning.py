"""Version parsing helpers for package and auto-update checks."""

from __future__ import annotations

import re

VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){1,3}$")


class VersionError(ValueError):
    """Raised when a version string cannot be compared safely."""


def parse_project_version(pyproject_text: str) -> str:
    """Extract `project.version` from a pyproject.toml document."""

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
    raise VersionError("project.version not found in pyproject.toml")


def compare_versions(left: str, right: str) -> int:
    """Compare two dotted numeric versions.

    Returns 1 when left is newer, -1 when right is newer, and 0 when equal.
    """

    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    max_length = max(len(left_parts), len(right_parts))
    normalized_left = left_parts + (0,) * (max_length - len(left_parts))
    normalized_right = right_parts + (0,) * (max_length - len(right_parts))
    if normalized_left > normalized_right:
        return 1
    if normalized_left < normalized_right:
        return -1
    return 0


def is_newer_version(candidate: str, current: str) -> bool:
    """Return whether candidate is newer than current."""

    return compare_versions(candidate, current) > 0


def _version_parts(version: str) -> tuple[int, ...]:
    if not VERSION_PATTERN.fullmatch(version):
        raise VersionError(f"unsupported version format: {version}")
    return tuple(int(part) for part in version.split("."))
