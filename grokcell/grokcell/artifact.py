"""One artifact type: generated module plus tests. Files, not vertex attributes."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .messages import validate_component_name
from .runner import suite_path

MODULE_NAME = "service.py"
TEST_NAME = "test_service.py"
LICENSE_NAME = "license.json"
SIGNATURE_NAME = "signature.txt"
FILE_ACTS = ("send", "publish", "delete", "sign")


def python_files(path: Path) -> list[Path]:
    return sorted(
        item
        for item in path.rglob("*.py")
        if item.is_file() and "__pycache__" not in item.parts
    )


def read_text_exact(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def hash_contents(files: dict[str, str]) -> str:
    return hash_bytes(
        {relative: content.encode("utf-8") for relative, content in files.items()}
    )


def hash_bytes(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relative])
        digest.update(b"\0")
    return digest.hexdigest()


def normalize_files(files: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_relative, content in files.items():
        if not isinstance(raw_relative, str) or not isinstance(content, str):
            raise ValueError("artifact files must map path strings to text")
        relative = PurePosixPath(raw_relative.replace("\\", "/"))
        if (
            not raw_relative
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or (relative.parts and relative.parts[0].endswith(":"))
            or relative.suffix != ".py"
            or "__pycache__" in relative.parts
        ):
            raise ValueError("invalid artifact path")
        key = relative.as_posix()
        if key in normalized:
            raise ValueError("duplicate normalized artifact path")
        normalized[key] = content
    return normalized


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    files: dict[str, str]
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", normalize_files(dict(self.files)))

    def digest(self) -> str:
        return hash_contents(self.files)


def resolve_artifact(payload: dict) -> Artifact | None:
    try:
        name = validate_component_name(payload.get("name"))
    except ValueError:
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
        item.relative_to(path).as_posix(): read_text_exact(item)
        for item in python_files(path)
    }
    if not files:
        return None
    return Artifact(name=name, files=files, source="suite")


def stage_artifact(artifact: Artifact, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    root = directory.resolve()
    for relative, content in artifact.files.items():
        target = directory.joinpath(*PurePosixPath(relative).parts)
        if not target.resolve().is_relative_to(root):
            raise ValueError("artifact_path_escape")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    return directory


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, name: str) -> Path:
        exact = validate_component_name(name)
        path = self.root / exact
        if path.resolve().parent != self.root.resolve():
            raise ValueError("invalid_component_name")
        return path

    def materialize(self, artifact: Artifact) -> Path:
        dest = self.path_for(artifact.name)
        digest = artifact.digest()
        if dest.exists():
            license_payload = self._read_license(dest)
            if (
                license_payload.get("name") == artifact.name
                and license_payload.get("hash") == digest
                and self._current_digest(dest) == digest
            ):
                return dest
            raise ValueError("artifact_conflict")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{artifact.name}-", dir=self.root))
        try:
            stage_artifact(artifact, temporary)
            self._write_license(
                temporary,
                name=artifact.name,
                license="admitted",
                digest=digest,
            )
            temporary.replace(dest)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
        return dest

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        items: list[dict] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            payload = self._read_license(child)
            if not payload:
                continue
            name = str(payload.get("name") or "")
            try:
                if validate_component_name(name) != child.name:
                    continue
            except ValueError:
                continue
            license_name = str(payload.get("license") or "")
            if not license_name or not payload.get("hash"):
                continue
            files = [item.relative_to(child).as_posix() for item in python_files(child)]
            items.append({"name": name, "license": license_name, "files": files})
        return items

    def names(self) -> set[str]:
        return {str(item["name"]) for item in self.list()}

    def prune_except(self, admitted_names: set[str]) -> None:
        """Remove valid artifacts that have no corresponding graph component."""
        for name in self.names() - admitted_names:
            shutil.rmtree(self.path_for(name))

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
        try:
            dest = self.path_for(owner)
        except ValueError:
            return {
                "decision": "refused",
                "reason": "invalid_component_name",
                "name": owner,
                "bypasses_dpo": False,
            }
        payload = self._read_license(dest)
        if (
            not payload
            or payload.get("name") != owner
            or payload.get("license") == "deleted"
        ):
            return {
                "decision": "refused",
                "reason": "missing_artifact",
                "name": owner,
                "bypasses_dpo": False,
            }
        digest = str(payload.get("hash") or "")
        if verb != "delete" and self._current_digest(dest) != digest:
            return {
                "decision": "refused",
                "reason": "artifact_modified",
                "name": owner,
                "bypasses_dpo": False,
            }
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
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _current_digest(self, dest: Path) -> str:
        files = {
            item.relative_to(dest).as_posix(): item.read_bytes()
            for item in python_files(dest)
        }
        return hash_bytes(files)

    def _write_license(self, dest: Path, *, name: str, license: str, digest: str) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        payload = {"name": name, "license": license, "hash": digest}
        path = dest / LICENSE_NAME
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
