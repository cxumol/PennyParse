from __future__ import annotations

import os
import json
import random
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .._client import ChatClient, ChatSession
from ..config import ensure_user_state_dir, get_init_ignore_config, get_user_toolbox_path, load_pp_config
from ..logger import get_logger
from ..utils import extract_md_codeblock
from . import tool as tool_cmd

_COST_LEVELS = ("very low", "low", "medium", "high", "very high")
_SAMPLE_TOOL_COSTS = {"very low", "low", "medium"}
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}
_OFFICE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp"}


def run_init_docs(
    *,
    overwrite: bool,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    logger = logger or get_logger("cmd.init_docs")
    ensure_user_state_dir(home=home)

    toolbox_path = get_user_toolbox_path(home=home)
    if not toolbox_path.exists():
        raise RuntimeError(f"{toolbox_path} not found. Run `pennyparse init tools` first.")

    result_path = cwd / ".pennyparse_memory.txt"
    if result_path.exists() and not overwrite:
        raise RuntimeError(f"refused to overwrite existing {result_path}")

    pp_cfg = load_pp_config(cwd=cwd, home=home)
    chat_settings = _chat_settings(pp_cfg)
    if not chat_settings.get("model"):
        raise RuntimeError("chat model is not configured")

    ignore_ext, ignore_folder = get_init_ignore_config(pp_cfg)
    sampling_cfg = _as_mapping(_as_mapping(pp_cfg.get("init")).get("sampling"))

    tools = _discover_tools(cwd=cwd, home=home, logger=logger)
    files = _walk_files(cwd=cwd, ignore_ext=ignore_ext, ignore_folder=ignore_folder)
    _previewer_status, enriched = _enrich_with_preview_metadata(files, tools=tools, cwd=cwd, home=home, logger=logger)

    llm_groups = _group_with_llm(enriched, chat_settings=chat_settings, logger=logger)
    if llm_groups is None:
        groups, unmatched = _group_heuristic(enriched)
    else:
        try:
            groups, unmatched = _apply_glob_groups(enriched, llm_groups)
        except Exception as exc:
            logger.info("LLM grouping rejected: %s", exc)
            groups, unmatched = _group_heuristic(enriched)

    groups, unmatched_count = _finalize_groups(groups, unmatched)
    groups = _add_group_stats(groups, enriched, sampling_cfg=sampling_cfg, tools=tools, cwd=cwd, home=home, logger=logger)

    memory = _memory_text(groups)
    result_path.write_text(memory, encoding="utf-8")
    return {
        "ok": True,
        "result_file": str(result_path),
        "groups": groups,
        "file_count": len(enriched),
        "unmatched_count": unmatched_count,
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _chat_settings(pp_cfg: Mapping[str, Any]) -> dict[str, Any]:
    chat = _as_mapping(_as_mapping(_as_mapping(pp_cfg.get("aigc")).get("api")).get("chatcomp"))
    base_url = str(chat.get("base") or "").strip()
    model = str(chat.get("model") or "").strip()
    if not base_url:
        raise RuntimeError("aigc.api.chatcomp.base is required")
    authkey = str(chat.get("authkey") or "").strip()
    return {
        "base_url": base_url,
        "api_key": authkey or None,
        "model": model or None,
    }


def _discover_tools(*, cwd: Path, home: Path, logger) -> list[tool_cmd.DiscoveredTool]:
    return [
        *tool_cmd.discover_builtin_tools(logger=logger),
        *tool_cmd.discover_user_tools_for_home(cwd=cwd, home=home, logger=logger),
    ]


def _walk_files(*, cwd: Path, ignore_ext: set[str], ignore_folder: set[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root, dirnames, filenames in os.walk(cwd, topdown=True):
        root_path = Path(root)
        rel_root = root_path.relative_to(cwd)
        if rel_root.parts and any(part.startswith(".") for part in rel_root.parts):
            dirnames[:] = []
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in ignore_folder
        ]

        for filename in filenames:
            if filename.startswith("."):
                continue
            path = root_path / filename
            if root_path == cwd and filename == "pennyparse.log":
                continue
            if not path.is_file():
                continue
            rel_path = path.relative_to(cwd).as_posix()
            ext = path.suffix.lstrip(".").lower()
            if ext and ext in ignore_ext:
                continue
            size = path.stat().st_size
            records.append({"path": rel_path, "size": size, "ext": ext, "meta": {}})
    records.sort(key=lambda item: item["path"])
    return records


def _enrich_with_preview_metadata(
    files: list[dict[str, Any]],
    *,
    tools: list[tool_cmd.DiscoveredTool],
    cwd: Path,
    home: Path,
    logger,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    previewers = [item for item in tools if item.spec.scope == "previewer"]
    status = {
        item.spec.name: {
            "available": item.availability.available,
            "reason": item.availability.reason or "",
        }
        for item in previewers
    }
    for record in files:
        ext = record.get("ext") or ""
        abs_path = (cwd / record["path"]).resolve()
        meta = record.setdefault("meta", {})
        for previewer in previewers:
            if not previewer.availability.available or not _previewer_accepts_path(previewer):
                continue
            if not _previewer_matches_ext(previewer.spec.name, ext):
                continue
            try:
                result = tool_cmd.run_tool(
                    previewer.spec.name,
                    ["--path", str(abs_path)],
                    cwd=cwd,
                    home=home,
                    logger=logger,
                )
            except Exception as exc:
                logger.warning("%s failed for %s: %s", previewer.spec.name, record["path"], exc)
                continue
            if result.kind == "binary":
                continue
            raw = result.value
            _merge_previewer_meta(meta, previewer.spec.name, raw)
    return status, files


def _previewer_accepts_path(previewer: tool_cmd.DiscoveredTool) -> bool:
    return previewer.spec.has_flag("path")


def _previewer_matches_ext(name: str, ext: str) -> bool:
    if name.startswith("pdf_") or "pdf" in name:
        return ext == "pdf"
    if name.startswith("img_") or "image" in name:
        return ext in _IMAGE_EXTS
    return True


def _merge_previewer_meta(meta: dict[str, Any], name: str, raw: Any) -> None:
    if name == "pdf_metadata" and isinstance(raw, Mapping):
        meta["pdf"] = {
            "page_count": int(raw.get("page_count") or 0),
            "word_count": int(raw.get("word_count") or 0),
        }
        return
    if name == "img_metadata_px" and isinstance(raw, Mapping):
        meta["image"] = {
            "width": int(raw.get("width") or 0),
            "height": int(raw.get("height") or 0),
        }
        return
    previewer_meta = meta.setdefault("previewer", {})
    if isinstance(previewer_meta, dict):
        previewer_meta[name] = raw


def _group_with_llm(
    files: list[dict[str, Any]],
    *,
    chat_settings: Mapping[str, Any],
    logger,
) -> list[dict[str, Any]] | None:
    if not chat_settings.get("model"):
        logger.info("LLM grouping skipped: chat model is not configured")
        return None

    prompt = (
        "You group local document files by parsing difficulty.\n"
        "Input: a JSON list of file records with relative paths and metadata.\n"
        "Output: JSON only with this schema:\n"
        "{\n"
        '  "groups": [\n'
        "    {\n"
        '      "name": "short_id",\n'
        '      "globs": ["relative/glob/**/*.pdf"],\n'
        f'      "cost_baseline": one of {list(_COST_LEVELS)!r}\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- globs MUST be relative paths.\n"
        "- globs MUST NOT contain '..' and MUST NOT start with '/'.\n"
        "- globs MUST NOT overlap across groups.\n"
        "- prefer a small number of groups.\n"
        "- do not emit prose.\n"
    )
    session = ChatSession()
    session.system(prompt)
    session.user(json.dumps({"files": files}, ensure_ascii=False))

    try:
        with ChatClient(**dict(chat_settings)) as client:
            assistant = client.complete(session, temperature=0)
    except Exception as exc:
        logger.info("LLM grouping skipped: %s", exc)
        return None

    content = assistant.get("content")
    text = content if isinstance(content, str) else ""
    payload = extract_md_codeblock(text) or text
    try:
        data = json.loads(payload)
    except Exception as exc:
        logger.info("LLM grouping invalid JSON: %s", exc)
        return None

    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list) or not groups:
        return None

    normalized: list[dict[str, Any]] = []
    for item in groups:
        if not isinstance(item, Mapping):
            return None
        name = str(item.get("name") or "").strip()
        if not name:
            return None
        globs = item.get("globs") or item.get("glob") or []
        if isinstance(globs, str):
            globs = [globs]
        if not isinstance(globs, list) or not globs:
            return None
        glob_list = [str(g).strip() for g in globs if str(g).strip()]
        if not glob_list:
            return None
        if any(g.startswith("/") or ".." in g.split("/") for g in glob_list):
            return None

        cost = str(item.get("cost_baseline") or "").strip().lower()
        if cost not in _COST_LEVELS:
            return None
        normalized.append({"name": name, "globs": glob_list, "cost_baseline": cost})
    return normalized


def _apply_glob_groups(
    files: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    paths = [str(item["path"]) for item in files]
    matched_by_group: list[dict[str, Any]] = []
    ownership: dict[str, str] = {}

    for group in groups:
        name = str(group["name"])
        globs = list(group["globs"])
        matched: list[str] = []
        for path in paths:
            p = PurePosixPath(path)
            if any(p.match(pattern) for pattern in globs):
                prev = ownership.get(path)
                if prev is not None and prev != name:
                    raise RuntimeError(f"LLM group overlap: {path} matches {prev} and {name}")
                ownership[path] = name
                matched.append(path)
        matched_by_group.append(
            {
                "name": name,
                "globs": globs,
                "cost_baseline": group["cost_baseline"],
                "matched": sorted(set(matched)),
            }
        )

    unmatched = sorted([path for path in paths if path not in ownership])
    return matched_by_group, unmatched


def _group_heuristic(files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    pdf_text: list[str] = []
    pdf_scanned: list[str] = []
    images: list[str] = []
    office: list[str] = []
    other: list[str] = []

    for record in files:
        path = str(record["path"])
        ext = str(record.get("ext") or "")
        if ext == "pdf":
            pdf = _as_mapping(_as_mapping(record.get("meta")).get("pdf"))
            page_count = int(pdf.get("page_count") or 0)
            word_count = int(pdf.get("word_count") or 0)
            if page_count > 0 and (word_count / page_count) >= 15:
                pdf_text.append(path)
            else:
                pdf_scanned.append(path)
        elif ext in _IMAGE_EXTS:
            images.append(path)
        elif ext in _OFFICE_EXTS:
            office.append(path)
        else:
            other.append(path)

    groups: list[dict[str, Any]] = []
    if pdf_text:
        groups.append({"name": "pdf_text", "globs": sorted(pdf_text), "cost_baseline": "low", "matched": sorted(pdf_text)})
    if pdf_scanned:
        groups.append(
            {"name": "pdf_scan", "globs": sorted(pdf_scanned), "cost_baseline": "medium", "matched": sorted(pdf_scanned)}
        )
    if images:
        groups.append({"name": "images", "globs": sorted(images), "cost_baseline": "medium", "matched": sorted(images)})
    if office:
        groups.append({"name": "office", "globs": sorted(office), "cost_baseline": "low", "matched": sorted(office)})
    if other:
        groups.append({"name": "other", "globs": sorted(other), "cost_baseline": "medium", "matched": sorted(other)})

    return groups, []


def _finalize_groups(
    groups: list[dict[str, Any]],
    unmatched: list[str],
) -> tuple[list[dict[str, Any]], int]:
    unmatched_count = len(unmatched)
    if unmatched:
        groups = [
            *groups,
            {
                "name": "misc",
                "globs": list(unmatched),
                "cost_baseline": "medium",
                "matched": list(unmatched),
            },
        ]
    return groups, unmatched_count


def _add_group_stats(
    groups: list[dict[str, Any]],
    files: list[dict[str, Any]],
    *,
    sampling_cfg: Mapping[str, Any],
    tools: list[tool_cmd.DiscoveredTool],
    cwd: Path,
    home: Path,
    logger,
) -> list[dict[str, Any]]:
    index = {str(item["path"]): item for item in files}
    for group in groups:
        matched = [path for path in group.get("matched") or [] if path in index]
        items = [index[path] for path in matched]
        group["file_count"] = len(items)
        group["total_bytes"] = sum(int(item.get("size") or 0) for item in items)
        group["ext_breakdown"] = _ext_breakdown(items)
        group["sample"] = _sample_summary(
            items,
            sampling_cfg=sampling_cfg,
            tools=tools,
            cwd=cwd,
            home=home,
            logger=logger,
        )
        group["summary"] = _group_summary(group)
    return groups


def _group_summary(group: Mapping[str, Any]) -> str:
    name = str(group.get("name") or "group")
    file_count = int(group.get("file_count") or 0)
    baseline = str(group.get("cost_baseline") or "medium")
    ext_breakdown = _as_mapping(group.get("ext_breakdown"))
    ext_text = ", ".join(
        f"{key or 'no_ext'}:{value}"
        for key, value in sorted(ext_breakdown.items(), key=lambda item: str(item[0]))
    )
    if not ext_text:
        ext_text = "no files"
    sample_paths = _sample_paths_for_text(group)
    sample_text = f" such as {sample_paths}" if sample_paths else ""
    observations = _sample_observations_for_text(group)
    observation_text = f" Sample check: {observations}." if observations else ""
    difficulty = _difficulty_text(baseline)
    return (
        f"{name} group contains {file_count} file(s) ({ext_text}){sample_text}; "
        f"the filename and preview metadata suggest {difficulty} parsing difficulty; "
        f"start from {baseline} cost parsing.{observation_text}"
    )


def _overall_summary(groups: list[dict[str, Any]]) -> str:
    file_count = sum(int(group.get("file_count") or 0) for group in groups)
    if not groups:
        return "Overall, no files were found; start from medium cost parsing only after adding documents."
    highest = max(
        (str(group.get("cost_baseline") or "medium") for group in groups),
        key=lambda cost: _COST_LEVELS.index(cost) if cost in _COST_LEVELS else _COST_LEVELS.index("medium"),
    )
    names = ", ".join(str(group.get("name") or "group") for group in groups)
    return (
        f"Overall, this folder has {file_count} file(s) across {len(groups)} group(s): {names}; "
        f"start from {highest} cost parsing as the overall baseline."
    )


def _memory_text(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.extend(str(group.get("summary") or _group_summary(group)) for group in groups)
    lines.append(_overall_summary(groups))
    return "\n".join(lines).rstrip() + "\n"


def _sample_paths_for_text(group: Mapping[str, Any]) -> str:
    matched = group.get("matched") or []
    if not isinstance(matched, list):
        return ""
    paths = [str(path) for path in matched[:3]]
    if not paths:
        return ""
    suffix = " and others" if len(matched) > len(paths) else ""
    return ", ".join(paths) + suffix


def _sample_observations_for_text(group: Mapping[str, Any]) -> str:
    sample = _as_mapping(group.get("sample"))
    files = sample.get("files")
    if not isinstance(files, list):
        return ""
    observations = [
        _clip_text(str(item.get("observation") or ""), limit=160)
        for item in files
        if isinstance(item, Mapping) and str(item.get("observation") or "").strip()
    ]
    return "; ".join(observations[:2])


def _difficulty_text(cost: str) -> str:
    if cost in {"very low", "low"}:
        return "low"
    if cost == "medium":
        return "moderate"
    return "high"


def _ext_breakdown(files: list[dict[str, Any]]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for record in files:
        ext = str(record.get("ext") or "")
        breakdown[ext] = breakdown.get(ext, 0) + 1
    return dict(sorted(breakdown.items(), key=lambda item: item[0]))


def _sample_summary(
    files: list[dict[str, Any]],
    *,
    sampling_cfg: Mapping[str, Any],
    tools: list[tool_cmd.DiscoveredTool],
    cwd: Path,
    home: Path,
    logger,
) -> dict[str, Any]:
    mode = str(sampling_cfg.get("by") or "random").strip().lower()
    num = int(sampling_cfg.get("num") or 0)
    pdf_page = int(sampling_cfg.get("pdf_page") or 0)
    pdf_page_total_max = int(sampling_cfg.get("pdf_page_total_max") or 0)

    if mode == "none" or num <= 0:
        return {"mode": mode, "files": [], "pdf_pages_planned": []}

    ordered = sorted(files, key=lambda item: item["path"])
    sample_files = _pick_sample_paths([item["path"] for item in ordered], num=num, mode=mode)
    picked = [item for item in ordered if item["path"] in set(sample_files)]
    sample_payload = [
        {
            "path": item["path"],
            "ext": item.get("ext") or "",
            "size": int(item.get("size") or 0),
            "meta": item.get("meta") or {},
            "observation": _sample_observation(item, tools=tools, cwd=cwd, home=home, logger=logger),
        }
        for item in picked
    ]
    return {
        "mode": mode,
        "files": sample_payload,
        "pdf_pages_planned": _plan_pdf_pages(picked, per_pdf=pdf_page, total_max=pdf_page_total_max),
    }


def _pick_sample_paths(paths: list[str], *, num: int, mode: str) -> list[str]:
    if num <= 0 or not paths:
        return []
    ordered = sorted(paths)
    if mode == "first":
        return ordered[:num]
    rng = random.Random(0)
    if num >= len(ordered):
        return ordered
    return sorted(rng.sample(ordered, k=num))


def _plan_pdf_pages(files: list[dict[str, Any]], *, per_pdf: int, total_max: int) -> list[dict[str, Any]]:
    if per_pdf <= 0 or total_max <= 0:
        return []
    remaining = total_max
    plans: list[dict[str, Any]] = []
    for item in files:
        if remaining <= 0:
            break
        if str(item.get("ext") or "") != "pdf":
            continue
        pdf = _as_mapping(_as_mapping(item.get("meta")).get("pdf"))
        page_count = int(pdf.get("page_count") or 0)
        effective_pages = page_count if page_count > 0 else None
        count = min(per_pdf, remaining) if effective_pages is None else min(per_pdf, effective_pages, remaining)
        pages = list(range(count))
        plans.append({"path": item["path"], "page_count": effective_pages, "pages": pages})
        remaining -= count
    return plans


def _sample_observation(
    item: Mapping[str, Any],
    *,
    tools: list[tool_cmd.DiscoveredTool],
    cwd: Path,
    home: Path,
    logger,
) -> str:
    ext = str(item.get("ext") or "")
    if ext != "pdf" and ext not in _IMAGE_EXTS and ext not in _OFFICE_EXTS:
        return ""

    abs_path = (cwd / str(item["path"])).resolve()
    observations: list[str] = []
    for tool in _sample_tools_for_ext(tools, ext):
        try:
            result = tool_cmd.run_tool(
                tool.spec.name,
                ["--path", str(abs_path)],
                cwd=cwd,
                home=home,
                logger=logger,
            )
        except SystemExit as exc:
            logger.warning("%s sample exited for %s: %s", tool.spec.name, item["path"], exc)
            continue
        except Exception as exc:
            logger.warning("%s sample failed for %s: %s", tool.spec.name, item["path"], exc)
            continue
        observation = _observation_from_tool_result(tool.spec.name, result.value, result.kind)
        if observation:
            observations.append(observation)
        if len(observations) >= 2:
            break
    if observations:
        return "; ".join(observations)
    return _observation_from_meta(item)


def _sample_tools_for_ext(
    tools: list[tool_cmd.DiscoveredTool],
    ext: str,
) -> list[tool_cmd.DiscoveredTool]:
    candidates = [
        item
        for item in tools
        if item.availability.available
        and item.spec.cost in _SAMPLE_TOOL_COSTS
        and item.spec.has_flag("path")
        and _sample_tool_flags_are_satisfiable(item.spec)
        and _sample_tool_matches_ext(item.spec.name, item.spec.scope, ext)
    ]
    return sorted(candidates, key=lambda item: (_COST_LEVELS.index(item.spec.cost), item.spec.name))


def _sample_tool_flags_are_satisfiable(spec: tool_cmd.ToolSpec) -> bool:
    return {_sample_flag_name(flag) for flag in spec.flags} <= {"path"}


def _sample_flag_name(name: str) -> str:
    return name.strip().lstrip("-").replace("_", "-")


def _sample_tool_matches_ext(name: str, scope: str, ext: str) -> bool:
    if scope == "previewer":
        return _previewer_matches_ext(name, ext)
    if ext == "pdf":
        return "pdf" in name
    if ext in _IMAGE_EXTS:
        return name.startswith("img_") or "image" in name or "ocr" in name
    if ext in _OFFICE_EXTS:
        return "pandoc" in name or "office" in name or "doc" in name
    return False


def _observation_from_tool_result(name: str, value: Any, kind: str) -> str:
    if kind == "binary":
        return ""
    if isinstance(value, str):
        text = _clip_text(" ".join(value.split()), limit=220)
        if not text:
            return ""
        return f"{name}: {text}"
    if isinstance(value, Mapping):
        flattened = ", ".join(
            f"{key}={_clip_text(str(val), limit=60)}"
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
            if isinstance(val, (str, int, float, bool)) or val is None
        )
        if flattened:
            return f"{name}: {flattened}"
    return ""


def _observation_from_meta(item: Mapping[str, Any]) -> str:
    meta = _as_mapping(item.get("meta"))
    pdf = _as_mapping(meta.get("pdf"))
    if pdf:
        return f"metadata: pages={int(pdf.get('page_count') or 0)}, words={int(pdf.get('word_count') or 0)}"
    image = _as_mapping(meta.get("image"))
    if image:
        return f"metadata: image={int(image.get('width') or 0)}x{int(image.get('height') or 0)}"
    return ""


def _clip_text(text: str, *, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
