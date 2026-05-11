---
name: pennyparse
description: Use PennyParse for cost-aware document parsing and OCR orchestration. Trigger when Codex needs to parse, OCR, review, or batch-convert mixed folders of PDFs, images, scans, office documents, handwriting, tables, formulas, or user-provided parser tools with the pennyparse CLI.
---

# PennyParse

Use PennyParse when the task is to turn document files into UTF-8 text or Markdown while choosing a sensible parser cost for each file. This skill is portable: callers should only rely on `SKILL.md`, optional `references/`, and ordinary shell commands.

## Workflow

1. Locate the CLI:

```shell
pennyparse --help
```

When working from this repository, prefer:

```shell
uv run pennyparse --help
```

2. Check available parser tools:

```shell
pennyparse tool --list --scope=parser
```

3. For external OCR, VLM, or API tools, write a concise toolbox description, then generate the runtime:

```shell
pennyparse init tools --from /path/to/pennyparse.toolbox_user.txt
```

Review `${HOME}/.pennyparse/user_toolbox.py` before running it with secrets.

4. Initialize the document folder:

```shell
cd /path/to/documents
pennyparse init docs
```

This creates `./.pennyparse_memory.txt`, which guides parser selection for later runs.

5. Parse files or folders:

```shell
pennyparse run --out-dir pennyparse_results
pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
```

Read the JSON summary from stdout. Check `pennyparse.log` in the working directory when a command fails.

## Operating Rules

- Keep secrets in environment variables or `.env`; do not pass API keys as argv.
- Run `init tools` before `init docs` when user tools are needed.
- Run `init docs` inside the target document folder, because `.pennyparse_memory.txt` is folder-local.
- Use `--force` only when the user intends to overwrite generated init assets.
- In restricted sandboxes where real `$HOME` is unavailable, set `HOME` to a writable workspace directory for the command.
- Preserve output directories unless the user asks to remove or overwrite them.

## References

Read `references/toolbox-and-config.md` when configuring chat endpoints, writing a user toolbox, handling sandboxed `$HOME`, or explaining expected generated files.

Read `references/agent-compatibility.md` when installing or adapting this skill for Claude Code, OpenClaw, Hermes Agent, Codex, or another SKILL.md-compatible caller.
