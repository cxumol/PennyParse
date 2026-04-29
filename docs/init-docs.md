# Init Docs

`pennyparse init docs` scans the current directory, enriches file metadata with available previewer tools, groups files, and writes a natural-language `./.pennyparse_memory.txt`.

The root `pennyparse.log` runtime file is skipped during scanning.

## Prerequisites

- Generate the user toolbox first:
  - `pennyparse init tools`
- Configure the chat model (required):
  - `PENNYPARSE_CHAT_MODEL` (and optionally `PENNYPARSE_CHAT_BASE`, `PENNYPARSE_CHAT_AUTHKEY` / `OPENAI_API_KEY`)
  - or `~/.pennyparse/pennyparse.settings.toml` / `./pennyparse.settings.toml` under `[aigc.api.chatcomp]`

## Usage

Run inside the directory that contains your documents:

```bash
cd /path/to/my_docs
pennyparse init docs
```

Overwrite an existing `./.pennyparse_memory.txt`:

```bash
pennyparse init docs --force
```

The command prints a JSON summary to `stdout` and writes natural-language parser context to `./.pennyparse_memory.txt`.

The memory file includes:

- one sentence for each group, covering filename traits, estimated parsing difficulty, and the suggested starting cost baseline
- one overall sentence covering the folder-level difficulty estimate and the suggested overall starting cost baseline

The memory file is intentionally not JSON. Runtime parser selection may read it as soft context, but it must not depend on a machine-readable `files` or `groups` schema.

## Configuration

Use `./pennyparse.settings.toml` (project) or `~/.pennyparse/pennyparse.settings.toml` (user) to customize:

- `[init.ignore]`
  - `ext`: extensions to ignore (without leading dots)
  - `folder`: folder names to skip during directory walk
- `[init.sampling]`
  - `by`: `first`, `random`, or `none`
  - `num`: sampled files per group
  - `pdf_page`: planned pages per sampled PDF
  - `pdf_page_total_max`: total planned pages per group

## Optional previewer dependencies

Some metadata enrichment is skipped unless these Python modules are importable:

- `PIL` (image width/height)
- `pymupdf` (PDF page/word counts)

Generated user tools with `scope = "previewer"` are also discovered. If they accept `--path`, their JSON or text result can contribute to the natural-language group summaries.
