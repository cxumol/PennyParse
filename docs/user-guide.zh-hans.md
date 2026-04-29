# 用户指南

PennyParse 会把一个目录里的混合文档解析成文本文件。推荐流程是：先生成工具运行时，再初始化文档目录，最后执行解析。

## 安装与配置

在项目环境中运行：

```shell
uv run pennyparse --help
```

需要 LLM 支持的初始化命令时，配置一个兼容 OpenAI chat-completions 的端点：

```shell
export PENNYPARSE_CHAT_BASE=http://localhost:8080/v1
export PENNYPARSE_CHAT_MODEL=your-model
export PENNYPARSE_CHAT_AUTHKEY=your-key
```

也可以使用 `OPENAI_API_KEY`，或把配置写入 `~/.pennyparse/pennyparse.settings.toml`、`./pennyparse.settings.toml`。

可选文档后端：

```shell
uv run --extra pdf pennyparse tool --list
uv run --extra docx pennyparse tool --list
```

## 准备用户工具

把外部工具写在 `${HOME}/pennyparse.toolbox_user.txt`，也可以用 `--from` 指定其他文件。内容用朴素的技术描述即可：工具名、用途范围、成本、参数、凭据、调用方式和注意事项。

生成工具运行时：

```shell
pennyparse init tools
pennyparse init tools --from ./pennyparse.toolbox_user.txt --force
```

生成结果位于 `${HOME}/.pennyparse/user_toolbox.py`。它是可执行 Python 代码，使用真实凭据前应先检查。

## 初始化文档目录

进入文档所在目录：

```shell
cd /path/to/documents
pennyparse init docs
```

命令会写入 `./.pennyparse_memory.txt`。这个文件是自然语言记忆，用来记录文件分组、解析难度和低成本预览结果。它不是数据库，也不要求手工维护结构。

完整初始化会同时生成工具和目录记忆：

```shell
pennyparse init --from /path/to/pennyparse.toolbox_user.txt --force
```

## 解析文档

解析当前目录：

```shell
pennyparse run
```

解析指定文件或目录：

```shell
pennyparse run invoice.pdf scans/ --out-dir pennyparse_results
```

每个成功解析的源文件会在输出目录下生成一个 UTF-8 文本文件，并保留相对路径：

```text
docs/report.pdf -> pennyparse_results/docs/report.pdf.txt
```

运行过程中，PennyParse 会向 `.pennyparse_memory.txt` 追加批次摘要和最终输出摘要。这些内容帮助后续解析选择工具。

## 查看与运行工具

```shell
pennyparse tool --list
pennyparse tool --list --scope=previewer
pennyparse tool pdf2txt --help
pennyparse tool pdf2txt --path report.pdf
```

不可用工具不会出现在普通列表中，原因会写入日志。常见原因是缺少可选依赖，或缺少工具声明的环境变量。

## 配置优先级

优先级从高到低：

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

[output]
dir = "pennyparse_results"
ext = "auto"

[reviewer]
max_length = 1000
```

## 常见问题

**每个命令都需要模型吗？**

不需要。工具查看和部分本地解析可以不用模型。`init tools` 和 `init docs` 需要模型，因为它们要让 agent 生成工具代码或理解目录结构。

**为什么 PDF 会被转成逐页图片？**

解析器会先尝试文本层提取。如果评审认为结果不可用，并且 PDF 图片后端可用，系统会把页面渲染成图片，再逐页解析并合并。

**为什么 `.pennyparse_memory.txt` 不是 JSON？**

它只是给解析器的软提示，不是事实来源。文件发现、工具校验和输出写入仍由确定性代码完成。

**错误信息在哪里看？**

命令结果在 `stdout`，简短错误在 `stderr`，详细日志在当前目录的 `pennyparse.log`。
