# User Guide

PennyParse parses a folder of documents into text files. It works best when you initialize the folder once, let it learn cheap hints about the files, then run parsing through a stable tool set.

## Install And Configure

Use the project environment:

```shell
uv run pennyparse --help
```

Configure an OpenAI-compatible chat-completions endpoint when you need LLM-backed initialization:

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

`OPENAI_API_KEY` is also accepted as the auth key. You can put the same values in `~/.pennyparse/pennyparse.settings.toml` or `./pennyparse.settings.toml`.

Optional document backends:

```shell
uv run --extra pdf pennyparse tool --list
uv run --extra docx pennyparse tool --list
```

## Prepare User Tools

Create a toolbox description at `${HOME}/pennyparse.toolbox_user.txt`, or pass another file with `--from`. Describe each external parser or API in plain technical prose: name, scope, cost, flags, credentials, and how to call it.

Generate the runtime:

```shell
pennyparse init tools
pennyparse init tools --from ./pennyparse.toolbox_user.txt --force
```

Review `${HOME}/.pennyparse/user_toolbox.py` before running generated tools with credentials.

## Initialize A Document Folder

Run this inside the folder that contains the documents:

```shell
cd /path/to/documents
pennyparse init docs
```

The command writes `./.pennyparse_memory.txt`. It is prose, not a database. It records file groups, rough parsing difficulty, and cheap preview observations so later runs can start with better tool choices.

The full initialization command runs both steps:

```shell
pennyparse init --from /path/to/pennyparse.toolbox_user.txt --force
```

## Parse Documents

Parse the current folder:

```shell
pennyparse run
```

Parse selected files or directories:

```shell
pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
```

Each successful source writes one UTF-8 text file under the output directory. The source-relative path is preserved:

```text
docs/report.pdf -> pennyparse_results/docs/report.pdf.txt
```

During a run, PennyParse appends short batch notes and a final output summary to `.pennyparse_memory.txt`. The notes help future runs; they are not required to be hand-edited.

## Inspect Tools

```shell
pennyparse tool --list
pennyparse tool --list --scope=previewer
pennyparse tool pdf2txt --help
pennyparse tool pdf2txt --path report.pdf
```

Unavailable tools are skipped from normal list output and logged with their reason. Common causes are missing optional Python packages or missing secret environment variables.

## Configuration

Configuration priority, from strongest to weakest:

1. Environment variables.
2. `./pennyparse.settings.toml`.
3. `~/.pennyparse/pennyparse.settings.toml`.
4. Package defaults.

Useful settings:

```toml
[aigc.api.chatcomp]
base = "http://localhost:8080/v1"
authkey = ""
model = ""

[output]
dir = "pennyparse_results"
ext = "auto"

[reviewer]
max_length = 1000
```

## FAQ

**Do I need a chat model for every command?**

No. Tool listing and many local parsing paths can run without one. `init tools` and `init docs` need a configured model because they ask an agent to synthesize tools or group a folder.

**Why did a PDF become page images?**

The parser tried text extraction first. If review rejected it and the PDF image backend was available, PennyParse rendered pages, parsed each image, merged the page text, and reviewed the merged result.

**Why is `.pennyparse_memory.txt` prose?**

Because it is guidance for ranking and summarization, not a source of truth. Filesystem discovery, tool validation, and output writing remain deterministic.

**Where should errors be read?**

The CLI prints command results to `stdout`, concise errors to `stderr`, and detailed logs to `pennyparse.log` in the working directory.
