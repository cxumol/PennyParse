from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent.init_tools import run_init_tools_agent
from ..config import ensure_user_state_dir, get_user_toolbox_path
from ..logger import get_logger


def run_init_tools(
    *,
    overwrite: bool,
    source_path: Path | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    logger = logger or get_logger("cmd.init_tools")
    ensure_user_state_dir(home=home)

    resolved_source = source_path or (home / "pennyparse.toolbox_user.txt")
    if not resolved_source.exists():
        raise FileNotFoundError(f"{resolved_source} not found")

    target_path = get_user_toolbox_path(home=home)
    if target_path.exists() and not overwrite:
        raise RuntimeError(f"refused to overwrite existing {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    return run_init_tools_agent(
        cwd=cwd,
        source_path=resolved_source,
        target_path=target_path,
        logger=logger,
    )

