<img alt="PennyParse logo rmbg640" style="float: right;right: 0px" src="https://github.com/user-attachments/assets/36372b56-d9a7-4a2b-a73d-36f4db5668fb" width="96" div align=right>

# PennyParse 厘晰

[![Publish to PyPI](https://github.com/cxumol/PennyParse/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/cxumol/PennyParse/actions/workflows/publish-pypi.yml)
[![PyPI version](https://badge.fury.io/py/pennyparse.svg)](https://badge.fury.io/py/pennyparse)
<!-- [![PyPI Downloads](https://img.shields.io/pepy/dt/pennyparse)](https://pepy.tech/projects/pennyparse) -->
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Versions](https://img.shields.io/pypi/pyversions/pennyparse)](https://pypi.org/project/pennyparse/)

![Brand banner](https://github.com/user-attachments/assets/c3247c7f-52db-4a7b-b46f-b543f2d88e5b)



> Penny parse, penny wise.

Document parsing should be tiered, routed, and reviewed. Use cheap local extraction when it is enough. Escalate only when the AI agent finds the page needs it.

- Tesseract OCR can't handle artistic fonts and rare characters; top-tier multimodal LLMs can easily parse published novels but waste computing power and time, so you need a tiered approach. 
- Even among multimodal large models, Model A is better at handwriting recognition, while Model B excels at formula recognition, so you need an Agent to handle allocation and scheduling.
- The benefit of an Agentic Loop for document recognition is proofreading; even if the proofreading uses an LLM without vision capabilities, it can still check from angles like whether the text reads smoothly or whether the layout is misaligned.
- You've collected 12 OCR APIs and want to digitize 34 different varieties of documents? Leave it to the AI Agent, PennyParse will handle it for you.

> 丝帛简牍数码书，千金半厘辨分殊。  
> 何须一模破万卷，自能调度在慧枢。

- Tesseract OCR 搞不定艺术字形和生僻字符; 顶级多模态 LLM 解析出版小说轻轻松松却浪费算力时间, 所以, 你需要分级。
- 同样是多模态大模型, 模型甲更擅长手写识别, 模型乙更胜任公式识别, 所以, 你需要 Agent 帮你分配调度。
- Agentic Loop 用于文档识别, 好处在于有校对, 即使校对选用了不带视觉功能的 LLM, 也可以从 读着是否通顺､ 排版是否错位､ 表格是否漂移 等方面校对。
- 你搭了 12 种 OCR 模型, 要录入 34 份不同品种的档案? 放心交给 Agent, 让 PennyParse 帮你搞定｡

---

## English

English | [简体中文](#简体中文)

## Why PennyParse

![Core value comparison](https://github.com/user-attachments/assets/a4e0b2e2-0b49-4ae8-92e9-ee2f6eb722f5)

Instead of "yet another doc parser", PennyParse is an Agentic Workflow that orchestrates multiple parsing tools for graded document parsing and judgment-based resource allocation.

A cheap parser gets the first try when the document looks easy. Costlier OCR, VLMs, and cloud APIs enter when the content needs them.

PennyParse gives its agent enough context to assign work by page character instead of treating every model as interchangeable.

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

`OPENAI_API_KEY` is also accepted as the auth key. The same values can live in `~/.pennyparse/pennyparse.settings.toml`, `./pennyparse.settings.toml`, or `.env`. Use [src/pennyparse/pennyparse.settings.default.toml](src/pennyparse/pennyparse.settings.default.toml) as the configuration reference.

List builtin tools:

```shell
pennyparse tool --list
```

If you want PennyParse to call your own OCR, VLM, shell command, or API, describe it in plain text first:

```text
$HOME/pennyparse.toolbox_user.txt
```

The toolbox description format can follow [src/pennyparse/pennyparse.toolbox_user.example.txt](src/pennyparse/pennyparse.toolbox_user.example.txt). Tool descriptions can be copied from the vendor's official docs, trimmed to name, scope, cost, flags, limits, and call shape. Put secrets such as API keys in environment variables, then name those variables in the toolbox prose.

Then generate the tool runtime:

```shell
pennyparse init tools
```

PennyParse writes executable Python to `$HOME/.pennyparse/user_toolbox.py`. Review that file before using it with real credentials.

Then parse a folder:

```shell
cd /path/to/documents
pennyparse init docs
pennyparse run --out-dir pennyparse_results
```

## CLI Example

```text
$ pennyparse tool --list --scope=parser
pdf2txt	scope: parser cost: low	Extract PDF text with PyMuPDF.
	--path /path/to/file.pdf

pdf_pages_to_images	scope: parser cost: medium	Render each PDF page to a PNG image with PyMuPDF.
	--path /path/to/file.pdf
	--out-dir /path/to/page-images

pandoc2txt	scope: parser cost: low	Convert office documents to plain text with Pandoc.
	--path /path/to/file

$ cd ~/cases/mixed_docs
$ pennyparse init tools --from ./pennyparse.toolbox_user.txt
{
  "ok": true,
  "usertools_valid": [
    "siliconflow_deepseekocr"
  ],
  "usertools_failed": [],
  "agent_turns": 1,
  "result_file": "/home/me/.pennyparse/user_toolbox.py"
}

$ pennyparse init docs
{
  "ok": true,
  "result_file": "/home/me/cases/mixed_docs/.pennyparse_memory.txt",
  "groups": [
    {
      "name": "pdf_text",
      "...": "..."
    }
  ],
  "file_count": 18,
  "unmatched_count": 0
}

$ pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
{
  "ok": true,
  "out_dir": "/home/me/cases/mixed_docs/pennyparse_results",
  "parsed_count": 18,
  "failed_count": 0,
  "skipped_count": 0,
  "results": [
    {
      "source": "invoice.pdf",
      "output_file": "/home/me/cases/mixed_docs/pennyparse_results/invoice.pdf.txt",
      "...": "..."
    }
  ],
  "failures": [],
  "skipped": [],
  "output_stats": {
    "file_count": 18,
    "...": "..."
  }
}
```

The JSON examples above keep the real field names and shorten long arrays with `"..."`.

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

![Architecture diagram](https://github.com/user-attachments/assets/e09c8cb7-06ad-4aa2-828f-8dfffa7f1939)

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

The complete default shape is in [src/pennyparse/pennyparse.settings.default.toml](src/pennyparse/pennyparse.settings.default.toml).

## Contributing

PennyParse is beta, which makes it a good time to shape the core. Useful contributions are small and concrete:

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

PennyParse is beta. The command shape is usable, and breaking changes are still possible. The project is looking for contributors who care about document extraction, local-first tooling, and agent workflows with clear boundaries.

---

## 简体中文

[English](#english) | 简体中文

## 为什么是 PennyParse

并非 "Yet Another 图文识别工具"，PennyParse 是用来统筹调度多种图文识别工具的 Agentic Workflow。 把一窝鸡飞狗跳的文档，整理成干净的纯文本。

容易的页，先请便宜的工具去读；读不动了，再请更贵的OCR、VLM或云端API。算力如灯油，明处不必添灯，暗处才该多照一照。

Agent先品尝解析工具和文档的调性，再分派任务。 带上 Agent 的解析不再是一锤子买卖，而是有校对，有打回重做，有请大师傅出山。

![核心价值对比图](https://github.com/user-attachments/assets/a4e0b2e2-0b49-4ae8-92e9-ee2f6eb722f5)

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

也可以使用 `OPENAI_API_KEY`。同样的配置可以写入 `~/.pennyparse/pennyparse.settings.toml`、`./pennyparse.settings.toml` 或 `.env`。配置格式可参考 [src/pennyparse/pennyparse.settings.default.toml](src/pennyparse/pennyparse.settings.default.toml)。

查看内建工具：

```shell
pennyparse tool --list
```

如果要让 PennyParse 调用你自己的 OCR、VLM、命令行工具或 API，先用普通文本描述它：

```text
$HOME/pennyparse.toolbox_user.txt
```

用户工具箱的写法可参考 [src/pennyparse/pennyparse.toolbox_user.example.txt](src/pennyparse/pennyparse.toolbox_user.example.txt)。各工具说明可以从对应官方文档摘取，再保留工具名、用途范围、成本、参数、限制和调用方式。API key 等机要内容放进环境变量，在工具箱说明中写环境变量名即可。

然后生成工具运行时：

```shell
pennyparse init tools
```

PennyParse 会启用 AI Agent 把 pennyparse.toolbox_user.txt 转换成的可执行脚本写入 `$HOME/.pennyparse/user_toolbox.py`。真实使用前，请先审阅这份文件。

然后解析一个目录：

```shell
cd /path/to/documents
pennyparse init docs
pennyparse run --out-dir pennyparse_results
```

## CLI 运行示例

```text
$ pennyparse tool --list --scope=parser
pdf2txt	scope: parser cost: low	Extract PDF text with PyMuPDF.
	--path /path/to/file.pdf

pdf_pages_to_images	scope: parser cost: medium	Render each PDF page to a PNG image with PyMuPDF.
	--path /path/to/file.pdf
	--out-dir /path/to/page-images

pandoc2txt	scope: parser cost: low	Convert office documents to plain text with Pandoc.
	--path /path/to/file

$ cd ~/cases/mixed_docs
$ pennyparse init tools --from ./pennyparse.toolbox_user.txt
{
  "ok": true,
  "usertools_valid": [
    "siliconflow_deepseekocr"
  ],
  "usertools_failed": [],
  "agent_turns": 1,
  "result_file": "/home/me/.pennyparse/user_toolbox.py"
}

$ pennyparse init docs
{
  "ok": true,
  "result_file": "/home/me/cases/mixed_docs/.pennyparse_memory.txt",
  "groups": [
    {
      "name": "pdf_text",
      "...": "..."
    }
  ],
  "file_count": 18,
  "unmatched_count": 0
}

$ pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
{
  "ok": true,
  "out_dir": "/home/me/cases/mixed_docs/pennyparse_results",
  "parsed_count": 18,
  "failed_count": 0,
  "skipped_count": 0,
  "results": [
    {
      "source": "invoice.pdf",
      "output_file": "/home/me/cases/mixed_docs/pennyparse_results/invoice.pdf.txt",
      "...": "..."
    }
  ],
  "failures": [],
  "skipped": [],
  "output_stats": {
    "file_count": 18,
    "...": "..."
  }
}
```

上面的 JSON 保留真实字段名，较长的数组用 `"..."` 缩短展示。

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

![架构图](https://github.com/user-attachments/assets/e09c8cb7-06ad-4aa2-828f-8dfffa7f1939)

| 层次 | 负责 | 例子 |
| --- | --- | --- |
| CLI 与命令 | 稳定行为 | 配置、路径、日志、stdout 和 stderr 边界 |
| 工具层 | 解析能力 | PDF 文本、图像缩略图、Pandoc、用户 OCR、VLM API |
| Agent 层 | 不确定场景下的判断 | 文件分组、工具选择、抽取结果审阅 |

解析 Agent 先问工具注册表："咱们工具箱里都有啥?" 再选取工具执行。解析得到的候选文本，须经审阅才写入输出目录。审阅不过的，Agent 自会另择工具。

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

完整默认配置见 [src/pennyparse/pennyparse.settings.default.toml](src/pennyparse/pennyparse.settings.default.toml)。

## 参与贡献

PennyParse 处于 beta 阶段，现在很适合参与塑造。适合下手的贡献包括：

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

- `src/pennyparse/cli.py`：命令行入口。
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

PennyParse 处于 beta 阶段。命令形态已经可用，后续仍可能有破坏性变更。若你也关心文档解析、本地优先工具、边界清楚的 Agentic 工作流，此时加入，正好赶上。
