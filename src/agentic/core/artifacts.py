"""Content-addressed artifact store.

Every stage output is written once, addressed by its SHA-256 digest, and
referenced by an ``agentic://`` URI. That makes runs reproducible and lets any
MCP client fetch the exact bytes a downstream agent consumed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..errors import ContractError
from .contracts import validate_payload


@dataclass(frozen=True)
class StoredArtifact:
    name: str
    uri: str
    digest: str
    path: Path
    size: int
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "uri": self.uri,
            "digest": self.digest,
            "path": str(self.path),
            "size": self.size,
            "created_at": self.created_at,
        }


class ArtifactStore:
    """Filesystem store for a single run."""

    def __init__(self, run_dir: Path, run_id: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.artifact_dir = self.run_dir / "artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = self.run_dir / "project"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.run_dir / "index.json"

    # -- writing ---------------------------------------------------------

    def put_model(self, name: str, model: BaseModel) -> StoredArtifact:
        payload = model.model_dump(mode="json")
        return self.put_json(name, payload)

    def put_json(self, name: str, payload: dict[str, Any], *, validate: bool = True) -> StoredArtifact:
        if validate:
            validate_payload(name, payload)
        blob = json.dumps(payload, indent=2, sort_keys=True).encode()
        digest = hashlib.sha256(blob).hexdigest()
        target = self.artifact_dir / f"{name}-{digest[:16]}.json"
        if not target.exists():
            target.write_bytes(blob)
        created = datetime.now(timezone.utc).isoformat()
        artifact = StoredArtifact(
            name=name,
            uri=f"agentic://{self.run_id}/{name}@{digest[:16]}",
            digest=digest,
            path=target,
            size=len(blob),
            created_at=created,
        )
        self._record(artifact)
        return artifact

    def _record(self, artifact: StoredArtifact) -> None:
        index: dict[str, Any] = {}
        if self._index_path.is_file():
            try:
                index = json.loads(self._index_path.read_text())
            except json.JSONDecodeError:
                index = {}
        entries: list[dict[str, Any]] = index.setdefault("artifacts", [])
        if not any(e.get("uri") == artifact.uri for e in entries):
            entries.append(artifact.to_json())
        self._index_path.write_text(json.dumps(index, indent=2, sort_keys=True))

    # -- reading ---------------------------------------------------------

    def get_json(self, uri_or_name: str) -> dict[str, Any]:
        path = self._resolve(uri_or_name)
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ContractError(f"artifact {uri_or_name} is not valid JSON: {exc}") from exc

    def latest(self, name: str) -> StoredArtifact | None:
        candidates = sorted(self.artifact_dir.glob(f"{name}-*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            return None
        path = candidates[-1]
        digest = path.stem.split("-", 1)[1]
        return StoredArtifact(
            name=name,
            uri=f"agentic://{self.run_id}/{name}@{digest}",
            digest=digest,
            path=path,
            size=path.stat().st_size,
            created_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        )

    def list_names(self) -> list[str]:
        names = {p.stem.rsplit("-", 1)[0] for p in self.artifact_dir.glob("*.json")}
        return sorted(names)

    def _resolve(self, uri_or_name: str) -> Path:
        if uri_or_name.startswith("agentic://"):
            tail = uri_or_name.removeprefix(f"agentic://{self.run_id}/")
            base, _, rev = tail.partition("@")
            matches = sorted(self.artifact_dir.glob(f"{base}-{rev}*.json")) if rev else sorted(
                self.artifact_dir.glob(f"{base}-*.json")
            )
            if not matches:
                raise ContractError(f"unknown artifact uri {uri_or_name}")
            return matches[-1]
        direct = self.artifact_dir / uri_or_name
        if direct.is_file():
            return direct
        latest = self.latest(uri_or_name)
        if latest is None:
            raise ContractError(f"unknown artifact {uri_or_name!r} in run {self.run_id}")
        return latest.path
