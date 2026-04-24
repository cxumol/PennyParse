from __future__ import annotations

import json
from typing import Any

from ._client import ChatClient, ChatSession
from .config import pp_config
from .logger import get_logger
from .utils import extract_md_codeblock

logger = get_logger("utils_aigc")


def _extract_json_candidate(text: str) -> str:
    code = extract_md_codeblock(text)
    if code:
        return code

    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        return text[obj_start : obj_end + 1]

    arr_start = text.find("[")
    arr_end = text.rfind("]")
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        return text[arr_start : arr_end + 1]

    return text


def ai_chat_to_json_obj(client: ChatClient, session: ChatSession) -> Any:
    retry_limit = int(pp_config["aigc"]["agent"]["max_retry"])
    last_text = ""
    for attempt in range(1, retry_limit + 1):
        message = client.complete(session)
        last_text = str(message.get("content") or "").strip()
        if not last_text:
            continue

        candidate = _extract_json_candidate(last_text)
        try:
            return json.loads(candidate)
        except Exception as exc:
            logger.warning("ai_chat_to_json_obj attempt %s/%s failed: %s", attempt, retry_limit, exc)
            continue

    raise RuntimeError(f"failed to parse JSON from AI response after {retry_limit} attempts: {last_text!r}")
