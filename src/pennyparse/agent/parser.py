from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import get_init_ignore_config, load_pp_config
from ..logger import get_logger
from ..cmd import tool as tool_cmd
from .reviewer import ReviewOutcome, review_text

_COST_ORDER: tuple[str, ...] = ("very low", "low", "medium", "high", "very high")
_COST_ORDER_DESC: tuple[str, ...] = ("very high", "very low", "medium", "high", "low")
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}
_OFFICE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp"}
_AGENT_IMPL_MODE = "tool_calls"
_PDF_SPLIT_TOOL = "pdf_pages_to_images"
_MAX_RECURSION_DEPTH = 1


class NoParserToolAvailable(RuntimeError):
    pass


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


@dataclass(slots=True)
class _ParsedText:
    text: str
    tool: str
    review: ReviewOutcome


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
    targets = _resolve_targets(paths=paths, cwd=cwd, memory=memory, output_dir=output_dir, pp_cfg=pp_cfg)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
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
        except NoParserToolAvailable as exc:
            skipped.append({"source_file": _relpath(target, cwd), "reason": str(exc)})
            logger.info("Skipped %s: %s", target, exc)
        except Exception as exc:
            failures.append({"source_file": _relpath(target, cwd), "error": str(exc)})
            logger.error("Failed to parse %s: %s", target, exc)

    return {
        "ok": not failures,
        "out_dir": str(output_dir),
        "parsed_count": len(results),
        "failed_count": len(failures),
        "skipped_count": len(skipped),
        "results": results,
        "failures": failures,
        "skipped": skipped,
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
    parsed = _parse_source(
        source,
        cwd=cwd,
        home=home,
        out_dir=output_dir,
        memory=memory,
        pp_cfg=pp_cfg,
        logger=logger,
        depth=0,
    )
    output_file = _write_output(
        parsed.review.text,
        source=source,
        cwd=cwd,
        out_dir=output_dir,
        pp_cfg=pp_cfg,
    )
    return ParseResult(
        ok=True,
        source_file=_relpath(source, cwd),
        output_file=str(output_file),
        tool=parsed.tool,
        review=parsed.review.as_dict(),
    )


def _parse_source(
    source: Path,
    *,
    cwd: Path,
    home: Path,
    out_dir: Path,
    memory: str,
    pp_cfg: Mapping[str, Any],
    logger,
    depth: int,
) -> _ParsedText:
    candidates = _candidate_tools(source, cwd=cwd, home=home, memory=memory, logger=logger)
    if not candidates:
        raise NoParserToolAvailable(f"no parser tool is available for {source.name}")

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

        return _ParsedText(text=review.text, tool=discovered.spec.name, review=review)

    if source.suffix.lower() == ".pdf" and depth < _MAX_RECURSION_DEPTH:
        try:
            return _parse_pdf_pages(
                source,
                cwd=cwd,
                home=home,
                out_dir=out_dir,
                memory=memory,
                pp_cfg=pp_cfg,
                logger=logger,
                depth=depth,
            )
        except Exception as exc:
            logger.info("PDF page-image fallback failed for %s: %s", source, exc)

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
        and item.spec.name != _PDF_SPLIT_TOOL
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


def _parse_pdf_pages(
    source: Path,
    *,
    cwd: Path,
    home: Path,
    out_dir: Path,
    memory: str,
    pp_cfg: Mapping[str, Any],
    logger,
    depth: int,
) -> _ParsedText:
    page_dir = _pdf_page_image_dir(source, cwd=cwd, out_dir=out_dir)
    raw = tool_cmd.run_tool(
        _PDF_SPLIT_TOOL,
        ["--path", str(source), "--out-dir", str(page_dir)],
        cwd=cwd,
        home=home,
        logger=logger,
    )
    if raw.kind != "json" or not isinstance(raw.value, Mapping):
        raise RuntimeError(f"{_PDF_SPLIT_TOOL} returned invalid result")

    pages = raw.value.get("pages")
    if not isinstance(pages, list) or not pages:
        raise RuntimeError(f"{_PDF_SPLIT_TOOL} produced no page images")

    parsed_pages: list[tuple[int, _ParsedText]] = []
    for item in pages:
        page = _as_mapping(item)
        page_number = int(page.get("page") or len(parsed_pages) + 1)
        image_file = page.get("image_file")
        if not isinstance(image_file, str) or not image_file:
            raise RuntimeError(f"{_PDF_SPLIT_TOOL} returned a page without image_file")
        page_parsed = _parse_source(
            Path(image_file),
            cwd=cwd,
            home=home,
            out_dir=out_dir,
            memory=memory,
            pp_cfg=pp_cfg,
            logger=logger,
            depth=depth + 1,
        )
        parsed_pages.append((page_number, page_parsed))

    text = _merge_page_text(parsed_pages)
    review = review_text(text, source_path=source, cwd=cwd, home=home, logger=logger)
    if not review.ok:
        raise RuntimeError(review.message)

    page_tools = ", ".join(
        f"page {page_number}: {parsed.tool}" for page_number, parsed in parsed_pages
    )
    return _ParsedText(
        text=review.text,
        tool=f"{_PDF_SPLIT_TOOL} ({page_tools})",
        review=review,
    )


def _pdf_page_image_dir(source: Path, *, cwd: Path, out_dir: Path) -> Path:
    return out_dir / ".pennyparse_pages" / Path(_relpath(source, cwd))


def _merge_page_text(parsed_pages: list[tuple[int, _ParsedText]]) -> str:
    sections: list[str] = []
    for page_number, parsed in parsed_pages:
        sections.append(f"## Page {page_number}\n\n{parsed.text.strip()}")
    return "\n\n".join(sections).rstrip() + "\n"


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
    for cost in _COST_ORDER_DESC:
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
    pp_cfg: Mapping[str, Any] | None = None,
) -> list[Path]:
    ignore_ext, ignore_folder = get_init_ignore_config(pp_cfg or load_pp_config(cwd=cwd))
    if paths:
        found: list[Path] = []
        for item in paths:
            path = item if item.is_absolute() else cwd / item
            if path.is_dir():
                found.extend(
                    _walk_targets(
                        path,
                        cwd=cwd,
                        output_dir=output_dir,
                        ignore_ext=ignore_ext,
                        ignore_folder=ignore_folder,
                    )
                )
            else:
                found.append(path)
        by_name = {path.resolve().as_posix(): path.resolve() for path in found}
        return [by_name[name] for name in sorted(by_name)]

    return _walk_targets(
        cwd,
        cwd=cwd,
        output_dir=output_dir,
        ignore_ext=ignore_ext,
        ignore_folder=ignore_folder,
    )


def _walk_targets(
    root: Path,
    *,
    cwd: Path,
    output_dir: Path,
    ignore_ext: set[str],
    ignore_folder: set[str],
) -> list[Path]:
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
            if not name.startswith(".")
            and name not in ignore_folder
            and (current / name).resolve() != output_dir
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            path = current / filename
            if path.resolve().is_relative_to(output_dir):
                continue
            ext = path.suffix.lstrip(".").lower()
            if ext and ext in ignore_ext:
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
