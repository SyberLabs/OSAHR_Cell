"""One artifact type: generated module plus tests. Files, not vertex attributes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .runner import suite_path

MODULE_NAME = "service.py"
TEST_NAME = "test_service.py"
LICENSE_NAME = "license.json"
SIGNATURE_NAME = "signature.txt"
FILE_ACTS = ("send", "publish", "delete", "sign")


def safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in str(name))
    return cleaned or "unnamed"


def python_files(path: Path) -> list[Path]:
    return sorted(
        item
        for item in path.rglob("*.py")
        if item.is_file() and "__pycache__" not in item.parts
    )


def hash_contents(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relative].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    files: dict[str, str]
    source: str

    def digest(self) -> str:
        return hash_contents(self.files)


def resolve_artifact(payload: dict) -> Artifact | None:
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    module = payload.get("module")
    tests = payload.get("tests")
    if isinstance(module, str) and module.strip() and isinstance(tests, str) and tests.strip():
        return Artifact(
            name=name,
            files={MODULE_NAME: module, TEST_NAME: tests},
            source="payload",
        )
    path = suite_path(name)
    if path is None:
        return None
    files = {
        str(item.relative_to(path)): item.read_text(encoding="utf-8")
        for item in python_files(path)
    }
    if not files:
        return None
    return Artifact(name=name, files=files, source="suite")


def stage_artifact(artifact: Artifact, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for relative, content in artifact.files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return directory


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, name: str) -> Path:
        return self.root / safe_name(name)

    def materialize(self, artifact: Artifact) -> Path:
        dest = self.path_for(artifact.name)
        dest.mkdir(parents=True, exist_ok=True)
        for relative, content in artifact.files.items():
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self._write_license(dest, name=artifact.name, license="admitted", digest=artifact.digest())
        return dest

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        items: list[dict] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            payload = self._read_license(child)
            name = str(payload.get("name") or child.name)
            license_name = str(payload.get("license") or "admitted")
            files = [str(item.relative_to(child)) for item in python_files(child)]
            items.append({"name": name, "license": license_name, "files": files})
        return items

    def act(self, *, act: str, name: str) -> dict:
        verb = str(act or "").strip()
        owner = str(name or "").strip()
        if verb not in FILE_ACTS:
            return {
                "decision": "refused",
                "reason": "unsupported_act",
                "name": owner,
                "bypasses_dpo": False,
            }
        dest = self.path_for(owner)
        payload = self._read_license(dest)
        if not payload or payload.get("license") == "deleted":
            return {
                "decision": "refused",
                "reason": "missing_artifact",
                "name": owner,
                "bypasses_dpo": False,
            }
        digest = str(payload.get("hash") or "")
        license_by_act = {
            "send": "sent",
            "publish": "published",
            "delete": "deleted",
            "sign": "signed",
        }
        if verb == "delete":
            for item in python_files(dest):
                item.unlink()
        elif verb == "sign":
            (dest / SIGNATURE_NAME).write_text(digest + "\n", encoding="utf-8")
        self._write_license(
            dest,
            name=owner,
            license=license_by_act[verb],
            digest=digest,
        )
        return {
            "decision": "accepted",
            "reason": f"artifact_{verb}",
            "name": owner,
            "bypasses_dpo": False,
        }

    def _read_license(self, dest: Path) -> dict:
        path = dest / LICENSE_NAME
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _write_license(self, dest: Path, *, name: str, license: str, digest: str) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        payload = {"name": name, "license": license, "hash": digest}
        (dest / LICENSE_NAME).write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
