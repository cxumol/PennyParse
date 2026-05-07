# PennyParse

[English](#english) | [简体中文](#简体中文)

![Brand banner placeholder](docs/assets/readme-brand-banner.png)

PennyParse turns a folder of mixed, messy documents into clean UTF-8 text. It is built for the files that break ordinary extraction: scanned PDFs, photos of paper, handwritten pages, low-quality copies, tables, charts, and folders where easy and hard documents sit side by side.

The idea is simple: spend the cheapest useful effort first, then escalate only when the document earns it.

---

## English

## Why PennyParse

Most document parsers make you choose one backend up front. That works for a tidy folder. It wastes money on easy files and fails quietly on hard ones.

PennyParse treats parsing as an adaptive workflow:

- It previews a folder before parsing it.
- It records a short natural-language memory for that folder.
- It chooses parser tools by file difficulty and previous results.
- It reviews extracted text before writing final output.
- It lets you plug in local tools, OCR services, VLMs, or cloud APIs through a small tool contract.

![Core value comparison placeholder](docs/assets/readme-core-value-comparison.png)

## First Run

Use the locked project environment:

```shell
git clone https://github.com/your-org/PennyParse.git
cd PennyParse
uv run pennyparse --help
```

For LLM-backed commands, configure an OpenAI-compatible chat-completions endpoint:

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

`OPENAI_API_KEY` is also accepted as the auth key. The same values can live in `~/.pennyparse/pennyparse.settings.toml`, `./pennyparse.settings.toml`, or `.env`.

List builtin tools:

```shell
uv run pennyparse tool --list
uv run --extra pdf pennyparse tool --list
uv run --extra docx pennyparse tool --list
```

Parse a folder:

```shell
cd /path/to/documents
uv run pennyparse init docs
uv run pennyparse run --out-dir pennyparse_results
```

If you want PennyParse to call your own OCR, VLM, shell command, or API, describe it in plain text first:

```text
$HOME/pennyparse.toolbox_user.txt
```

Then generate the tool runtime:

```shell
uv run pennyparse init tools
```

PennyParse writes executable Python to `$HOME/.pennyparse/user_toolbox.py`. Review that file before using it with real credentials.

## CLI Example

```text
$ uv run pennyparse tool --list --scope=parser
pdf2txt          scope: parser cost: very low   Extract embedded PDF text
pdf_page_image   scope: parser cost: low        Render PDF pages as images
pandoc_docx      scope: parser cost: low        Convert office documents through Pandoc

$ cd ~/cases/mixed_docs
$ uv run pennyparse init docs
{
  "ok": true,
  "groups": 4,
  "memory_file": "/home/me/cases/mixed_docs/.pennyparse_memory.txt"
}

$ uv run pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
{
  "ok": true,
  "parsed": 18,
  "failed": 1,
  "out_dir": "pennyparse_results"
}
```

## What You Get

PennyParse preserves relative paths in the output directory:

```text
docs/report.pdf -> pennyparse_results/docs/report.pdf.txt
scans/page-01.jpg -> pennyparse_results/scans/page-01.jpg.md
```

It also maintains a folder memory file:

```text
.pennyparse_memory.txt
```

That memory is plain prose. It helps later parser runs choose a sensible starting cost without forcing the project into a rigid database schema.

## Architecture

```text
              CLI
               |
     config, logging, paths
               |
        deterministic commands
               |
   +-----------+-----------+
   |                       |
 tools                  agents
   |                       |
 local parsers       plan, choose, review
 OCR / VLM / APIs        |
   +-----------+-----------+
               |
          reviewed text
               |
        pennyparse_results/
```

![Detailed architecture diagram placeholder](docs/assets/readme-detailed-architecture.png)

PennyParse has three working planes:

| Plane | Owns | Examples |
| --- | --- | --- |
| CLI and commands | Stable behavior | config, paths, logging, stdout and stderr contracts |
| Tool plane | Extraction capability | PDF text, image thumbnails, Pandoc, user OCR, VLM APIs |
| Agent plane | Judgment under uncertainty | grouping files, choosing tools, reviewing extracted text |

The parser never calls vendors directly. It asks the tool registry what is available, runs a parser through the same boundary as the CLI, and sends the candidate text to review before writing output.

## Configuration

Configuration priority:

1. Environment variables.
2. `./pennyparse.settings.toml`.
3. `~/.pennyparse/pennyparse.settings.toml`.
4. Package defaults.

Common settings:

```toml
[aigc.api.chatcomp]
base = "http://localhost:8080/v1"
authkey = ""
model = ""
model_hasVision = true

[output]
dir = "pennyparse_results"
ext = "auto"
parser_summary_batch = 5

[reviewer]
max_length = 1000
```

## Contributing

PennyParse is pre-alpha, which makes it a good time to shape the core. Useful contributions are small and concrete:

- Add or improve builtin parser tools.
- Add demo assets that represent real document pain.
- Improve reviewer prompts and failure cases.
- Strengthen tests around CLI behavior, tool discovery, and generated user tools.
- Write adapters for common OCR, VLM, and document conversion backends.
- Improve docs for a workflow you actually tried.

Start with:

```shell
uv run python -m unittest discover -s tests
uv run --extra pdf python -m unittest discover -s tests
```

Useful code paths:

- `src/pennyparse/cli.py`: command boundary.
- `src/pennyparse/cmd/`: command implementations.
- `src/pennyparse/cmd/tool.py`: builtin and user tool contract.
- `src/pennyparse/agent/`: model-facing loops.
- `src/pennyparse/config.py`: layered settings.
- `tests/`: current test suite and CLI flow checks.

## Documentation

- [User Guide](docs/user-guide.md)
- [Architecture](docs/architecture.md)
- [Agent Loop](docs/agent-loop.md)
- [Tool Mechanism](docs/tool-mechanism.md)
- [Developer Guide](docs/developer-guide.md)

## Status

PennyParse is pre-alpha. The command shape is usable, and breaking changes are still possible. The project is looking for contributors who care about document extraction, local-first tooling, and agent workflows with clear boundaries.

---

## 简体中文

## 为什么是 PennyParse

PennyParse 把一个目录里的混合文档解析成干净的 UTF-8 文本。它面向普通解析工具容易失手的材料：扫描 PDF、纸本文档照片、手写稿、模糊影印件、表格、图表，以及同一目录中难度参差不齐的文件。

它的核心思路很直接：先用足够便宜的办法处理简单文件，只有确实需要时才升级到更贵的 OCR、VLM 或云端 API。

大多数文档解析器要求你预先选定一个后端。文件整齐时这很好用；文件复杂时，要么浪费成本，要么静默失败。

PennyParse 把解析变成一个自适应流程：

- 先预览整个目录，再开始解析。
- 为目录写一份自然语言解析记忆。
- 根据文件难度和前序结果选择解析工具。
- 在写入最终结果前审阅抽取文本。
- 通过小而清晰的工具契约接入本地工具、OCR 服务、VLM 或云端 API。

![核心价值对比图占位](docs/assets/readme-core-value-comparison.zh-hans.png)

## 快速开始

使用锁定的项目环境：

```shell
git clone https://github.com/your-org/PennyParse.git
cd PennyParse
uv run pennyparse --help
```

需要 LLM 支持的命令时，配置兼容 OpenAI chat-completions 的端点：

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

也可以使用 `OPENAI_API_KEY`。同样的配置可以写入 `~/.pennyparse/pennyparse.settings.toml`、`./pennyparse.settings.toml` 或 `.env`。

查看内建工具：

```shell
uv run pennyparse tool --list
uv run --extra pdf pennyparse tool --list
uv run --extra docx pennyparse tool --list
```

解析一个目录：

```shell
cd /path/to/documents
uv run pennyparse init docs
uv run pennyparse run --out-dir pennyparse_results
```

如果要让 PennyParse 调用你自己的 OCR、VLM、命令行工具或 API，先用普通文本描述它：

```text
$HOME/pennyparse.toolbox_user.txt
```

然后生成工具运行时：

```shell
uv run pennyparse init tools
```

PennyParse 会把可执行 Python 写入 `$HOME/.pennyparse/user_toolbox.py`。带真实凭据使用前，请先审阅这份文件。

## CLI 运行示例

```text
$ uv run pennyparse tool --list --scope=parser
pdf2txt          scope: parser cost: very low   Extract embedded PDF text
pdf_page_image   scope: parser cost: low        Render PDF pages as images
pandoc_docx      scope: parser cost: low        Convert office documents through Pandoc

$ cd ~/cases/mixed_docs
$ uv run pennyparse init docs
{
  "ok": true,
  "groups": 4,
  "memory_file": "/home/me/cases/mixed_docs/.pennyparse_memory.txt"
}

$ uv run pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
{
  "ok": true,
  "parsed": 18,
  "failed": 1,
  "out_dir": "pennyparse_results"
}
```

## 产出结果

PennyParse 会在输出目录中保留相对路径：

```text
docs/report.pdf -> pennyparse_results/docs/report.pdf.txt
scans/page-01.jpg -> pennyparse_results/scans/page-01.jpg.md
```

它还会维护一份目录记忆：

```text
.pennyparse_memory.txt
```

这份记忆是普通自然语言文本。后续解析会参考它选择合适的起始成本，但项目不会因此被锁进僵硬的数据表结构。

## 三层架构概览

```text
              CLI
               |
      配置、日志、路径
               |
        确定性的命令层
               |
   +-----------+-----------+
   |                       |
 工具层                  Agent 层
   |                       |
 本地解析器            规划、选择、审阅
 OCR / VLM / API          |
   +-----------+-----------+
               |
          审阅后的文本
               |
        pennyparse_results/
```

![详细架构图占位](docs/assets/readme-detailed-architecture.zh-hans.png)

| 层次 | 负责 | 例子 |
| --- | --- | --- |
| CLI 与命令 | 稳定行为 | 配置、路径、日志、stdout 和 stderr 边界 |
| 工具层 | 解析能力 | PDF 文本、图像缩略图、Pandoc、用户 OCR、VLM API |
| Agent 层 | 不确定场景下的判断 | 文件分组、工具选择、抽取结果审阅 |

解析器不会直接调用厂商服务。它先询问工具注册表有哪些工具可用，再通过与 CLI 相同的边界运行工具，候选文本通过审阅后才写入输出目录。

## 配置

配置优先级从高到低：

1. 环境变量。
2. `./pennyparse.settings.toml`。
3. `~/.pennyparse/pennyparse.settings.toml`。
4. 包内默认配置。

常用配置：

```toml
[aigc.api.chatcomp]
base = "http://localhost:8080/v1"
authkey = ""
model = ""
model_hasVision = true

[output]
dir = "pennyparse_results"
ext = "auto"
parser_summary_batch = 5

[reviewer]
max_length = 1000
```

## 参与贡献

PennyParse 处于 pre-alpha 阶段，现在很适合参与塑造核心。适合下手的贡献包括：

- 增加或改进内建解析工具。
- 增加能代表真实文档难题的 demo assets。
- 改进 reviewer prompt 和失败案例。
- 加强 CLI 行为、工具发现、用户工具生成相关测试。
- 为常见 OCR、VLM、文档转换后端编写适配器。
- 把你实际跑通过的流程写进文档。

开始前可先运行：

```shell
uv run python -m unittest discover -s tests
uv run --extra pdf python -m unittest discover -s tests
```

常用代码入口：

- `src/pennyparse/cli.py`：命令边界。
- `src/pennyparse/cmd/`：命令实现。
- `src/pennyparse/cmd/tool.py`：内建和用户工具契约。
- `src/pennyparse/agent/`：面向模型的循环。
- `src/pennyparse/config.py`：分层配置。
- `tests/`：当前测试套件和 CLI 流程检查。

## 文档

- [用户指南](docs/user-guide.zh-hans.md)
- [架构说明](docs/architecture.md)
- [Agent 循环](docs/agent-loop.md)
- [工具机制](docs/tool-mechanism.md)
- [开发者指南](docs/developer-guide.md)

## 项目状态

PennyParse 处于 pre-alpha 阶段。命令形态已经可用，后续仍可能发生破坏性变更。项目欢迎关心文档解析、本地优先工具和边界清晰的 Agent 工作流的贡献者。
