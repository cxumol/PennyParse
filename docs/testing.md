# Testing

Runtime code must not depend on repository demo fixtures.

`demo_assets/` is only test input data. Tests discover usable files by type at runtime instead of naming specific fixture files.

Run the local verification suite with:

```shell
python -m unittest discover -s tests
```

In this repository's lightweight environment, use the locked project environment and enable PDF support:

```shell
UV_CACHE_DIR=/tmp/uv-cache uv run --extra pdf python -m unittest discover -s tests
```

The dynamic tests create temporary fake `cwd` and `HOME` directories, write a minimal fake user toolbox there, and verify `pennyparse init docs` writes natural-language `.pennyparse_memory.txt`.

Parser tests use discovered demo assets and skip optional PDF assertions when the matching backend is not installed.

Run-command tests keep the same temporary `cwd` and `HOME` pattern. They verify that `pennyparse run` refuses missing init files, appends parser batch notes without replacing existing memory, and appends final output statistics.

Agent-loop tests use fake chat clients. They verify chat retry behavior, JSON tool-result feedback for tool exceptions, and `max_iter` termination without network calls.

For end-to-end CLI checks that need chat settings, load `.env` into the command environment, for example:

```shell
dotenv -f .env run -- python -m pennyparse tool --list
```

Manual end-to-end testing lives in `tests/e2e.sh`:

```shell
tests/e2e.sh
tests/e2e.sh -d _test_playground
```

The script uses the chosen directory as both `HOME` and `CWD`, copies `.env`, the toolbox TXT, and demo assets into it, then runs the real CLI flow:

- `pennyparse tool --list`
- `pennyparse init --force --from pennyparse.toolbox_user.txt`
- `pennyparse run docs --out-dir pennyparse_results_e2e_<timestamp>`

Its console output is intentionally verbose and safe to paste into a code assistant: commands, exit codes, file lists, generated memory, result previews, log tail, and sanitized config presence are printed in labeled sections.
