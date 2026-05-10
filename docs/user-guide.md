# User Guide

PennyParse turns a mixed document folder into UTF-8 text. It works best when you initialize the folder once, let it learn cheap signals about the files, then parse through a stable tool set.

The workflow is graded. Embedded PDF text, clean scans, decorative type, handwriting, formulas, and tables do not deserve the same parser or the same bill. PennyParse starts with the cheapest plausible route, reviews the result, and escalates when the page asks for more.

## Install And Configure

Install PennyParse from PyPI with the common document backends:

```shell
python -m pip install "pennyparse[full]"
pennyparse --help
```

<details>
<summary>Prefer uv?</summary>

```shell
uv tool install "pennyparse[full]"
pennyparse --help
```

</details>

Configure an OpenAI-compatible chat-completions endpoint for LLM-backed initialization:

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

`OPENAI_API_KEY` is also accepted as the auth key. You can put the same values in `~/.pennyparse/pennyparse.settings.toml` or `./pennyparse.settings.toml`. Use [../src/pennyparse/pennyparse.settings.default.toml](../src/pennyparse/pennyparse.settings.default.toml) as the configuration reference.

The `full` extra includes the common local document backends. Minimal installs are possible, but most users should start with `pennyparse[full]`.

## Prepare User Tools

Create a toolbox description at `${HOME}/pennyparse.toolbox_user.txt`, or pass another file with `--from`. Follow the shape in [../src/pennyparse/pennyparse.toolbox_user.example.txt](../src/pennyparse/pennyparse.toolbox_user.example.txt).

Describe each external parser or API in plain technical prose: name, scope, cost, flags, strengths, limits, and how to call it. Vendor tool descriptions can be copied from official docs and trimmed to the facts PennyParse needs. Keep secrets in environment variables, then name those variables in the toolbox prose.

Generate the runtime:

```shell
pennyparse init tools
pennyparse init tools --from ./pennyparse.toolbox_user.txt --force
```

Review `${HOME}/.pennyparse/user_toolbox.py` before running generated tools with credentials.

## Initialize A Document Folder

`pennyparse init docs` requires `${HOME}/.pennyparse/user_toolbox.py`, so prepare user tools first. Then run this inside the folder that contains the documents:

```shell
cd /path/to/documents
pennyparse init docs
```

The command writes `./.pennyparse_memory.txt`. It is prose used as guidance. It records file groups, rough parsing difficulty, and cheap preview observations so later runs can start with better tool choices.

The full initialization command runs both steps:

```shell
pennyparse init --from /path/to/pennyparse.toolbox_user.txt --force
```

Its JSON output uses `result_file` for generated paths. `init docs` returns `groups` as a list of group records, plus `file_count` and `unmatched_count`.

## Parse Documents

Parse the current folder:

```shell
pennyparse run
```

Parse selected files or directories:

```shell
pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
```

`pennyparse run` requires both `${HOME}/.pennyparse/user_toolbox.py` and `./.pennyparse_memory.txt`. Its JSON summary reports `parsed_count`, `failed_count`, `skipped_count`, detailed `results`, `failures`, `skipped`, and `output_stats`.

Each successful source writes one UTF-8 text file under the output directory. The source-relative path is preserved:

```text
docs/report.pdf -> pennyparse_results/docs/report.pdf.txt
```

During a run, PennyParse appends short batch notes and a final output summary to `.pennyparse_memory.txt`. The notes help future runs and do not need hand editing.

## Inspect Tools

```shell
pennyparse tool --list
pennyparse tool --list --scope=parser
pennyparse tool pdf2txt --help
pennyparse tool pdf2txt --path report.pdf
```

Parser tool list output includes each available tool and its flags, for example `pdf2txt`, `pdf_pages_to_images`, and `pandoc2txt` when their optional backends are installed.

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

The full default settings file is [../src/pennyparse/pennyparse.settings.default.toml](../src/pennyparse/pennyparse.settings.default.toml).

## FAQ

**Do I need a chat model for every command?**

No. Tool listing and many local parsing paths can run without one. `init tools` and `init docs` need a configured model because they ask an agent to synthesize tools or read the shape of a folder.

**Why did a PDF become page images?**

The parser tried text extraction first. If review rejected it and the PDF image backend was available, PennyParse rendered pages, parsed each image, merged the page text, and reviewed the merged result.

**Why is `.pennyparse_memory.txt` prose?**

Because it is guidance for ranking and summarization. Filesystem discovery, tool validation, and output writing remain deterministic.

**Where should errors be read?**

The CLI prints command results to `stdout`, concise errors to `stderr`, and detailed logs to `pennyparse.log` in the working directory.
