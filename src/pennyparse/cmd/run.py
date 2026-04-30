from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .._client import ChatClient, ChatSession
from ..agent.parser import run_parser
from ..agent import parser as parser_agent
from ..config import get_user_toolbox_path, load_pp_config
from ..logger import get_logger
from ..utils_aigc import complete_with_retry


def run(
    *,
    paths: list[Path] | None = None,
    out_dir: Path | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    logger = logger or get_logger("cmd.run")
    pp_cfg = load_pp_config(cwd=cwd, home=home)
    memory_path = cwd / ".pennyparse_memory.txt"
    _require_initialized(cwd=cwd, home=home, memory_path=memory_path)

    output_dir = parser_agent._resolve_output_dir(out_dir=out_dir, cwd=cwd, pp_cfg=pp_cfg)
    memory = _read_memory(memory_path)
    targets = parser_agent._resolve_targets(
        paths=paths,
        cwd=cwd,
        memory=memory,
        output_dir=output_dir,
    )
    batch_size = _parser_summary_batch(pp_cfg)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for batch in _chunks(targets, batch_size):
        batch_summary = run_parser(
            paths=batch,
            out_dir=output_dir,
            cwd=cwd,
            home=home,
            logger=logger,
        )
        batch_results = list(batch_summary.get("results") or [])
        batch_failures = list(batch_summary.get("failures") or [])
        batch_skipped = list(batch_summary.get("skipped") or [])
        results.extend(batch_results)
        failures.extend(batch_failures)
        skipped.extend(batch_skipped)
        _append_memory(memory_path, _summarize_batch(batch_results, batch_failures, batch_skipped, pp_cfg=pp_cfg))

    output_stats = _output_stats(output_dir)
    final_line = _final_summary(
        parsed_count=len(results),
        failed_count=len(failures),
        skipped_count=len(skipped),
        output_stats=output_stats,
    )
    _append_memory(memory_path, final_line)

    return {
        "ok": not failures,
        "out_dir": str(output_dir),
        "parsed_count": len(results),
        "failed_count": len(failures),
        "skipped_count": len(skipped),
        "results": results,
        "failures": failures,
        "skipped": skipped,
        "output_stats": output_stats,
    }


def _require_initialized(*, cwd: Path, home: Path, memory_path: Path) -> None:
    toolbox_path = get_user_toolbox_path(home=home)
    if not toolbox_path.is_file():
        raise RuntimeError(f"{toolbox_path} not found; run `pennyparse init tools` first")
    if not memory_path.is_file():
        raise RuntimeError(f"{memory_path} not found; run `pennyparse init docs` first")
    with memory_path.open("r", encoding="utf-8"):
        pass


def _read_memory(memory_path: Path) -> str:
    with memory_path.open("r", encoding="utf-8") as handle:
        return handle.read()


def _append_memory(memory_path: Path, line: str) -> None:
    text = line.strip()
    if not text:
        return
    with memory_path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write(text)
        handle.write("\n")


def _parser_summary_batch(pp_cfg: Mapping[str, Any]) -> int:
    value = pp_cfg.get("parser_summary_batch")
    output = pp_cfg.get("output")
    if value is None and isinstance(output, Mapping):
        value = output.get("parser_summary_batch")
    return max(1, int(value or 5))


def _chunks(items: list[Path], size: int) -> list[list[Path]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _summarize_batch(
    results: list[dict[str, Any]],
    failures: list[dict[str, str]],
    skipped: list[dict[str, str]],
    *,
    pp_cfg: Mapping[str, Any],
) -> str:
    fallback = _fallback_batch_summary(results, failures, skipped)
    settings = _chat_settings(pp_cfg)
    if not settings.get("model"):
        return fallback

    session = ChatSession()
    session.system("用20个汉字以内概述本批解析文件名和工具。只输出概述。")
    session.user(
        json.dumps(
            {
                "results": [
                    {
                        "source_file": item.get("source_file", ""),
                        "tool": item.get("tool", ""),
                    }
                    for item in results
                ],
                "failures": failures,
                "skipped": skipped,
            },
            ensure_ascii=False,
        )
    )
    try:
        with ChatClient(**settings) as client:
            message = complete_with_retry(
                client,
                session,
                max_retry=_max_retry(pp_cfg),
                temperature=0,
            )
        text = str(message.get("content") or "").strip()
    except Exception:
        return fallback
    return _limit_20(text or fallback)


def _fallback_batch_summary(
    results: list[dict[str, Any]],
    failures: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> str:
    first_source = ""
    for item in results:
        first_source = str(item.get("source_file") or "")
        if first_source:
            break
    if not first_source and failures:
        first_source = str(failures[0].get("source_file") or "")
    if not first_source and skipped:
        first_source = str(skipped[0].get("source_file") or "")
    first_name = Path(first_source).name or "空批次"
    tools = sorted({str(item.get("tool") or "") for item in results if item.get("tool")})
    tool_text = ",".join(tools) if tools else "无工具"
    total = len(results) + len(failures) + len(skipped)
    skip_text = f",跳过{len(skipped)}" if skipped else ""
    return _limit_20(f"{first_name}等{total}份:{tool_text}{skip_text}")


def _limit_20(text: str) -> str:
    compact = "".join(str(text).split())
    return compact[:20]


def _output_stats(output_dir: Path) -> dict[str, Any]:
    files: list[Path] = []
    if output_dir.exists():
        files = sorted(
            path
            for path in output_dir.rglob("*")
            if path.is_file() and ".pennyparse_pages" not in path.relative_to(output_dir).parts
        )
    by_ext: dict[str, int] = {}
    byte_count = 0
    for path in files:
        ext = path.suffix.lower() or "<none>"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        byte_count += path.stat().st_size
    return {
        "file_count": len(files),
        "byte_count": byte_count,
        "by_ext": by_ext,
    }


def _final_summary(
    *,
    parsed_count: int,
    failed_count: int,
    skipped_count: int,
    output_stats: Mapping[str, Any],
) -> str:
    by_ext = output_stats.get("by_ext")
    ext_text = ""
    if isinstance(by_ext, Mapping) and by_ext:
        ext_text = "; " + ", ".join(f"{key}:{by_ext[key]}" for key in sorted(by_ext))
    return (
        "Run summary: "
        f"parsed {parsed_count}, skipped {skipped_count}, failed {failed_count}, "
        f"output {output_stats.get('file_count', 0)} file(s), "
        f"{output_stats.get('byte_count', 0)} bytes"
        f"{ext_text}."
    )


def _chat_settings(pp_cfg: Mapping[str, Any]) -> dict[str, Any]:
    aigc = pp_cfg.get("aigc")
    api = aigc.get("api") if isinstance(aigc, Mapping) else {}
    chat = api.get("chatcomp") if isinstance(api, Mapping) else {}
    chat = chat if isinstance(chat, Mapping) else {}
    return {
        "base_url": str(chat.get("base") or "").strip(),
        "api_key": str(chat.get("authkey") or "").strip() or None,
        "model": str(chat.get("model") or "").strip() or None,
    }


def _max_retry(pp_cfg: Mapping[str, Any]) -> int:
    aigc = pp_cfg.get("aigc")
    agent = aigc.get("agent") if isinstance(aigc, Mapping) else {}
    if isinstance(agent, Mapping):
        return max(1, int(agent.get("max_retry") or 3))
    return 3
