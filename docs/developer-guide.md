# Developer Guide

PennyParse is a small Python CLI with agent-assisted edges. Development is easiest when you keep the same split as the runtime: deterministic command code owns contracts; agents supply judgments behind those contracts.

## Environment

Use the locked project environment:

```shell
uv run pennyparse --help
```

Enable optional backends only when a task needs them:

```shell
uv run --extra pdf python -m unittest discover -s tests
uv run --extra docx pennyparse tool --list
```

For end-to-end checks that need chat settings, put them in `.env` or export them:

```shell
PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
PENNYPARSE_CHAT_MODEL=your-model
PENNYPARSE_CHAT_AUTHKEY=your-key
```

## Code Map

- `src/pennyparse/cli.py`: Typer command boundary and stream handling.
- `src/pennyparse/config.py`: layered settings, `.env`, and environment overrides.
- `src/pennyparse/cmd/`: command implementations for init, tools, and run.
- `src/pennyparse/agent/`: model-facing loops for tool generation, parsing, and review.
- `src/pennyparse/_client.py`: OpenAI-compatible chat-completions client with a 1234 second default request timeout.
- `src/pennyparse/utils_aigc.py`: shared retry and tool-call loop helpers.
- `tests/`: dynamic unit tests and manual end-to-end script.

## Local State In Tests

Runtime code reads `${HOME}/.pennyparse/user_toolbox.py` and `./.pennyparse_memory.txt`. Tests should isolate both `HOME` and `cwd` with temporary directories. Do not depend on repository demo assets by name; discover suitable files by type, or skip optional assertions when their backend is absent.

## Verification

Run unit tests:

```shell
python -m unittest discover -s tests
```

Run the suite in the project environment with PDF support:

```shell
UV_CACHE_DIR=/tmp/uv-cache uv run --extra pdf python -m unittest discover -s tests
```

Run the manual CLI flow:

```shell
tests/e2e.sh
tests/e2e.sh -d _test_playground
```

The script uses the chosen directory as both `HOME` and `cwd`, copies test inputs, runs the real CLI flow, and prints commands, exit codes, generated memory, output previews, and log tails.

## Development Rules

Preserve the stdout/stderr contract. A command result must be machine-readable from `stdout` without filtering logs.

Keep tool contracts narrow. New tools should enter through specs and handlers, not through parser-specific branches. If a backend is optional, report unavailability with a reason.

Use agents where fixed code would encode brittle judgment: interpreting user toolbox prose, grouping heterogeneous document folders, choosing among uncertain parser results, and reviewing extraction quality. Use deterministic code for paths, config, validation, imports, subprocess boundaries, and output writes.

When a code change affects behavior, update the relevant document under `docs/` in the same change.

## Debugging

Start with `pennyparse.log`. It records unavailable tools, validation failures, skipped optional dependencies, parser tool failures, and review fallback reasons.

For tool issues, inspect discovery first:

```shell
pennyparse tool --list
pennyparse tool <toolname> --help
```

For initialization issues, inspect the generated state files:

```text
${HOME}/.pennyparse/user_toolbox.py
./.pennyparse_memory.txt
```

For agent issues, lower the problem to the loop contract: what messages entered, what tool call or code block came back, what deterministic validator rejected, and whether the failure was fed back into the next turn.
