from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import load_pp_config
from ..logger import get_logger
from ..cmd import tool as tool_cmd
from .reviewer import ReviewOutcome, review_text

_COST_ORDER = ("very low", "low", "medium", "high", "very high")
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}
_OFFICE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp"}
_AGENT_IMPL_MODE = "tool_calls"


@dataclass(slots=True)
class ParseResult:
    ok: bool
    source_file: str
    output_file: str
    tool: str
    review: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source_file": self.source_file,
            "output_file": self.output_file,
            "tool": self.tool,
            "review": self.review,
        }


def run_parser(
    *,
    paths: list[Path] | None = None,
    out_dir: Path | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    logger = logger or get_logger("agent.parser")
    pp_cfg = load_pp_config(cwd=cwd, home=home)
    output_dir = _resolve_output_dir(out_dir=out_dir, cwd=cwd, pp_cfg=pp_cfg)
    memory = _read_memory(cwd)
    targets = _resolve_targets(paths=paths, cwd=cwd, memory=memory, output_dir=output_dir)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for target in targets:
        try:
            results.append(
                parse_path(
                    target,
                    cwd=cwd,
                    home=home,
                    out_dir=output_dir,
                    memory=memory,
                    pp_cfg=pp_cfg,
                    logger=logger,
                ).as_dict()
            )
        except Exception as exc:
            failures.append({"source_file": _relpath(target, cwd), "error": str(exc)})
            logger.error("Failed to parse %s: %s", target, exc)

    return {
        "ok": not failures,
        "out_dir": str(output_dir),
        "parsed_count": len(results),
        "failed_count": len(failures),
        "results": results,
        "failures": failures,
    }


def parse_path(
    path: Path,
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    out_dir: Path | None = None,
    memory: str | None = None,
    pp_cfg: Mapping[str, Any] | None = None,
    logger=None,
) -> ParseResult:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    logger = logger or get_logger("agent.parser")
    pp_cfg = pp_cfg or load_pp_config(cwd=cwd, home=home)
    output_dir = _resolve_output_dir(out_dir=out_dir, cwd=cwd, pp_cfg=pp_cfg)
    source = path if path.is_absolute() else (cwd / path)
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"{source} not found")

    memory = memory if memory is not None else _read_memory(cwd)
    candidates = _candidate_tools(source, cwd=cwd, home=home, memory=memory, logger=logger)
    if not candidates:
        raise RuntimeError(f"no parser tool is available for {source.name}")

    last_review: ReviewOutcome | None = None
    for discovered in candidates:
        argv = _tool_argv(discovered.spec, source)
        if argv is None:
            continue
        try:
            raw = tool_cmd.run_tool(discovered.spec.name, argv, cwd=cwd, home=home, logger=logger)
        except Exception as exc:
            logger.info("Parser tool %s failed for %s: %s", discovered.spec.name, source, exc)
            continue
        if raw.kind == "binary":
            logger.info("Parser tool %s returned binary output for %s", discovered.spec.name, source)
            continue
        text = _result_text(raw.value)
        review = review_text(text, source_path=source, cwd=cwd, home=home, logger=logger)
        last_review = review
        if not review.ok:
            continue

        output_file = _write_output(
            review.text,
            source=source,
            cwd=cwd,
            out_dir=output_dir,
            pp_cfg=pp_cfg,
        )
        return ParseResult(
            ok=True,
            source_file=_relpath(source, cwd),
            output_file=str(output_file),
            tool=discovered.spec.name,
            review=review.as_dict(),
        )

    message = (
        last_review.message
        if last_review is not None
        else "The reviewer found current given result need a major revision."
    )
    raise RuntimeError(message)


def _candidate_tools(
    source: Path,
    *,
    cwd: Path,
    home: Path,
    memory: str,
    logger,
) -> list[tool_cmd.DiscoveredTool]:
    discovered = [
        *tool_cmd.discover_builtin_tools(logger=logger),
        *tool_cmd.discover_user_tools_for_home(cwd=cwd, home=home, logger=logger),
    ]
    usable = [
        item
        for item in discovered
        if item.availability.available
        and item.spec.scope == "parser"
        and item.spec.has_flag("path")
    ]
    ext = source.suffix.lstrip(".").lower()
    baseline = _cost_baseline(source, cwd=cwd, memory=memory)

    def score(item: tool_cmd.DiscoveredTool) -> tuple[int, int, str]:
        return (
            _extension_rank(item.spec.name, ext),
            abs(_cost_index(item.spec.cost) - _cost_index(baseline)),
            item.spec.name,
        )

    return sorted(usable, key=score)


