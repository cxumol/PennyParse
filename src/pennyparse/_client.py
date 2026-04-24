from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

import httpx

__all__ = ["ChatClient", "ChatSession", "ChatStream", "response_message"]

Message = dict[str, Any]
_UNSET = object()


def _clone(value: Any) -> Any:
    return deepcopy(value)


def _clone_message(message: Mapping[str, Any]) -> Message:
    return dict(_clone(message))


def response_message(response: Mapping[str, Any], *, choice: int = 0) -> Message:
    choices = response.get("choices") or []
    if len(choices) <= choice:
        raise ValueError("chat completion returned no choices")
    return _clone_message(choices[choice]["message"])


@dataclass(slots=True)
class ChatSession:
    messages: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = [_clone_message(message) for message in self.messages]

    def add(self, role: str, content: Any = _UNSET, **extra: Any) -> Message:
        message: Message = {"role": role, **_clone(extra)}
        if content is not _UNSET:
            message["content"] = _clone(content)
        self.messages.append(message)
        return message

    def system(self, content: Any, **extra: Any) -> Message:
        return self.add("system", content, **extra)

    def user(self, content: Any, **extra: Any) -> Message:
        return self.add("user", content, **extra)

    def assistant(
        self,
        content: Any = None,
        *,
        tool_calls: Sequence[Mapping[str, Any]] | None = None,
        **extra: Any,
    ) -> Message:
        if tool_calls is not None:
            extra["tool_calls"] = [_clone_message(call) for call in tool_calls]
        return self.add("assistant", content, **extra)

    def tool(self, content: Any, *, tool_call_id: str, name: str | None = None, **extra: Any) -> Message:
        if name is not None:
            extra["name"] = name
        return self.add("tool", content, tool_call_id=tool_call_id, **extra)

    def extend(self, messages: Sequence[Mapping[str, Any]]) -> list[Message]:
        added = [_clone_message(message) for message in messages]
        self.messages.extend(added)
        return added

    def append_response(self, response: Mapping[str, Any], *, choice: int = 0) -> Message:
        message = response_message(response, choice=choice)
        self.messages.append(_clone_message(message))
        return message

    def snapshot(self) -> list[Message]:
        return [_clone_message(message) for message in self.messages]

    def clear(self) -> None:
        self.messages.clear()


def _iter_sse_data(lines: Iterator[str]) -> Iterator[str]:
    data_lines: list[str] = []
    for line in lines:
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


class ChatStream(Iterator[dict[str, Any]]):
    def __init__(self, response: httpx.Response, *, session: ChatSession | None = None) -> None:
        self._response = response
        self._session = session
        self._events = iter(_iter_sse_data(response.iter_lines()))
        self._role = "assistant"
        self._content_parts: list[str] = []
        self._tool_calls: list[Message | None] = []
        self._finished = False
        self._appended = False
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] | None = None

    def __iter__(self) -> ChatStream:
        return self

    def __next__(self) -> dict[str, Any]:
        if self._finished:
            raise StopIteration

        try:
            while True:
                data = next(self._events)
                if data == "[DONE]":
                    self._finish()
                    raise StopIteration
                payload = json.loads(data)
                self._merge(payload)
                return payload
        except StopIteration:
            self._finish()
            raise

    def __enter__(self) -> ChatStream:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @property
    def message(self) -> Message:
        message: Message = {"role": self._role}
        tool_calls = [_clone_message(call) for call in self._tool_calls if call]
        if self._content_parts:
            message["content"] = "".join(self._content_parts)
        else:
            message["content"] = None
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    def close(self) -> None:
        self._response.close()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._session is not None and not self._appended:
            self._session.messages.append(_clone_message(self.message))
            self._appended = True
        self._response.close()

    def _merge(self, payload: Mapping[str, Any]) -> None:
        usage = payload.get("usage")
        if usage is not None:
            self.usage = dict(_clone(usage))

        choices = payload.get("choices") or []
        if not choices:
            return

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            self.finish_reason = finish_reason

        delta = choice.get("delta") or {}
        role = delta.get("role")
        if role:
            self._role = role

        content = delta.get("content")
        if isinstance(content, str):
            self._content_parts.append(content)

        for tool_delta in delta.get("tool_calls") or []:
            index = tool_delta.get("index", 0)
            while len(self._tool_calls) <= index:
                self._tool_calls.append(None)

            call = self._tool_calls[index]
            if call is None:
                call = {}
                self._tool_calls[index] = call

            if "id" in tool_delta:
                call["id"] = tool_delta["id"]
            if "type" in tool_delta:
                call["type"] = tool_delta["type"]

            function_delta = tool_delta.get("function") or {}
            if not function_delta:
                continue

            function = call.setdefault("function", {})
            if "name" in function_delta:
                function["name"] = f"{function.get('name', '')}{function_delta['name']}"
            if "arguments" in function_delta:
                function["arguments"] = (
                    f"{function.get('arguments', '')}{function_delta['arguments']}"
                )


class ChatClient:
    endpoint = "chat/completions"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "http://localhost:8080/v1",
        timeout: float | httpx.Timeout | None = 60.0,
        headers: Mapping[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._owns_client = client is None
        if client is not None:
            self._client = client
            return

        merged_headers = {"accept": "application/json"}
        sk = api_key or os.getenv("OPENAI_API_KEY")
        if sk:
            merged_headers["authorization"] = f"Bearer {sk}"
        if headers:
            merged_headers.update(headers)

        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            headers=merged_headers,
            timeout=timeout,
        )

    def __enter__(self) -> ChatClient:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def create(
        self,
        messages: ChatSession | Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        payload, _ = self._payload(
            messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            **options,
        )
        response = self._client.post(self.endpoint, json=payload)
        response.raise_for_status()
        return response.json()

    def complete(
        self,
        messages: ChatSession | Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        choice: int = 0,
        **options: Any,
    ) -> Message:
        response = self.create(
            messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            **options,
        )
        message = response_message(response, choice=choice)
        if isinstance(messages, ChatSession):
            messages.messages.append(_clone_message(message))
        return message

    def stream(
        self,
        messages: ChatSession | Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        **options: Any,
    ) -> ChatStream:
        payload, session = self._payload(
            messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            **options,
        )
        request = self._client.build_request(
            "POST",
            self.endpoint,
            json=payload,
            headers={"accept": "text/event-stream"},
        )
        response = self._client.send(request, stream=True)
        try:
            response.raise_for_status()
        except Exception:
            response.close()
            raise
        return ChatStream(response, session=session)

    def _payload(
        self,
        messages: ChatSession | Sequence[Mapping[str, Any]],
        *,
        model: str | None,
        tools: Sequence[Mapping[str, Any]] | None,
        tool_choice: str | Mapping[str, Any] | None,
        stream: bool | None = None,
        **options: Any,
    ) -> tuple[dict[str, Any], ChatSession | None]:
        if isinstance(messages, ChatSession):
            payload_messages = messages.snapshot()
            session = messages
        else:
            payload_messages = [_clone_message(message) for message in messages]
            session = None

        resolved_model = model or self.model
        if resolved_model is None:
            raise ValueError("model is required")

        payload: dict[str, Any] = {"model": resolved_model, "messages": payload_messages}
        if tools is not None:
            payload["tools"] = _clone(list(tools))
        if tool_choice is not None:
            payload["tool_choice"] = _clone(tool_choice)
        if stream is not None:
            payload["stream"] = stream
        if options:
            payload.update(_clone(options))
        return payload, session
