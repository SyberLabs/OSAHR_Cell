"""File snapshot of surface + kernel. Chat is not the database."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from osahr import load_checkpoint, save_checkpoint

from . import protocol
from .messages import Message

KERNEL_NAME = "kernel.osahr.gz"
SURFACE_NAME = "surface.json"


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
        held_list = [Message.from_json(item) for item in payload.get("held") or []]
        return cls(
            seq=int(payload.get("seq") or 0),
            inject_seq=int(payload.get("inject_seq") or 0),
            queued=[Message.from_json(item) for item in payload.get("queued") or []],
            held={item.message_id: item for item in held_list},
        )


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, root: Path | None = None) -> "SnapshotStore":
        return cls(Path(root) if root is not None else protocol.STATE_DIR)

    @property
    def kernel_path(self) -> Path:
        return self.root / KERNEL_NAME

    @property
    def surface_path(self) -> Path:
        return self.root / SURFACE_NAME

    def exists(self) -> bool:
        return self.kernel_path.is_file() and self.surface_path.is_file()

    def incomplete(self) -> bool:
        return self.kernel_path.is_file() != self.surface_path.is_file()

    def save(self, runtime: object, surface: SurfaceSnapshot) -> None:
        kernel_tmp = self.kernel_path.with_name(self.kernel_path.name + ".tmp")
        surface_tmp = self.surface_path.with_name(self.surface_path.name + ".tmp")
        save_checkpoint(kernel_tmp, runtime.snapshot())
        surface_tmp.write_text(
            json.dumps(surface.to_json(), indent=2) + "\n",
            encoding="utf-8",
        )
        kernel_tmp.replace(self.kernel_path)
        surface_tmp.replace(self.surface_path)

    def load_pair(self) -> tuple[object, SurfaceSnapshot] | None:
        if self.incomplete():
            raise ValueError("incomplete grokcell snapshot")
        if not self.exists():
            return None
        kernel = load_checkpoint(self.kernel_path)
        payload = json.loads(self.surface_path.read_text(encoding="utf-8"))
        return kernel, SurfaceSnapshot.from_json(payload)
