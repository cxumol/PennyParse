# PennyParse

[English](#english) | [简体中文](#简体中文)

![Brand banner](docs/assets/readme-brand-banner.png)

PennyParse turns a folder of mixed, unruly documents into clean UTF-8 text. It is built for the files that break ordinary extraction: scanned PDFs, photos of paper, handwritten pages, low-quality copies, tables, charts, and folders where easy and hard documents sit side by side.

Its bet is simple: document parsing should be routed, reviewed, and priced like a workflow. Use cheap local extraction when it is enough. Escalate only when the page asks for it.

![PennyParse logo](docs/assets/readme-logo.png)

---

## English

## Why PennyParse

Most document parsers make you choose one backend up front. That is a poor fit for real folders. Tesseract OCR can be the right tool for plain printed pages, but it cannot reliably handle decorative type, rare characters, and degraded scans. A top multimodal LLM can read many clean scanned novels beautifully, but sending every readable page to it wastes compute, time, and money.

PennyParse is built around graded parsing. A cheap parser gets the first try when the document looks easy. Costlier OCR, VLMs, and cloud APIs enter when the content needs them. The point is resource allocation with judgment.

The same logic applies among multimodal models. One model may be stronger on handwriting. Another may preserve mathematical formulas better. Another may handle tables or mixed-language pages with fewer scars. PennyParse gives an agent enough context to assign work by page character instead of treating every model as interchangeable.

PennyParse treats parsing as an adaptive workflow:

- It previews a folder before parsing it.
- It records a short natural-language memory for that folder.
- It chooses parser tools by file difficulty and previous results.
- It reviews extracted text before writing final output, even when the reviewer is text-only.
- It lets you plug in local tools, OCR services, VLMs, or cloud APIs through a small tool contract.

The review step matters. A text-only LLM cannot see the page, but it can still catch broken prose, duplicated headers, table drift, missing paragraphs, and layout damage that makes the result read wrong. That turns parsing from a single blind shot into an agentic loop with a second opinion.

![Core value comparison](docs/assets/readme-core-value-comparison.png)

## First Run

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

For LLM-backed commands, configure an OpenAI-compatible chat-completions endpoint:

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

`OPENAI_API_KEY` is also accepted as the auth key. The same values can live in `~/.pennyparse/pennyparse.settings.toml`, `./pennyparse.settings.toml`, or `.env`.

List builtin tools:

```shell
pennyparse tool --list
```

Parse a folder:

```shell
cd /path/to/documents
pennyparse init docs
pennyparse run --out-dir pennyparse_results
```

If you want PennyParse to call your own OCR, VLM, shell command, or API, describe it in plain text first:

```text
$HOME/pennyparse.toolbox_user.txt
```

Then generate the tool runtime:

```shell
pennyparse init tools
```

PennyParse writes executable Python to `$HOME/.pennyparse/user_toolbox.py`. Review that file before using it with real credentials.

## CLI Example

```text
$ pennyparse tool --list --scope=parser
pdf2txt          scope: parser cost: very low   Extract embedded PDF text
pdf_page_image   scope: parser cost: low        Render PDF pages as images
pandoc_docx      scope: parser cost: low        Convert office documents through Pandoc

$ cd ~/cases/mixed_docs
$ pennyparse init docs
{
  "ok": true,
  "groups": 4,
  "memory_file": "/home/me/cases/mixed_docs/.pennyparse_memory.txt"
}

$ pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
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
CLI  （pennyparse init / run / tool）
 │
AI Agents  （init_tools / parser / reviewer）
 │
Tool chain  （builtin tools + user_toolbox.py）
```

![Architecture diagram](docs/assets/readme-architecture.png)

PennyParse has three working planes:

| Plane | Owns | Examples |
| --- | --- | --- |
| CLI and commands | Stable behavior | config, paths, logging, stdout and stderr contracts |
| Tool plane | Extraction capability | PDF text, image thumbnails, Pandoc, user OCR, VLM APIs |
| Agent plane | Judgment under uncertainty | grouping files, choosing tools, reviewing extracted text |

The parser never calls vendors directly. It asks the tool registry what is available, runs a parser through the same boundary as the CLI, and sends candidate text to review before writing output. When the review fails, the agent can retry with another tool or a higher-cost route, guided by folder memory and the last failure.

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

PennyParse 做一件细事：把一篮子性情不同的文档，慢慢理成干净的 UTF-8 文本。扫描 PDF、纸页照片、手写稿、影印本、表格、图表，许多寻常工具一见便手生；同在一个目录里，浅的浅，深的深，尤其如此。

它的意思很朴素：容易的页，先请便宜的工具去读；读不动了，再请更贵的 OCR、VLM 或云端 API。算力如灯油，明处不必添灯，暗处才该多照一照。

许多解析器要人一开始便选定后端。目录清爽时，这样也成；文档一杂，便难免两头落空。Tesseract OCR 遇见普通印刷页，往往够用；碰到艺术字型、生僻字符、磨损扫描件，便真是搞不定。顶级多模态 LLM 读多数扫描清晰的出版小说，自然从容；可每一页都这样送去读，花费的算力、时间与钱，都显得过满。

PennyParse 因此把解析做成分级流程。文档看着容易，低成本工具先试；内容显出难处，再交给更强的 OCR、VLM 或云端 API。分级解析才是正道：让合适的能力去做合适的事。

多模态模型之间也各有心性。甲也许更会认手写，乙也许更会守住数学公式，丙也许处理表格和中英混排更清爽。PennyParse 让 Agent 先看材料，再分派任务，不把所有模型都看成一把尺子。

PennyParse 把解析变成一个自适应流程：

- 先预览整个目录，再开始解析。
- 为目录写一份自然语言解析记忆。
- 根据文件难度和前序结果选择解析工具。
- 在写入最终结果前审阅抽取文本，审阅者即使没有视觉能力，也仍有用处。
- 通过小而清晰的工具接口约定接入本地工具、OCR 服务、VLM 或云端 API。

Agentic Loop 的好处，正在这一次回看。纯文本 LLM 看不见原页，却能听出句子是否顺，标题是否重，表格是否漂移，段落是否少了一截。解析不再是一锤子买卖，而有校对，有改道，有第二眼。

![核心价值对比图](docs/assets/readme-core-value-comparison.png)

## 快速开始

从 PyPI 安装 PennyParse，并带上常用文档后端：

```shell
python -m pip install "pennyparse[full]"
pennyparse --help
```

<details>
<summary>偏好 uv？</summary>

```shell
uv tool install "pennyparse[full]"
pennyparse --help
```

</details>

需要 LLM 支持的命令时，配置兼容 OpenAI chat-completions 的端点：

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

也可以使用 `OPENAI_API_KEY`。同样的配置可以写入 `~/.pennyparse/pennyparse.settings.toml`、`./pennyparse.settings.toml` 或 `.env`。

查看内建工具：

```shell
pennyparse tool --list
```

解析一个目录：

```shell
cd /path/to/documents
pennyparse init docs
pennyparse run --out-dir pennyparse_results
```

如果要让 PennyParse 调用你自己的 OCR、VLM、命令行工具或 API，先用普通文本描述它：

```text
$HOME/pennyparse.toolbox_user.txt
```

然后生成工具运行时：

```shell
pennyparse init tools
```

PennyParse 会把可执行 Python 写入 `$HOME/.pennyparse/user_toolbox.py`。带真实凭据使用前，请先审阅这份文件。

## CLI 运行示例

```text
$ pennyparse tool --list --scope=parser
pdf2txt          scope: parser cost: very low   Extract embedded PDF text
pdf_page_image   scope: parser cost: low        Render PDF pages as images
pandoc_docx      scope: parser cost: low        Convert office documents through Pandoc

$ cd ~/cases/mixed_docs
$ pennyparse init docs
{
  "ok": true,
  "groups": 4,
  "memory_file": "/home/me/cases/mixed_docs/.pennyparse_memory.txt"
}

$ pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
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
命令行  （pennyparse init / run / tool）
 │
AI Agents 智能体  （init_tools / parser / reviewer）
 │
工具链  （builtin tools + user_toolbox.py）
```

![架构图](docs/assets/readme-architecture.png)

| 层次 | 负责 | 例子 |
| --- | --- | --- |
| CLI 与命令 | 稳定行为 | 配置、路径、日志、stdout 和 stderr 边界 |
| 工具层 | 解析能力 | PDF 文本、图像缩略图、Pandoc、用户 OCR、VLM API |
| Agent 层 | 不确定场景下的判断 | 文件分组、工具选择、抽取结果审阅 |

解析器不直接拨打厂商服务。它先问工具注册表：此地有什么可用；再沿着与 CLI 相同的边界运行工具。候选文本须经审阅，才写入输出目录。若审阅不过，Agent 会参考目录记忆和上一次失败，另择工具，或把成本往上提一级。

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
- `src/pennyparse/cmd/tool.py`：内建和用户工具接口约定。
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

PennyParse 处于 pre-alpha 阶段。命令形态已经可用，后续仍可能有破坏性变更。若你也关心文档解析、本地优先工具、边界清楚的 Agent 工作流，此时加入，正好能改到根上。
