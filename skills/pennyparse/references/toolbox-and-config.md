# Toolbox And Configuration

## Chat Endpoint

LLM-backed commands need an OpenAI-compatible chat-completions endpoint:

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

`OPENAI_API_KEY` is also accepted as the auth key. The same values can live in `./pennyparse.settings.toml`, `~/.pennyparse/pennyparse.settings.toml`, or `.env`.

## User Toolbox

A toolbox description is plain prose. Include only facts the generator needs:

- tool name
- scope, usually `parser` or `previewer`
- cost, one of `very low`, `low`, `medium`, `high`, `very high`
- supported file types
- required flags
- required secret environment variables
- request shape or shell command
- output shape
- known limits

Example:

```text
my_ocr_api

Scope: parser
Cost: medium
Input: image files through --path /path/to/image.png
Secrets: MY_OCR_API_KEY
Call: POST https://example.test/v1/ocr with multipart file upload and Bearer auth.
Output: return only recognized Markdown text.
Limits: max 10 MB per file.
```

Generate the runtime:

```shell
pennyparse init tools --from ./pennyparse.toolbox_user.txt
```

PennyParse writes `${HOME}/.pennyparse/user_toolbox.py`. Treat it as executable generated code and review it before using real credentials.

## Sandboxed HOME

If the runtime cannot read or write the real home directory, use a writable workspace directory:

```shell
HOME=/path/to/workspace-home pennyparse init tools --from ./pennyparse.toolbox_user.txt
HOME=/path/to/workspace-home pennyparse init docs
HOME=/path/to/workspace-home pennyparse run --out-dir pennyparse_results
```

Keep the same `HOME` across `init tools`, `init docs`, and `run`, otherwise PennyParse will look for a different `user_toolbox.py`.

## Generated Files

- `${HOME}/.pennyparse/user_toolbox.py`: generated Python tool runtime.
- `./.pennyparse_memory.txt`: folder-local parsing memory, created by `init docs`.
- `./pennyparse.log`: command log in the current working directory.
- `./pennyparse_results/`: default output directory unless configured or overridden.

## Useful Commands

```shell
pennyparse tool --list
pennyparse tool --list --scope=previewer
pennyparse tool --list --scope=parser
pennyparse tool <toolname> --help
pennyparse tool <toolname> --path /path/to/file
```
