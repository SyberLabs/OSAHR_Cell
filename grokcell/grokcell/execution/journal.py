"""Execution generations in SnapshotStore's CURRENT pointer, not a second database.

A state root is either a legacy graph/surface root or an execution root. Mixing
modes is refused. Checksums detect corruption; the operator-owned directory is
part of the trust boundary, not an authenticated hostile-storage protocol.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..snapshot import SnapshotStore

MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MANIFEST_VERSION = 2


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("nonfinite checkpoint number")


def read_json(path: Path, maximum: int = MAX_CHECKPOINT_BYTES) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("invalid or oversized checkpoint file")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("checkpoint byte limit")
    result = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    if type(result) is not dict:
        raise ValueError("checkpoint object required")
    return result


def sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def private_root(path: Path) -> Path:
    if os.name != "posix":
        raise RuntimeError("durable execution currently requires POSIX local storage")
    if path.is_symlink():
        raise ValueError("state root must not be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("execution state must be operator-owned with mode 0700")
    return path.resolve()


def _current(store: SnapshotStore):
    if not store.current_path.exists() and not store.current_path.is_symlink():
        if (store.kernel_path.exists() or store.surface_path.exists()
                or any(store.root.glob("kernel-*.osahr.gz"))
                or any(store.root.glob("surface-*.json"))
                or any(store.root.glob("execution-*.json"))):
            raise ValueError("missing CURRENT or legacy state; operator recovery required")
        return None, None
    manifest = read_json(store.current_path, 4096)
    if (set(manifest) != {"version", "kind", "generation", "execution", "sha256"}
            or manifest["version"] != MANIFEST_VERSION or manifest["kind"] != "execution"):
        raise ValueError("state root belongs to another format; no implicit migration")
    if (any(path.exists() or path.is_symlink()
            for path in (store.kernel_path, store.surface_path))
            or any(store.root.glob("kernel-*.osahr.gz"))
            or any(store.root.glob("surface-*.json"))):
        raise ValueError("mixed state formats; operator recovery required")
    generation = manifest["generation"]
    if type(generation) is not str or not re.fullmatch(r"[0-9a-f]{32}", generation):
        raise ValueError("invalid execution generation")
    name = f"execution-{generation}.json"
    if manifest["execution"] != name:
        raise ValueError("invalid execution path")
    path = store.root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ValueError("missing or invalid execution generation")
    actual = store._digest(path)
    if manifest["sha256"] != actual:
        raise ValueError("execution checksum mismatch")
    return manifest, f"execution:{generation}:{actual}"


def load(store: SnapshotStore) -> dict | None:
    with store.locked():
        manifest, revision = _current(store)
        value = None if manifest is None else read_json(store.root / manifest["execution"])
        store._loaded, store._loaded_revision = True, revision
        return value


def _write(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def save(store: SnapshotStore, payload: dict) -> None:
    if type(payload) is not dict:
        raise TypeError("checkpoint object required")
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint byte limit")
    with store.locked():
        if not store._loaded:
            raise RuntimeError("execution state must be loaded before saving")
        previous, revision = _current(store)
        if revision != store._loaded_revision:
            raise RuntimeError("execution state changed since it was loaded")
        generation = uuid.uuid4().hex
        name = f"execution-{generation}.json"
        data_path = store.root / name
        temporary = store.root / f".CURRENT-{generation}.json.tmp"
        checksum = hashlib.sha256(raw).hexdigest()
        manifest = {"version": MANIFEST_VERSION, "kind": "execution", "generation": generation,
                    "execution": name, "sha256": checksum}
        try:
            _write(data_path, raw)
            sync_directory(store.root)
            _write(temporary, json.dumps(manifest, sort_keys=True).encode("utf-8"))
            os.replace(temporary, store.current_path)
            sync_directory(store.root)
        finally:
            temporary.unlink(missing_ok=True)
        store._loaded_revision = f"execution:{generation}:{checksum}"
        keep = {name, previous["execution"] if previous else ""}
        for item in store.root.glob("execution-*.json"):
            if item.name not in keep:
                item.unlink(missing_ok=True)
        sync_directory(store.root)