def _extension_rank(name: str, ext: str) -> int:
    if ext == "pdf" and name == "pdf2txt":
        return 0
    if ext in _OFFICE_EXTS and name == "pandoc2txt":
        return 0
    if ext in _IMAGE_EXTS and name == "img_thumb":
        return 9
    if name in {"pdf2txt", "pandoc2txt"}:
        return 4
    return 1


def _tool_argv(spec: tool_cmd.ToolSpec, source: Path) -> list[str] | None:
    if not spec.has_flag("path"):
        return None
    return [spec.flag_token("path"), str(source)]


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _resolve_output_dir(*, out_dir: Path | None, cwd: Path, pp_cfg: Mapping[str, Any]) -> Path:
    if out_dir is None:
        configured = _as_mapping(pp_cfg.get("output")).get("dir") or "pennyparse_results"
        out_dir = Path(str(configured))
    if not out_dir.is_absolute():
        out_dir = cwd / out_dir
    return out_dir.resolve()


def _write_output(
    text: str,
    *,
    source: Path,
    cwd: Path,
    out_dir: Path,
    pp_cfg: Mapping[str, Any],
) -> Path:
    rel = Path(_relpath(source, cwd))
    ext = _output_ext(pp_cfg)
    output_file = out_dir / rel.parent / f"{rel.name}.{ext}"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(text, encoding="utf-8")
    return output_file


def _output_ext(pp_cfg: Mapping[str, Any]) -> str:
    configured = str(_as_mapping(pp_cfg.get("output")).get("ext") or "auto").strip().lower()
    if configured in {"txt", "md", "html"}:
        return configured
    return "txt"


def _read_memory(cwd: Path) -> str:
    path = cwd / ".pennyparse_memory.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _cost_baseline(source: Path, *, cwd: Path, memory: str) -> str:
    rel = _relpath(source, cwd)
    text = memory if isinstance(memory, str) else ""
    if not text.strip():
        return "medium"

    source_markers = (rel.lower(), source.name.lower())
    for sentence in _memory_sentences(text):
        lowered = sentence.lower()
        if any(marker and marker in lowered for marker in source_markers):
            cost = _cost_from_text(sentence)
            if cost:
                return cost

    for sentence in _memory_sentences(text):
        if "overall" in sentence.lower():
            cost = _cost_from_text(sentence)
            if cost:
                return cost
    return "medium"


def _memory_sentences(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _cost_from_text(text: str) -> str | None:
    lowered = text.lower()
    for cost in sorted(_COST_ORDER, key=len, reverse=True):
        if f"{cost} cost" in lowered or f"start from {cost}" in lowered:
            return cost
    return None


def _cost_index(cost: str) -> int:
    try:
        return _COST_ORDER.index(cost)
    except ValueError:
        return _COST_ORDER.index("medium")


def _resolve_targets(
    *,
    paths: list[Path] | None,
    cwd: Path,
    memory: str,
    output_dir: Path,
) -> list[Path]:
    if paths:
        found: list[Path] = []
        for item in paths:
            path = item if item.is_absolute() else cwd / item
            if path.is_dir():
                found.extend(_walk_targets(path, cwd=cwd, output_dir=output_dir))
            else:
                found.append(path)
        by_name = {path.resolve().as_posix(): path.resolve() for path in found}
        return [by_name[name] for name in sorted(by_name)]

    return _walk_targets(cwd, cwd=cwd, output_dir=output_dir)


def _walk_targets(root: Path, *, cwd: Path, output_dir: Path) -> list[Path]:
    targets: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        rel_current = _relpath(current, cwd)
        if rel_current != "." and any(part.startswith(".") for part in Path(rel_current).parts):
            dirnames[:] = []
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and (current / name).resolve() != output_dir
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            path = current / filename
            if path.resolve().is_relative_to(output_dir):
                continue
            targets.append(path.resolve())
    targets.sort(key=lambda item: item.as_posix())
    return targets


def _relpath(path: Path, cwd: Path) -> str:
    try:
        return path.resolve().relative_to(cwd.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix().lstrip("/")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
