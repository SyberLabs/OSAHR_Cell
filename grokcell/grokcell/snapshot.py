"""File snapshot of surface + kernel. Chat is not the database."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from osahr import RuntimeConfig, load_checkpoint, save_checkpoint

from . import protocol
from .messages import Message

KERNEL_NAME = "kernel.osahr.gz"
SURFACE_NAME = "surface.json"
CURRENT_NAME = "CURRENT.json"
LOCK_NAME = ".grokcell.lock"
SNAPSHOT_VERSION = 1
_GENERATION = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class _StateLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "_StateLock":
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError(
                "grokcell state is locked by another writer"
            ) from exc
        self.handle = handle
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.handle is not None
        try:
            self.handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        finally:
            self.handle.close()
            self.handle = None


@dataclass
class SurfaceSnapshot:
    seq: int
    inject_seq: int
    queued: list[Message]
    held: dict[str, Message]

    def to_json(self) -> dict:
        return {
            "version": protocol.SURFACE_VERSION,
            "seq": self.seq,
            "inject_seq": self.inject_seq,
            "queued": [item.to_json() for item in self.queued],
            "held": [item.to_json() for item in self.held.values()],
        }

    @classmethod
    def from_json(cls, payload: dict) -> "SurfaceSnapshot":
        if not isinstance(payload, dict):
            raise ValueError("invalid grokcell surface snapshot")
        if payload.get("version") != protocol.SURFACE_VERSION:
            raise ValueError("unsupported grokcell surface snapshot")
        seq = payload.get("seq")
        inject_seq = payload.get("inject_seq")
        queued_payload = payload.get("queued")
        held_payload = payload.get("held")
        if (
            not isinstance(seq, int)
            or isinstance(seq, bool)
            or not isinstance(inject_seq, int)
            or isinstance(inject_seq, bool)
            or seq \u003c 0
            or inject_seq \u003c 0
            or inject_seq > seq
            or not isinstance(queued_payload, list)
            or not isinstance(held_payload, list)
        ):
            raise ValueError("invalid grokcell surface counters or queues")
        queued = [Message.from_json(item) for item in queued_payload]
        held_list = [Message.from_json(item) for item in held_payload]
        messages = queued + held_list
        identities = [item.message_id for item in messages]
        if (
            len(identities) != len(set(identities))
            or any(
                item.seq \u003c= 0 or item.message_id != f"m-{item.seq:04d}"
                for item in messages
            )
            or any(item.seq > seq for item in messages)
        ):
            raise ValueError("invalid grokcell surface message identities")
        return cls(
            seq=seq,
            inject_seq=inject_seq,
            queued=queued,
            held={item.message_id: item for item in held_list},
        )


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._loaded = False
        self._loaded_revision: str | None = None
        self._thread_lock = threading.RLock()
        self._lock_depth = 0
        self._process_lock: _StateLock | None = None

    @classmethod
    def load(cls, root: Path | None = None) -> "SnapshotStore":
        if root is not None:
            return cls(Path(root))
        env = os.environ.get("GROKCELL_STATE_DIR")
        return cls(Path(env) if env else protocol.STATE_DIR)

    @property
    def kernel_path(self) -> Path:
        return self.root / KERNEL_NAME

    @property
    def surface_path(self) -> Path:
        return self.root / SURFACE_NAME

    @property
    def current_path(self) -> Path:
        return self.root / CURRENT_NAME

    @property
    def lock_path(self) -> Path:
        return self.root / LOCK_NAME

    def _state_lock(self) -> _StateLock:
        return _StateLock(self.lock_path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize a complete state-root transaction, reentrantly per store."""
        with self._thread_lock:
            if self._lock_depth == 0:
                process_lock = self._state_lock()
                process_lock.__enter__()
                self._process_lock = process_lock
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
                if self._lock_depth == 0:
                    assert self._process_lock is not None
                    self._process_lock.__exit__(None, None, None)
                    self._process_lock = None

    def exists(self) -> bool:
        return self.current_path.is_file() or (
            self.kernel_path.is_file() and self.surface_path.is_file()
        )

    def incomplete(self) -> bool:
        if self.current_path.is_file():
            try:
                manifest = self._load_manifest()
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                return True
            return not all(
                (self.root / manifest[key]).is_file() for key in ("kernel", "surface")
            )
        has_generation = any(self.root.glob("kernel-*.osahr.gz")) or any(
            self.root.glob("surface-*.json")
        )
        if has_generation:
            # Generation files mean CURRENT is the only valid pointer. A planted
            # legacy pair next to them is tampering, not a crashed migration.
            return True
        legacy_kernel = self.kernel_path.is_file()
        legacy_surface = self.surface_path.is_file()
        if legacy_kernel != legacy_surface:
            return True
        return False

    def _revision(self) -> str | None:
        if self.current_path.is_file():
            manifest = self._load_manifest()
            kernel_path = self.root / manifest["kernel"]
            surface_path = self.root / manifest["surface"]
            return ":".join(
                (
                    "generation",
                    manifest["generation"],
                    manifest["kernel_sha256"],
                    manifest["surface_sha256"],
                    self._digest(kernel_path),
                    self._digest(surface_path),
                )
            )
        if self.kernel_path.is_file() and self.surface_path.is_file():
            return (
                f"legacy:{self._digest(self.kernel_path)}:"
                f"{self._digest(self.surface_path)}"
            )
        return None

    def save(self, runtime: object, surface: SurfaceSnapshot) -> None:
        with self.locked():
            if not self._loaded:
                raise RuntimeError("grokcell state must be loaded before it is saved")
            if self._revision() != self._loaded_revision:
                raise RuntimeError("grokcell state changed since it was loaded")
            previous: set[str] = set()
            if self.current_path.is_file():
                old_manifest = self._load_manifest()
                previous.update((old_manifest["kernel"], old_manifest["surface"]))
            generation = uuid.uuid4().hex
            kernel_path = self.root / f"kernel-{generation}.osahr.gz"
            surface_path = self.root / f"surface-{generation}.json"
            kernel_tmp = kernel_path.with_suffix(kernel_path.suffix + ".tmp")
            surface_tmp = surface_path.with_suffix(surface_path.suffix + ".tmp")
            current_tmp = self.root / f".CURRENT-{generation}.json.tmp"
            try:
                save_checkpoint(kernel_tmp, runtime.snapshot())
                surface_tmp.write_text(
                    json.dumps(surface.to_json(), indent=2) + "\n",
                    encoding="utf-8",
                )
                kernel_tmp.replace(kernel_path)
                surface_tmp.replace(surface_path)
                manifest = {
                    "version": SNAPSHOT_VERSION,
                    "generation": generation,
                    "kernel": kernel_path.name,
                    "surface": surface_path.name,
                    "kernel_sha256": self._digest(kernel_path),
                    "surface_sha256": self._digest(surface_path),
                }
                current_tmp.write_text(
                    json.dumps(manifest, indent=2) + "\n",
                    encoding="utf-8",
                )
                current_tmp.replace(self.current_path)
            finally:
                for temporary in (kernel_tmp, surface_tmp, current_tmp):
                    temporary.unlink(missing_ok=True)
            self._loaded_revision = ":".join(
                (
                    "generation",
                    generation,
                    manifest["kernel_sha256"],
                    manifest["surface_sha256"],
                    manifest["kernel_sha256"],
                    manifest["surface_sha256"],
                )
            )
            for legacy_path in (self.kernel_path, self.surface_path):
                try:
                    legacy_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._prune_generations(
                previous | {kernel_path.name, surface_path.name}
            )

    def load_pair(
        self,
        *,
        legacy_model: object | None = None,
        legacy_config: RuntimeConfig | None = None,
    ) -> tuple[object, SurfaceSnapshot] | None:
        with self.locked():
            if self.incomplete():
                raise ValueError("incomplete grokcell snapshot")
            if not self.exists():
                self._loaded = True
                self._loaded_revision = None
                return None
            revision = self._revision()
            if self.current_path.is_file():
                manifest = self._load_manifest()
                kernel_path = self.root / manifest["kernel"]
                surface_path = self.root / manifest["surface"]
                if self._digest(kernel_path) != manifest["kernel_sha256"]:
                    raise ValueError("grokcell kernel snapshot hash mismatch")
                if self._digest(surface_path) != manifest["surface_sha256"]:
                    raise ValueError("grokcell surface snapshot hash mismatch")
            else:
                kernel_path = self.kernel_path
                surface_path = self.surface_path
            kernel = load_checkpoint(
                kernel_path,
                legacy_model=legacy_model,
                legacy_config=legacy_config,
            )
            payload = json.loads(surface_path.read_text(encoding="utf-8"))
            surface = SurfaceSnapshot.from_json(payload)
            self._loaded = True
            self._loaded_revision = revision
            return kernel, surface

    def _load_manifest(self) -> dict:
        payload = json.loads(self.current_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
            raise ValueError("unsupported grokcell snapshot manifest")
        generation = str(payload["generation"])
        if _GENERATION.fullmatch(generation) is None:
            raise ValueError("invalid grokcell snapshot generation")
        expected_kernel = f"kernel-{generation}.osahr.gz"
        expected_surface = f"surface-{generation}.json"
        if payload.get("kernel") != expected_kernel or payload.get("surface") != expected_surface:
            raise ValueError("invalid grokcell snapshot manifest")
        if (
            _SHA256.fullmatch(str(payload.get("kernel_sha256") or "")) is None
            or _SHA256.fullmatch(str(payload.get("surface_sha256") or "")) is None
        ):
            raise ValueError("invalid grokcell snapshot hashes")
        root = self.root.resolve()
        for name in (expected_kernel, expected_surface):
            if (self.root / name).resolve().parent != root:
                raise ValueError("grokcell snapshot path escape")
        return payload

    def _prune_generations(self, keep: set[str]) -> None:
        for pattern in ("kernel-*.osahr.gz", "surface-*.json"):
            for path in self.root.glob(pattern):
                if path.name not in keep:
                    try:
                        path.unlink()
                    except OSError:
                        pass

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
