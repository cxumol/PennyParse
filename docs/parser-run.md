# Parser Run

`pennyparse run` is the document parsing entrypoint.

## Usage

```shell
pennyparse run
pennyparse run --out-dir pennyparse_results
pennyparse run invoice.pdf scans/
```

When explicit paths are omitted, PennyParse walks the current directory. If `./.pennyparse_memory.txt` exists, the parser reads its natural-language notes as soft context for tool ordering.

## Parser Selection

The parser agent uses available `scope=parser` tools that accept `--path` and return text or JSON.

- PDF files prefer `pdf2txt`.
- Office-style documents prefer `pandoc2txt`.
- User parser tools can handle images and higher-cost parsing backends.
- Natural-language cost hints from `.pennyparse_memory.txt` are used as a soft ranking signal.

## Reviewer

The reviewer marks empty extraction as `major_revision`.

When no chat model is configured, non-empty local extraction is accepted. When a chat model is configured, the reviewer asks it for `pass`, `minor_revision`, or `major_revision` JSON.

Reviewer prompt input is truncated by `[reviewer].max_length`. This truncation is only for audit context. A `pass` result writes the parser tool's complete original text, and a `minor_revision` result writes the complete original text after applying reviewer-provided regex patches.

## Output

Each successful source writes one UTF-8 text file under the output directory. The source relative path is preserved, and the original filename is kept in the output name:

```text
docs/report.pdf -> pennyparse_results/docs/report.pdf.txt
```
