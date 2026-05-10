# Developer Guide

PennyParse is a small Python CLI with agent-assisted edges. Development is easiest when the code keeps the same split as the runtime: deterministic command code owns contracts; agents supply judgment behind those contracts.

The project is about graded parsing. Cheap text extraction, local OCR, remote OCR, VLMs, and multimodal LLMs should not be treated as one interchangeable bucket. Code changes should preserve that routing discipline: inspect cheaply, spend carefully, review before writing.

## Environment

Use the locked project environment:

```shell
uv run pennyparse --help
```

<details>
<summary>Prefer pip?</summary>

```shell
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[full]"
pennyparse --help
```

</details>

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

`init tools` validates generated handlers with demo assets packaged under `pennyparse/demo_assets/`. The validation copies those files into a temporary working directory, runs handlers from that directory, points `TMPDIR`, `TEMP`, and `TMP` there, and removes the directory on normal exit.

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
It copies repository-local runtime inputs when present: `.env`, `pennyparse.settings.toml`, `.pennyparse/pennyparse.settings.toml`, `pennyparse.toolbox_user.txt`, and files under `demo_assets/`.

## Release To PyPI

The release workflow is `.github/workflows/publish-pypi.yml`. It builds with `uv build` and uploads with `uv publish`.

Use PyPI Trusted Publishing for the project. In PyPI, add a trusted publisher for this repository, workflow `publish-pypi.yml`, and environment `pypi`. No PyPI token is needed in GitHub secrets.

Release from a version tag:

```shell
uv lock
uv build
git tag v0.1.0
git push origin v0.1.0
```

<details>
<summary>Prefer pip build tools?</summary>

```shell
python -m pip install build twine
python -m build
python -m twine check dist/*
```

</details>

## Development Rules

Preserve the stdout/stderr contract. A command result must be machine-readable from `stdout` without filtering logs.

Keep tool contracts narrow. New tools should enter through specs and handlers, not through parser-specific branches. If a backend is optional, report unavailability with a reason.

Use agents where fixed code would encode brittle judgment: interpreting user toolbox prose, grouping heterogeneous document folders, choosing among uncertain parser results, and reviewing extraction quality. Use deterministic code for paths, config, validation, imports, subprocess boundaries, and output writes.

Protect the review loop. Even a text-only model can reject broken extraction by reading the result for fluency, ordering, repeated noise, and layout drift. Changes that bypass review should be treated as behavior changes, not plumbing.

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

For agent issues, reduce the problem to the loop contract: what messages entered, what tool call or code block came back, what deterministic validator rejected, and whether the failure was fed back into the next turn.

When `init tools` cannot reach the chat endpoint, it still writes an importable fallback `user_toolbox.py`. The fallback records inferred tool names as unavailable with the request failure reason. Treat this as a degraded initialization path: builtin local tools can still run, and remote user tools become active only after a successful regeneration.
