"""Runtime configuration for the BJJ app backend."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


GroundingMode = Literal["off", "positions", "positions+techniques"]
_VALID_GROUNDING_MODES = ("off", "positions", "positions+techniques")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


@dataclass(frozen=True)
class Settings:
    project_root: Path
    vault_root: Path
    db_path: Path
    host: str
    port: int
    frontend_build_dir: Path
    # Claude CLI adapter
    claude_bin: Path
    claude_model: str
    claude_max_calls: int
    claude_window_seconds: float
    taxonomy_path: Path
    # Prompt grounding mode (M10 + M12)
    grounding_mode: GroundingMode


def load_settings() -> Settings:
    project_root = Path(os.getenv("BJJ_PROJECT_ROOT", str(_project_root()))).resolve()
    vault_root = Path(os.getenv("BJJ_VAULT_ROOT", str(project_root))).resolve()
    db_override = os.getenv("BJJ_DB_OVERRIDE")
    db_path = (
        Path(db_override)
        if db_override
        else project_root / "tools" / "bjj-app" / "bjj-app.db"
    )
    claude_bin = Path(
        os.getenv("BJJ_CLAUDE_BIN", "/Users/greigbradley/.local/bin/claude")
    )
    return Settings(
        project_root=project_root,
        vault_root=vault_root,
        db_path=db_path,
        host=os.getenv("BJJ_HOST", "0.0.0.0"),
        port=int(os.getenv("BJJ_PORT", "8000")),
        frontend_build_dir=project_root / "tools" / "bjj-app" / "web" / "build",
        claude_bin=claude_bin,
        claude_model=os.getenv("BJJ_CLAUDE_MODEL", "claude-opus-4-7"),
        claude_max_calls=int(os.getenv("BJJ_CLAUDE_MAX_CALLS", "10")),
        claude_window_seconds=float(os.getenv("BJJ_CLAUDE_WINDOW_SECONDS", "300")),
        taxonomy_path=project_root / "tools" / "taxonomy.json",
        grounding_mode=_parse_grounding_mode(),
    )


def _parse_grounding_mode() -> GroundingMode:
    raw = os.getenv("BJJ_GROUNDING_MODE", "positions").strip()
    if raw not in _VALID_GROUNDING_MODES:
        raise ValueError(
            f"BJJ_GROUNDING_MODE={raw!r} invalid. "
            f"Choose one of: {_VALID_GROUNDING_MODES}"
        )
    return raw  # type: ignore[return-value]
