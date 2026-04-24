from __future__ import annotations

from pathlib import Path
from typing import Any


def run_init(
    *,
    overwrite_tools: bool,
    overwrite_docs: bool,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> dict[str, Any]:
    from .init_docs import run_init_docs
    from .init_tools import run_init_tools

    tools_summary = run_init_tools(
        overwrite=overwrite_tools,
        cwd=cwd,
        home=home,
        logger=logger,
    )
    docs_summary = run_init_docs(
        overwrite=overwrite_docs,
        cwd=cwd,
        home=home,
        logger=logger,
    )
    return {
        "ok": bool(tools_summary.get("ok")) and bool(docs_summary.get("ok")),
        "tools": tools_summary,
        "docs": docs_summary,
    }

