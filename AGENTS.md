---
mod: readonly
warn: 此文件对于 AI Agent 只读, 禁止 AI Agent 修改此文件
---

# 系统设计

## 综述

本系统综合多种文档处理､ 图像处理工具, 借助LLM智能调度, 使得文件解析难度 (印刷品扫描件, 手写稿, 图表, 模糊影印件等) 与解析工具成本 (低成本 OCR, VLM 大模型, 云端 API 等) 智能匹配, 达到优化资源配置, 成本最优且质量优秀的解析效果

## 架构

AI Agent: 负责实现 Agentic 迭代循环
CLI: 各项功能的主入口 `pennyparse <sub_command> <more_args>`, 其中部分工具可递归调用
Skill:  PennyParse 可封装为 Skill 被其它 Agent 调用 (计划中, 尚未实现) 

## User Flow

```shell
pennyparse init tools [args]
cd /path/to/my_docs
pennyparse init docs [args]
pennyparse run [args]
```

## CLI

- 默认 POSIX 系统环境, 但仍需兼容 Windows 环境
- cli.py 仅负责人机交互逻辑, 具体功能由 cmd/*.py 实现

## 入口

按 config.py 导入系统配置和用户配置

### config

优先次序: 
- 环境变量
- `${CWD}/pennyparse.settings.toml`
- `${HOME}/.pennyparse/pennyparse.settings.toml`
- package default

环境变量 / argv 两者仅用其一, 即环境变量不可作为 argv 传递, 反之亦然; 原则上, 环境变量用于长期有效的内容, argv 用于需要实时变化的内容
代码不含配置的默认项, 只含配置逻辑, 所有默认项均存放于 系统配置文件

config.py 可以通过  python-dotenv 从 .env 文件中读取环境变量

`pennyparse.settings.default.toml`
前身为 pennyparse.settings.default.ini, 重构时无需考虑兼容 ini

`pennyparse.prompt.toml`
- 导入为 pp_agentic_prompt, 按应用场景分组
- 短且与函数强绑定的 prompt 可内联；跨 agent、需要调参或复用的 prompt 放入 `pennyparse.prompt.toml`

如果用户未提供 PENNYPARSE_CHAT_*, 则需要提醒用户: PENNYPARSE_CHAT_*需要自行配置, 否则 PennyParse 可能无法正常工作 

### cmd/init

- 分别运行 `init_tools`, `init_docs` 两个子命令

### cmd/init_tools

`pennyparse init tools --from [Usertool_txt_path][default=$HOME/pennyparse.toolbox_user.txt]`

- 检查 `${HOME}/.pennyparse/user_toolbox.py` 是否存在
  + 如果已有则询问覆盖, `-f` 强制覆盖, 默认否 (y/N), 超时(PENNYPARSE_CLI_TIMEOUT)自动选默认, 即终止流程
- 调用 agent/init_tools
- 返回成功示例 (内部表示为 python dict, 如需输出则json.dumps): `{"ok":True, "usertools_valid":["tool1", "tool2"], "usertools_failed":["tool3"], "agent_turns": 3, "result_file":"/home/ubuntu/.pennyparse/user_toolbox.py"}`
- 警告用户需要自行审计 user_toolbox.py 的安全风险

### cmd/init_docs

`pennyparse init docs`

- 检查 `${HOME}/.pennyparse/user_toolbox.py` 是否存在
  + 如果不存在, 则提醒用户先运行 init tools, 然后终止流程
- 检查 `./.pennyparse_memory.txt` 是否存在
  + 如果已有则询问覆盖, `-f` 强制覆盖, 默认否 (y/N), 超时(PENNYPARSE_CLI_TIMEOUT)自动选默认, 即终止流程
- 检查 pp_config["aigc.api.chatcomp"] 是否已配置好, 否则终止流程
- Walk 遍历所有子目录, 子文件, 获取待解析的文件名及文件体积
- 通过 `pennyparse tool --list --scope=previewer` 找到可用的工具, 提取对应文件的元数据, 合并到文件列表元数据中
  + 如果 pdf 的 planner 阶段工具可用, 则可根据页码数和文件体积推测 pdf 是否为影印版
- 让 LLM 根据给出全部的文件路径和元数据, 通过 tool_calls 协议给出 glob 格式的匹配模式来分组, 分组依据为 LLM 从文件名和元数据推测出的文档解析难度
  + 约束 glob: 必须相对路径、不得跨目录、不得匹配隐藏目录、不得冲突
- LLM 拿到 glob 匹配结果, 可以适当调整 glob 匹配模式或确定已有 glob 匹配模式无误, 然后将未匹配的作为 misc 组
- 按照 pp_config["init.sampling"] 中的数字, 对每组进行抽样解析
- 抽样规则
  + 对于 pdf 文件, 每个 pdf 按页数抽样, 提取该页(文字层/该页截图)到临时文件夹, 直到 pp_config["init.sampling"]["pdf_page_total_max"]
  + 对于图像文件, 按文件数抽样
  + 对于其他文件, 暂且跳过 (留出日后增加支持更多文件类型的余地) 
- 抽检过程 按 pp_config["aigc.api.chatcomp"]["model_hasVision"] 分为两种
  + 不具备视觉的, 按普通 OCR (或者其余 `tool if tool.cost in ["very low","low"]`) 抽取, pdf 先尝试抽取文字层, 如果文字层不存在再尝试 OCR, 然后文字发往 LLM 令其判断文字结果是否通顺, 是否含有图表等 OCR 难以应付的内容
  + 具备视觉的, 先 `pennyparse tool img_thumb` 生成缩略图, 再让 VLM 看缩略图判断清晰程度､ 印刷/手写､ 扫描清晰度､ 纯文字段落/含有图表､ 复杂排版等情况
- 写入 `./.pennyparse_memory.txt`
  + 用自然语言分别总结每组文件的文件名特征, 对文档解析难度的估算, 以及建议以哪个 cost 基线作为开始 (每组一句话) 
  + 根据所有分组抽检情况, 用自然语言总结当前文件夹文档的总体难度估算, 以及建议总体上从哪个 cost 作为基线作为开始

### cmd/tool

tool 实例属性
- enabled:bool, 默认True, 若在 `cmd/init_docs` 阶段如果发现工具不可用, 则在 `disable_reason` 填入原因
- disable_reason:str, 默认空字符串 
- cost:str, 分为 "very low","low","medium","high","very high" 模糊对应算力需求, 小到树莓派部署即可毫秒级响应, 大到数据中心GPU集群/云端付费API
- scope:str, 暂定为 "previewer", "parser", "reviewer"
- desc:str, 一句话简述此工具的目的､ 适用范围
- secrets:List[str], 调用本工具需要引用的环境变量, 例如, DEEPSEEK_API_KEY, etc.
- flags:Dict[str, str], 调用本工具需要传入的参数, 例如, --path /path/to/example.jpg 即 {"path": "/path/to/example.jpg", ...} 为多数 scope==parser 工具所须

tool 分为 cmd/tool 的内建工具, 以及 cmd/init_tools 构建的用户工具, 用户工具在每次运行 cmd/tool 时, 从 `$HOME/.pennyparse/user_toolbox.py` 动态导入; 
内建工具又根据是否具备 pymupdf, pypandoc 等依赖, 设置工具的可用状态
如果 `$HOME/.pennyparse/user_toolbox.py` 不存在/导入错误, 则仅显示可用的内建工具

命令行列出所有可用工具
`pennyparse tool --list` 
输出为
`'\n\n'.join([f"{tool.__name__}\tscope: {tool.scope} cost: {tool.cost}\t{tool.desc}\n\t" + '\n\t'.join([f'--{k} {v}' for k, v in tool.flags.items()]) for tool in all_tools if tool.enabled])`

可指定 scope `pennyparse tool --list --scope=parser` 
输出为
`'\n\n'.join([f"{tool.__name__}\tscope: {tool.scope} cost: {tool.cost}\t{tool.desc}\n\t" + '\n\t'.join([f'--{k} {v}' for k, v in tool.flags.items()]) for tool in all_tools if tool.enabled and tool.scope=='parser'])`

### cmd/run

`pennyparse run [--out-dir pennyparse_results]`

- 检查前期初始化工作是否齐备, 是否有对应文件生成
- 读取每个文档文件的路径, 依次提交给 agent/parser
- 每解析完 pp_config["parser_summary_batch"] 份文件, 就让 LLM 20字以内概述这批文件的文件名和解析所用工具, 追加到 .pennyparse_memory.txt, 为后续 agent/parser 选取工具当作参考
- 统计输出文件夹中的文件, 并将统计结果汇总为汇报形式, 追加到 .pennyparse_memory.txt

## Agent

> 本系统中并非所有 LLM 请求都属于 Agent 请求, 常规 LLM 请求更适合放在各自 procedure 中实现

prompt 要求: 能够一次性引导当前 LLM 的返回结果, 使其实现每个 Agent 中定义的 Agentic 的循环步骤

Agentic 循环模式: 
- tool_calls
- pseudo_XML

- tool_calls 以 tool_calls 字段为基础的, 标准化工具调用/ReACT循环流程
- pseudo_XML 兼容性强, 忽略 tool/tool_calls/function_calling 字段, 而是模拟自然对话形式, 在 prompt 中指定 / 从 prompt 中解析 Anthropic 风味 pseudo-XML 的工具调用流程  (见 utils.py extract_pseudo_xml), 适用于单一工具/代码生成/代码迭代修改的情况｡ 

如果是在 pseudo_XML 模式下, 则在 prompt 中引导约定
- 对于书写代码的场景, 使用 tag 包裹 markdown code fence 形式, 即 <full_file_code>\n```language\n(.*?)\n```</full_file_code> 提供需要创建/全量替换的代码文件全文
- 以 `please run the tool and paste the results below:` 作为每次 Assistant message 的结尾
- 如果 Assistant 验收了 result, 则让 Assistant 在 message 中回复 `<status>mission_complete</status>` 来表示循环结束

agent/*.py 可以根据各自源文件顶部常量 _AGENT_IMPL_MODE 来切换 tool_calls / pseudo_XML 两种模式, 因此需要合理设计代码组织形式, prompt 拼接形式, 以复用共有逻辑

Agent 语境下, 交互形式应偏向自然语言, 而非形式逻辑语言

### $CWD/.pennyparse_memory.txt

- 文件权限控制: 常规运行时, 文件打开模式仅限 'r', 'a'; 唯一例外: 初始化时, 用户要求覆盖此文件

### agent/init_tools

prompt 需要注入: `$usertool_txt_path`, `cmd/tool.py`

Agentic 循环模式: pseudo_XML

- 调用 LLM 写脚本: 让 LLM 写出 `$HOME/.pennyparse/user_toolbox.py`, 要求包含符合 `cmd/tool` 范式, 且可被 `cmd/tool` 动态导入
- 校验: 生成 user_toolbox.py 后拿 demo_assets 尝试运行, 根据preliminary解析结果让 LLM 分析要不要调整/如何调整 user_toolbox.py 相关代码 (若网络不通则跳过校验且默认可用) 
- 自修复循环: 根据解析结果, 迭代更新 user_toolbox.py 直到 user_toolbox.py 可被动态导入和校验, 或达到 max_iter

在此过程中, 需要配合 `$HOME/.pennyparse/user_toolbox.py` 文件的写入与运行 subprocess.run(['sys.executable',...],...)

> 校验自修复循环举例: 例一: 某OCR解析结果, 发现正文中混入形如 <bbox>[[44, 395, 277, 471]]</bbox> 等非文档本身的内容, 则增加去除它们的后处理步骤; 例二: 某 VLM 结果中混入了"好的, 这个图片中包含了一份资料, 资料上写的内容是: blah blah", 则需要调整 VLM 的 prompt, 以及增加后处理步骤, 比如下次迭代中让 VLM prompt 要求解析内容用 <doc_fulltext> </doc_fulltext> 包裹, 然后增加 re findall "<doc_fulltext>(.*?)</doc_fulltext>" 的后处理;
> 以上仅供举例, 实现上应当由 Agent 自己决定如何改 metadata、调用方式、prompt、解析、清洗或禁用工具

> 如果提供的是像 Qwen-VL, Gemini, 这类多模态 VLM 用作 parser, 则需要将事先定义在 pennyparse.prompt.toml 中的 VLM_prompt 导入到 user_toolbox.py 的对应过程中｡ VLM_prompt 应当包括任务指令和格式引导, 格式引导: 默认 markdown, 但在带有表格/复杂排版情况下时, 则对应部分用 HTML 表示

### agent/parser

Agentic 循环模式: tool_calls

- 用于处理待解析的单个文档
- 每个文档具有独立的上下文

- 读取 `pennyparse tool --list --scope=parser` 以了解有哪些解析工具可供使用
- 读取 .pennyparse_memory.txt 并根据其中的预检结果, 选取适合本文件的解析工具
- 调用解析工具进行解析
- 调用 agent/reviewer 对解析结果进行验收
- 验收不过的情况下, 换一个解析工具进行解析
- 不以规则强制, 而是由prompt引导, 让 LLM 自行判断换到哪个工具
  - 对于图片文件, 建议agent在相同成本的档位尝试1-2次 
  - 对于 PDF, 建议 agent 先尝试直接按 PDF 解析, 如果验收不过, 再按页拆成每页一幅图 (调用 pdf 拆成图的 tool), 按页来解析 (此时递归以图片文件形式调用 agent) 
- 验收通过, 则往 ./<pennyparse_results>/ 输出解析结果, 其中输出文件名后缀由 LLM 根据 pp_config["output"]["ext"] 自行决定

### agent/reviewer

Agentic 循环模式: tool_calls

- 只有由 agent/parser 调用
- agent/reviewer 具有独立的上下文和提示词, 免受 agent/parser 分析过程的干扰

- LLM 自行判断给出的文字是否通顺, 排版是否完整 (此 Agent 的 prompt 应赋予严谨细致审慎的性格) 
- context 管理: 超过  pp_config["output"]["max_length"] 的, 则截断到 pp_config["output"]["max_length"] 位置再注入 prompt
- 自修复循环: 生成 `re.sub()` 形式的 myregexpatch 来修复文本, 可以 `re.sub()` 多次, 形成修复链; apply myregexpatch 得到修改结果后再检查反馈给 LLM 继续修复
  + 注意 `re.sub()` 形式的替换容易出错, 因此应该在 LLM 反馈的修改结果中, 包含修复前后的文本长度
  + 每次生成/Apply的 myregexpatch 都是针对本 Agent 接收到的初始文本, 而非上一次的修改结果
  + 第二次及以上生成 myregexpatch 时, 传入的信息不要保留上次修改文本内容, 而是包含Agent的上次修改建议, 以及上次让 Agent 审计修改结果时, 对这轮修改结果的总结
- 三类结果: 
  + 通过: Agent 认为当前给到的文字, 通顺完整, 排版无误, 则返回类似 "The reviewer found current given result is good." 这样的消息
  + 小改: 返回结构化 patch，由程序应用并重新校验。
  + 大改: 验收不通过, 重新解析

# 参考资料

## Data Extraction

从回答结果中提取代码: extract_md_codeblock
提取结构化数据: extract_md_codeblock 后 json.loads

## Agentic Loop

ReAct loop (minimal pseudo code):
```
for _ in range(int(aigc.agent.max_iter)):
    resp = llm.call(messages) 
    if resp.has_tool_calls():
    results = execute(resp.tool_calls)
        messages.append(results)
    else:
        return resp.text
```

分层错误处理
- LLM 调用层：自动重试 + 指数退避
- 工具执行层：捕获异常并将错误信息作为工具结果返回给 LLM
- 循环层：max_iter 防止无限循环

## 模板字符串注入

模版字面量, 变量统一为 `${__snake_case__}` 形式, 在 .toml 中用三括号包裹, 然后在 .py 中用 string.Template().safe_substitute() 来注入需要拼接的信息

被注入的内容, 若为文件, 则 open(fpath,"r", encoding="utf8").read() 注入全文

## prompt 编写

语言风格: 
- 尚简, 陈言务去
- in-context learning prior to list of rules
- RFC 7322 为表  (刨除格式排版部分), 善用 RFC 2119 keywords
- Steven Pinker classic style 为精神

## docstring 编写

文件级 docstring: 
- 非必须, 如有必要, 仅描述此文件与习惯上同名文件的差异之处

函数级 docstring: 
- 如果函数签名足以表明含义, 则省略
- 实现功能非常复杂, 或有 edge case 需要注意的, 才写注意事项

语言风格: 
- 惜字如金, 电报式拼写

## logger

- console handler 指向 stderr
- file handler 指向 `${CWD}/pennyparse.log`
- log format 带模块名或文件名
- 若从环境变量中注入了 secrets, 须脱敏

## README.md

- 国际化/在地化: 单文件双语版本, 英文在上, 简体中文在下, 水平线分割, 总标题下方链接跳转语言版本 (en, zh-hans) 
- 遣词造句体现良好语感, 注重亲和力, 吸引力: 
  + Steven Pinker classic style 如事实般呈现观点, 平实素朴
  + 面向大学生知识水平的大众读者, 拉近读者距离, 引起情绪共鸣
  + 避免出现 GPT 特征的行文风格: em-dash; triplicates; not X but Y; in today's world; Dramatic Fragment; where [scary change], [virtue] becomes [advantage]; Here's the truth; If you're not doing [X], you're ...; if you want; 万能比喻, 模板化衔接词, 重磅形容词; etc.
  + 避免出现特定语料中的黑话､ 怪话､ 口癖: 落盘, 接住, 狠狠, 说穿, 开悟, 兜底, 口径, 契约, 硬撑, 硬写, 不稳, 砍一刀, 补一刀, 说人话就是, 等等
  + 谨慎使用 加粗号､ Emoji 等媚俗装饰
- 排版: 灵活运用 GFM 可供的格式, 使文档清晰易读
- 目的: 使陌生读者对项目价值､ 优势一目了然, 且能快速上手; 让多数浏览者更容易在 GitHub 上进来扫两眼后点上星标

---

# 本地测试(仅供dev)

- 测试代码放在 tests/ 下, 测试实验时使用 _test_playground 目录当作 workspace; 
- 测试代码以 python-dotenv 从 .env 读环境变量, 并允许联网
- 沙箱环境下无访问 $HOME 目录权限, 可用此 workspace 临时充当 $HOME 目录; 
- 如需 fixture, 运行时从 demo_assets 动态发现可用 pdf/img 文件

# 对于当前代码库

- 当前全项目处于 beta 阶段, 没有实际用户, 如需重构, 则不考虑兼容, 允许 breaking change
