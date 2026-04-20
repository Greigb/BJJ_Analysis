"""Runtime configuration for the BJJ app backend."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    # tools/bjj-app/server/config.py → project root is three parents up
    return Path(__file__).resolve().parent.parent.parent.parent


@dataclass(frozen=True)
class Settings:
    project_root: Path
    vault_root: Path
    db_path: Path
    host: str
    port: int
    frontend_build_dir: Path


def load_settings() -> Settings:
    project_root = Path(os.getenv("BJJ_PROJECT_ROOT", str(_project_root()))).resolve()
    return Settings(
        project_root=project_root,
        vault_root=project_root,  # vault IS the project root per the spec
        db_path=project_root / "tools" / "bjj-app" / "bjj-app.db",
        host=os.getenv("BJJ_HOST", "0.0.0.0"),
        port=int(os.getenv("BJJ_PORT", "8000")),
        frontend_build_dir=project_root / "tools" / "bjj-app" / "web" / "build",
    )
