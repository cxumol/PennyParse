# Chat Completions Client

`src/pennyparse/_client.py` provides a small wrapper around `POST /chat/completions`.

Default `base_url` is `http://localhost:8080/v1`.

- `ChatClient` sends requests with `httpx`.
- `ChatSession` stores the `messages` array and appends new messages in place.
- `ChatStream` iterates parsed SSE payloads and merges the final assistant message.
- `get_chat_settings()` always resolves `base_url` to a concrete string before constructing `ChatClient`.

## Basic Request

```python
from pennyparse._client import ChatClient, ChatSession

session = ChatSession()
session.system("You are concise.")
session.user("Say hello in one short sentence.")

with ChatClient(model="gpt-4.1") as client:
    message = client.complete(session)

print(message["content"])
print(session.messages)
```

`client.complete(session)` returns the first assistant message and appends it back into `session.messages`.

## Streaming

```python
from pennyparse._client import ChatClient, ChatSession

session = ChatSession([{"role": "user", "content": "Count to three."}])

with ChatClient(model="gpt-4.1") as client:
    with client.stream(session) as stream:
        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            if text := delta.get("content"):
                print(text, end="")

    print(stream.message)
```

After the stream is fully consumed, `stream.message` contains the merged assistant message. If `session` was passed in, that final message is appended to `session.messages`.

## Tool Calls

```python
import json

from pennyparse._client import ChatClient, ChatSession

tools = [
    {
        "type": "function",
        "function": {
            "name": "lookup_weather",
            "description": "Get current weather.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]

session = ChatSession()
session.user("What's the weather in Singapore?")

with ChatClient(model="gpt-4.1") as client:
    assistant = client.complete(session, tools=tools)
    for call in assistant.get("tool_calls", []):
        result = {"city": "Singapore", "temperature_c": 31}
        session.tool(json.dumps(result), tool_call_id=call["id"])
    follow_up = client.complete(session, tools=tools)
```

`ChatStream` merges streamed `tool_calls` deltas in the same shape as a non-stream response. `stream.usage` is populated when the server includes usage in streamed chunks.

If you need another OpenAI-compatible endpoint, pass `base_url` explicitly.
