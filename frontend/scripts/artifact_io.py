"""Bounded, read-only helpers for importing research artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_JSONL_ROWS = 100_000


class SourceChangedError(RuntimeError):
    """Raised when a source file changes while it is being read."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"Source changed while reading: {path}")


class RejectedPathError(RuntimeError):
    """Raised when a candidate path is not a regular in-root file."""

    def __init__(self, path: Path, code: str, message: str):
        self.path = path
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class StableBytes:
    data: bytes
    content_hash: str


def display_path(path: Path, root: Path) -> str:
    try:
        return path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return path.name


def diagnostic(path: Path, root: Path, code: str, message: str) -> dict[str, str]:
    return {
        "file": display_path(path, root),
        "code": code,
        "message": message,
    }


def _reject_unsafe_path(path: Path, root: Path) -> None:
    root_abs = root.absolute()
    path_abs = path.absolute()
    try:
        relative = path_abs.relative_to(root_abs)
    except ValueError as exc:
        raise RejectedPathError(path, "outside_root", "Path is outside the configured root") from exc

    cursor = root_abs
    for part in relative.parts:
        cursor /= part
        try:
            metadata = os.stat(cursor, follow_symlinks=False)
        except FileNotFoundError:
            raise
        if stat.S_ISLNK(metadata.st_mode):
            raise RejectedPathError(path, "symlink_rejected", "Symbolic links are not imported")
    if not stat.S_ISREG(metadata.st_mode):
        raise RejectedPathError(path, "not_regular_file", "Only regular files are imported")


def read_stable_bytes(path: Path, root: Path) -> StableBytes:
    """Read a regular in-root file twice and fail if metadata or bytes change."""

    _reject_unsafe_path(path, root)
    before = os.stat(path, follow_symlinks=False)
    if before.st_size > MAX_FILE_BYTES:
        raise RejectedPathError(
            path,
            "file_too_large",
            f"File exceeds the {MAX_FILE_BYTES}-byte import limit",
        )

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened_before = os.fstat(descriptor)
        first = os.read(descriptor, MAX_FILE_BYTES + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second = os.read(descriptor, MAX_FILE_BYTES + 1)
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = os.stat(path, follow_symlinks=False)

    comparable = lambda value: (  # noqa: E731 - compact immutable stat projection
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
    if (
        comparable(before) != comparable(opened_before)
        or comparable(opened_before) != comparable(opened_after)
        or comparable(opened_after) != comparable(after)
        or first != second
    ):
        raise SourceChangedError(path)
    if len(first) > MAX_FILE_BYTES:
        raise RejectedPathError(
            path,
            "file_too_large",
            f"File exceeds the {MAX_FILE_BYTES}-byte import limit",
        )
    return StableBytes(first, hashlib.sha256(first).hexdigest())


def read_json_object(path: Path, root: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    try:
        text = read_stable_bytes(path, root).data.decode("utf-8")
        value = json.loads(text)
    except RejectedPathError as exc:
        return None, [diagnostic(path, root, exc.code, str(exc))]
    except UnicodeDecodeError:
        return None, [diagnostic(path, root, "invalid_utf8", "File is not valid UTF-8")]
    except json.JSONDecodeError as exc:
        return None, [
            diagnostic(path, root, "invalid_json", f"Invalid JSON at line {exc.lineno}, column {exc.colno}")
        ]
    if not isinstance(value, dict):
        return None, [diagnostic(path, root, "invalid_json_object", "Expected a JSON object")]
    return value, []


def read_jsonl_objects(path: Path, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    try:
        text = read_stable_bytes(path, root).data.decode("utf-8")
    except RejectedPathError as exc:
        return [], [diagnostic(path, root, exc.code, str(exc))]
    except UnicodeDecodeError:
        return [], [diagnostic(path, root, "invalid_utf8", "File is not valid UTF-8")]

    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number > MAX_JSONL_ROWS:
            diagnostics.append(
                diagnostic(path, root, "jsonl_row_limit", f"Stopped after {MAX_JSONL_ROWS} JSONL rows")
            )
            break
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                diagnostic(
                    path,
                    root,
                    "invalid_jsonl_line",
                    f"Line {line_number} is invalid JSON at column {exc.colno}",
                )
            )
            continue
        if not isinstance(value, dict):
            diagnostics.append(
                diagnostic(path, root, "invalid_jsonl_object", f"Line {line_number} is not a JSON object")
            )
            continue
        rows.append(value)
    return rows, diagnostics


def read_text(path: Path, root: Path) -> tuple[str | None, list[dict[str, str]]]:
    try:
        return read_stable_bytes(path, root).data.decode("utf-8"), []
    except RejectedPathError as exc:
        return None, [diagnostic(path, root, exc.code, str(exc))]
    except UnicodeDecodeError:
        return None, [diagnostic(path, root, "invalid_utf8", "File is not valid UTF-8")]
