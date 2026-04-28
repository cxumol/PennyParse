from __future__ import annotations

import os
import json
import random
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .._client import ChatClient, ChatSession
from ..config import ensure_user_state_dir, get_user_toolbox_path, load_pp_config
from ..logger import get_logger
from ..utils import extract_md_codeblock
from . import tool as tool_cmd

_COST_LEVELS = ("very low", "low", "medium", "high", "very high")
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}


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

    ignore_cfg = _as_mapping(_as_mapping(pp_cfg.get("init")).get("ignore"))
    ignore_ext = {str(item).lstrip(".").lower() for item in (ignore_cfg.get("ext") or [])}
    ignore_folder = {str(item) for item in (ignore_cfg.get("folder") or [])}
    sampling_cfg = _as_mapping(_as_mapping(pp_cfg.get("init")).get("sampling"))

    files = _walk_files(cwd=cwd, ignore_ext=ignore_ext, ignore_folder=ignore_folder)
    previewer_status, enriched = _enrich_with_preview_metadata(files, cwd=cwd, logger=logger)

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
    groups = _add_group_stats(groups, enriched, sampling_cfg=sampling_cfg)

    memory = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(cwd.resolve()),
        "result_file": str(result_path.resolve()),
        "previewer": previewer_status,
        "file_count": len(enriched),
        "files": enriched,
        "unmatched_files": unmatched,
        "groups": groups,
    }
    result_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    if not base_url:
        raise RuntimeError("aigc.api.chatcomp.base is required")
    authkey = str(chat.get("authkey") or "").strip()
    model = str(chat.get("model") or "").strip()
    return {
        "base_url": base_url,
        "api_key": authkey or None,
        "model": model or None,
    }


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
    cwd: Path,
    logger,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    discovered = {item.spec.name: item for item in tool_cmd.discover_builtin_tools(logger=logger)}
    pdf_avail = discovered.get("pdf_metadata")
    img_avail = discovered.get("img_metadata_px")
    status = {
        "pdf_metadata": {
            "available": bool(pdf_avail and pdf_avail.availability.available),
            "reason": "" if not pdf_avail else (pdf_avail.availability.reason or ""),
        },
        "img_metadata_px": {
            "available": bool(img_avail and img_avail.availability.available),
            "reason": "" if not img_avail else (img_avail.availability.reason or ""),
        },
    }
    for record in files:
        ext = record.get("ext") or ""
        abs_path = (cwd / record["path"]).resolve()
        meta = record.setdefault("meta", {})
        if ext == "pdf" and status["pdf_metadata"]["available"]:
            try:
                raw = tool_cmd.pdf_metadata(["--path", str(abs_path)])
            except Exception as exc:
                logger.warning("pdf_metadata failed for %s: %s", record["path"], exc)
                continue
            meta["pdf"] = {
                "page_count": int(raw.get("page_count") or 0),
                "word_count": int(raw.get("word_count") or 0),
            }
        elif ext in _IMAGE_EXTS and status["img_metadata_px"]["available"]:
            try:
                raw = tool_cmd.img_metadata_px(["--path", str(abs_path)])
            except Exception as exc:
                logger.warning("img_metadata_px failed for %s: %s", record["path"], exc)
                continue
            meta["image"] = {
                "width": int(raw.get("width") or 0),
                "height": int(raw.get("height") or 0),
            }
    return status, files


def _group_with_llm(
    files: list[dict[str, Any]],
    *,
    chat_settings: Mapping[str, Any],
    logger,
) -> list[dict[str, Any]] | None:
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
        with ChatClient(**dict(chat_settings), timeout=10.0) as client:
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
        elif ext in {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp"}:
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
) -> list[dict[str, Any]]:
    index = {str(item["path"]): item for item in files}
    for group in groups:
        matched = [path for path in group.get("matched") or [] if path in index]
        items = [index[path] for path in matched]
        group["file_count"] = len(items)
        group["total_bytes"] = sum(int(item.get("size") or 0) for item in items)
        group["ext_breakdown"] = _ext_breakdown(items)
        group["sample"] = _sample_summary(items, sampling_cfg=sampling_cfg)
    return groups


def _ext_breakdown(files: list[dict[str, Any]]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for record in files:
        ext = str(record.get("ext") or "")
        breakdown[ext] = breakdown.get(ext, 0) + 1
    return dict(sorted(breakdown.items(), key=lambda item: item[0]))


def _sample_summary(files: list[dict[str, Any]], *, sampling_cfg: Mapping[str, Any]) -> dict[str, Any]:
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
