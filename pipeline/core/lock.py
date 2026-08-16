"""A portable, blocking-free file lock for the sync pipeline.

Prevents two sync processes from writing the database concurrently (spec §19 /
T1.8). Uses advisory locks: ``fcntl.flock`` on POSIX, ``msvcrt.locking`` on
Windows — both standard-library, so no new dependency.

Usage::

    with sync_lock(DATA_DIR / ".sync.lock"):
        ...  # build + publish candidate

The lock is non-blocking: if another process holds it we raise
``SyncLockError`` immediately instead of waiting forever.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class SyncLockError(RuntimeError):
    """Raised when the sync lock is already held by another process."""


class SyncLock:
    """Non-blocking exclusive lock backed by an OS advisory file lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Any = None

    def __enter__(self) -> SyncLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # a+ keeps the file around; ensure it holds at least one byte so the
        # Windows byte-range lock has a region to lock.
        self._fh = open(self.path, "a+", encoding="utf-8")
        try:
            if self._fh.tell() == 0:
                self._fh.write("0")
                self._fh.flush()
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise SyncLockError(
                f"another sync process holds the lock {self.path} ({exc})"
            ) from exc
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def sync_lock(path: Path) -> SyncLock:
    """Context-manager factory: ``with sync_lock(path): ...``"""
    return SyncLock(path)


def db_lock_path(db_path: str | Path) -> Path:
    """The sync-lock path for a database file.

    Every writer of a given database — the sync pipeline AND the review-write
    entry points (API resolve, CLI resolve) — must take the SAME lock, otherwise
    a sync rebuild can clobber a resolution made mid-publish (P1-01).
    """
    return Path(db_path).parent / ".sync.lock"
