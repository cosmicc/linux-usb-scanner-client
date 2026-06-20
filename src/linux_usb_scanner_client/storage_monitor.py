"""Storage capacity checks for the persistent queue volume."""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageStatus:
    """Disk capacity and queue database size details."""

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    database_bytes: int
    min_free_bytes: int
    low_space: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly dictionary."""

        return asdict(self)


def build_storage_status(
    database_path: Path | str, min_free_mb: int
) -> StorageStatus:
    """Return capacity details for the filesystem that stores the queue."""

    database = Path(database_path)
    target = _existing_storage_path(database)
    usage = shutil.disk_usage(target)
    database_bytes = _database_file_bytes(database)
    min_free_bytes = max(0, int(min_free_mb) * 1024 * 1024)
    return StorageStatus(
        path=str(target),
        total_bytes=int(usage.total),
        used_bytes=int(usage.used),
        free_bytes=int(usage.free),
        database_bytes=database_bytes,
        min_free_bytes=min_free_bytes,
        low_space=usage.free < min_free_bytes,
    )


def _existing_storage_path(database_path: Path) -> Path:
    """Return an existing path suitable for disk usage checks."""

    candidates = [database_path.parent, *database_path.parents]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("/")


def _database_file_bytes(database_path: Path) -> int:
    """Return the queue database footprint, including SQLite sidecar files."""

    total = 0
    for path in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total
