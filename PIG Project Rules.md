# PIG 项目规则 / PIG Project Rules

## 0. Project Identity

你正在开发的是：

**PIG — Project Ingestion Gateway**

PIG 不是普通文件管理器、普通解压软件，也不是一个为了展示 AI 而堆页面的后台系统。

PIG 的核心使命是：

> 先把审计、财务、采购、法务、尽调等项目中分散、嵌套、异构的原始文件，转化为可快速查看、打开、整理和持续编辑的项目工作区；再逐步沉淀为可追溯、可索引、机器可读的 Project Data Layer。

长期数据链路：

Raw Files
→ Original Snapshot
→ Structure Discovery
→ Editable Project Workspace
→ Catalog / Lineage
→ Structured Project Data
→ Search / Tool / Workflow / Agent / Automation

当前 V1 重点：

**Complex File Ingestion + Workspace Tree + Lazy Materialization + Open/Edit
+ Current/Previous Version Protection + Accidental Top-level Import Undo
+ Explicit File/Folder Export**

当前 V1 的首要价值是让用户快速处理复杂项目资料。完整 Lineage、Manifest
和审计呈现保留为长期能力，但不再是 V1 的主要用户流程或验收中心。

除非任务明确要求，否则不要提前实现 AI、RAG、OCR、知识图谱等后期能力。

---

# 一、基础规则

## 1. 先解决领域问题，再考虑页面

任何功能开发前，优先回答：

1. 这个功能解决什么真实业务问题？
2. 涉及哪些领域对象？
3. 对象之间是什么关系？
4. 数据如何进入系统？
5. 数据经过哪些状态变化？
6. 最终产生什么可复用的数据资产？
7. 哪些动作需要记录日志？
8. 哪些动作涉及权限或风险？

只有以上问题明确后，才设计 UI。

禁止：

- 先创建 Dashboard
- 先堆页面
- 先设计导航栏
- 为“看起来像完整系统”添加空模块

---

## 2. 每次只实现最小可运行闭环

优先：

输入
→ 处理
→ 持久化
→ 查询
→ 输出

而不是：

输入页面
+ Dashboard
+ 用户中心
+ 设置中心
+ AI 页面
+ 统计页面
+ 管理后台

但核心业务链路没有跑通。

每个阶段必须明确：

- 输入是什么
- 数据经过什么处理
- 数据保存在哪里
- 状态如何变化
- 输出是什么
- 用户如何验证结果
- 哪些场景仍未闭环

---

## 3. PIG 的核心资产是数据结构，不是 UI

优先建设：

- Project
- Original Snapshot
- Source Structure Node
- Workspace Item
- Working Artifact
- Container
- File
- Parent / Child
- Minimal Origin Reference
- Metadata
- Processing Status
- Processing Event
- Tool Result

其次才是：

- Tree View
- Detail Panel
- Search Page
- Dashboard

任何 UI 都应该是底层领域模型的表现，而不能成为事实来源。

---

## 4. 原始数据不可变

任何进入 PIG 的原始资料必须先复制为项目内的只读 Original Snapshot。
后续打开、编辑、移动和删除只作用于 Workspace Item 或 Working Artifact。

禁止：

- 修改原文件
- 覆盖原文件
- 原地解压
- 无记录地重命名原文件
- 无记录地移动原文件

必须区分：

- External Input
- Original Snapshot
- Workspace Copy
- Extracted Artifact
- Derived Data

必要时保存：

- 原始路径
- 工作路径
- SHA-256
- 文件大小
- 时间戳
- 来源关系

---

## 5. 来源结构和工作结构必须分离

用户可以自由整理 Workspace Tree，但不得覆盖 Source Structure。

例如：

邮件
→ ZIP
→ Excel

Workspace Tree 可以整理成：

Excel/
报价.xlsx

但必须保留最小来源绑定，使系统仍然知道：

报价.xlsx 来自哪个 ZIP、哪个邮件、哪个原始项目资料。

V1 至少保存 `Workspace Item -> Source Node -> Original Snapshot`。完整传递闭包、
图查询和审计级 Lineage 可以在后续版本完善。

---

## 6. 当前状态和历史事件必须分离

例如 Node 当前状态可以是：

SUCCESS

但必须能够追溯：

PENDING
→ PROCESSING
→ PASSWORD_REQUIRED
→ PROCESSING
→ SUCCESS

关键业务状态变化不能只覆盖字段。

必须考虑：

Current State
+
Event / Processing Log

---

## 7. 错误也是数据

文件处理失败不能简单：

catch Exception
→ print(error)
→ 跳过

必须产生明确状态，例如：

- SUCCESS
- UNSUPPORTED
- PASSWORD_REQUIRED
- CORRUPTED
- LIMIT_EXCEEDED
- FAILED
- SKIPPED

并记录：

- 哪个 Node
- 哪个 Handler
- 哪个阶段
- 错误类型
- 错误信息
- 时间
- 是否可重试

---

# 二、领域与数据建模规则

## 8. 不要用字符串代替领域模型

如果一个概念未来需要：

- 查询
- 权限
- 状态
- 关系
- 日志
- 生命周期

它应该成为明确的领域对象，而不是塞进：

- JSON
- 字符串
- metadata blob

例如：

Project 和 Node 应独立建模。

---

## 9. 多对多关系必须显式建模

如果未来出现：

File ↔ Tag

File ↔ Business Entity

File ↔ Dataset

Project ↔ User

不要使用：

tag_ids = "1,2,3"

或随意 JSON。

应该建立关系表。

JSON 主要用于：

- 不稳定 metadata
- parser 原始结果
- 外部系统 payload
- 扩展字段

不能代替核心关系模型。

---

## 10. Logical Structure 和 Physical Storage 必须分离

必须区分：

Physical Path

和：

Logical / Evidence Path

例如文件实际存储可能是：

working/<workspace-item-id>/<safe-display-name>.<trusted-suffix>

但 Source Path 是：

采购资料.zip
→ 邮件
→ Lenovo报价.msg
→ 附件.zip
→ 最终报价.xlsx

同时 Workspace Path 可以是：

```text
最终资料/已确认报价.xlsx
```

Physical Path、Source Path 和 Workspace Path 是三种不同事实，不得混用。

---

## 11. UI Tree 不等于数据库 Tree

UI 可以展示 Source Tree 或 Workspace Tree。

但底层必须保存真实关系：

Source Node / Source Relationship
Workspace Item / Workspace Parent
Origin Reference

UI 拖动不得直接成为数据库事实；必须通过 Application Action 校验并持久化。

---

# 三、架构规则

## 12. 严格分离 UI、Domain、Application、Infrastructure

推荐理解：

UI Layer
↓
Application / Use Case
↓
Domain
↓
Infrastructure

UI 不允许直接承担：

- 解压逻辑
- 邮件解析
- 数据库 SQL
- 权限判断
- Hash 计算
- 文件安全校验

---

## 13. Handler 是文件类型能力边界

Folder、ZIP、RAR、7z、MSG、EML 等 Container 应通过统一 Handler 抽象。

概念接口：

can_handle()
inspect()
list_children()
materialize(target_entry)

Processor 不应该知道：

“MSG 是怎么解析附件的”。

Processor 只负责：

识别 Source Node
→ 找 Handler
→ 检查结构
→ 注册 Children / Materialization Recipe
→ 更新状态
→ 继续处理

`inspect` 与 `materialize` 必须分离。导入时允许为了检查嵌套 Container 而受控地
读取或临时提取 Container 字节，但不得因此批量生成全部终端 Working File。

---

## 14. 递归业务使用可控队列，而不是无限函数递归

优先：

Queue / Work Queue / Job

理由：

- 可控制最大深度
- 可计算进度
- 可暂停
- 可重试
- 可恢复
- 可记录状态
- 可限制资源
- 未来可异步化

---

## 15. 安全边界属于核心业务，不是补丁

处理所有用户输入时默认：

**输入不可信。**

必须考虑：

- Path Traversal
- Zip Bomb
- Archive Bomb
- Symbolic Link
- 文件重名
- 超深嵌套
- 超大文件
- 超多文件
- 密码压缩包
- 恶意文件名
- 损坏文件

安全逻辑必须集中管理，不要散落在各 Handler。

---

## 16. 配置必须集中管理

例如：

MAX_DEPTH
MAX_FILES
MAX_EXPANDED_SIZE
MAX_SINGLE_FILE_SIZE
WORKSPACE_PATH

不要把限制数字散落在代码里。

---

## 17. 后端必须是业务事实来源

前端只能：

- 展示
- 发起 Action
- 接收结果
- 提供交互

前端不得自行决定：

- 用户是否有权限
- 文件是否允许处理
- Node 状态是否合法
- 高风险操作是否可以执行

即使当前是单机应用，也要保持这个边界意识。

---

# 四、日志与可观察性规则

## 18. 核心业务动作必须结构化记录

至少考虑：

Project Created
Import Started / Snapshot Created
Node Discovered
Container Opened
Working File Materialized
Workspace Item Added / Moved / Deleted / Restored
Working File Modified / Missing
Node Processing Started
Node Processing Finished
Processing Failed
File Opened

不要只写自然语言日志。

优先：

event_type
project_id
node_id
actor
timestamp
metadata

---

## 19. Processing Log 与 Debug Log 分离

Processing Log：

属于业务事实。

Debug Log：

属于开发诊断。

不要混在一起。

例如：

“ZIP 解包失败”

属于 Processing Event。

SQL connection timeout stacktrace：

属于 Debug Log。

---

# 五、权限与 Action 规则

## 20. 读操作和写操作必须区分

未来所有 Tool / API / Agent Action 应区分：

READ

和：

WRITE

例如：

search_files
get_node
get_lineage

属于低风险读取。

而：

delete_project
rename_source
replace_file
export_data
send_email

属于写或外部影响操作。

---

## 21. 高风险操作必须显式确认

未来 Agent 能执行真实业务 Action 时：

不可让 Agent 静默执行高风险写操作。

例如：

- 删除
- 覆盖
- 外发
- 修改来源数据
- 更改权限
- 提交业务系统
- 对外通信

必须经过显式确认或明确的 Automation Policy。

---

# 六、AI / Agent 规则

## 22. AI 不是核心数据库

LLM 输出不能成为唯一业务事实来源。

核心事实必须来自：

- Project Database
- File Metadata
- Processing Result
- Tool Result
- External System

AI 主要负责：

- 理解
- 推理
- 分类
- 总结
- 决策建议
- Tool orchestration

---

## 23. 能用确定性代码解决的问题，不优先使用 LLM

例如：

文件大小
Hash
文件扩展名
路径关系
日期比较
数据统计
明确规则校验

优先普通代码。

只有：

语义理解
模糊分类
自然语言推理
跨文件综合判断

才考虑 AI。

---

## 24. Agent 不等于聊天机器人

Agent 的价值应该体现在：

读取上下文
→ 规划
→ 调用 Tool
→ 获取结果
→ 判断下一步
→ 完成 Workflow

不要为了存在 Agent 而增加聊天界面。

没有真实 Tool 和 Workflow 的 Agent，只是 Chat UI。

---

## 25. Agent 必须通过 Tool 操作系统

Agent 不应：

直接写数据库
直接改文件
直接调用任意内部函数

Agent 应调用稳定 Tool Contract。

例如：

list_project_files
search_nodes
get_node_metadata
get_lineage
extract_container
query_project

这样才可以进行：

权限控制
日志
审计
重试
Automation
MCP 暴露

---

# 七、Tool 规则

## 26. Tool 是核心业务能力的稳定接口

设计 Tool 时优先考虑它未来是否可以被：

- Web UI
- Desktop UI
- Agent
- Workflow
- Automation
- MCP

共同调用。

Tool 应尽量与调用者无关。

---

## 27. Tool 必须有明确输入输出 Schema

禁止：

输入任意 dict
输出任意文本

优先结构化输入输出。

Tool 至少明确：

- name
- description
- input schema
- output schema
- permissions
- side effects
- error types
- idempotency

---

## 28. Tool 不等于底层函数

不是每个 Python function 都应该成为 Tool。

Tool 应代表：

**领域能力或业务动作。**

例如：

get_project_tree

是 Tool。

calculate_sha256

通常只是内部函数。

---

# 八、Prompt 规则

## 29. Prompt 不允许散落在业务代码中

未来如果引入 LLM：

所有 Prompt 必须集中管理。

需要明确：

- Prompt Name
- Version
- Purpose
- Input Schema
- Output Schema
- Model Requirement

禁止：

在几十个 `.py` 文件里直接写长字符串 Prompt。

---

## 30. 结构化输出优先

凡是结果会继续进入程序处理：

优先 JSON / Schema。

不要依赖：

“请输出以下格式……”

然后用正则解析自然语言。

---

## 31. Prompt 不能代替业务规则

例如：

“不要删除原始文件”

属于系统业务规则。

不能仅靠 Prompt 告诉 Agent。

必须由 Tool / Permission / Backend 强制执行。

---

# 九、Workflow / Automation 规则

## 32. Workflow 是可重复的生产流程

Workflow 表达：

Step A
→ Step B
→ Condition
→ Step C

而不是：

“给 Agent 一个 Prompt，看它自己怎么办”。

稳定流程优先 Workflow。

不确定环节再使用 Agent。

---

## 33. Automation 是事件驱动规则，不是定时聊天

Automation 应建立在明确 Event 上。

例如：

ProjectImported
NodeExtracted
ProcessingFailed
ManifestGenerated

事件必须由业务代码显式产生。

禁止让 AI 猜：

“是不是发生了某个事件”。

---

## 34. Automation 必须考虑幂等性

同一 Event 重复触发：

不能导致重复：

- 写数据
- 解压
- 发通知
- 外部 Action

需要考虑：

event_id
job_id
idempotency_key
processing status

---

# 十、Skill / Workflow / Tool / MCP 区分

## 35. 四个概念严格区分

### Tool

一个可调用的业务能力。

例：

get_project_tree()

---

### Workflow

多个 Tool / Step 组成的确定性流程。

例：

Import Project
→ Scan
→ Extract
→ Index
→ Generate Manifest

---

### Skill

指导 AI 如何组合领域知识、Prompt 和 Tool 完成某类任务的能力配方。

例：

“分析采购项目资料完整性”。

---

### MCP

将 Tool / Resource 暴露给外部 AI Client 的标准接入通道。

MCP 不是：

- Agent
- Workflow
- Skill
- 业务逻辑

不要混淆。

---

## 36. 不为了“支持 MCP”提前造 MCP

当内部 Tool Contract 稳定后，

再考虑将部分 Tool 通过 MCP 暴露。

不要为了技术名词而增加无业务价值的复杂度。

---

# 十一、AI Native 架构原则

## 37. 为 AI Ready 设计，但不要 AI First Everything

PIG 当前应该：

AI-ready

而不是：

AI-everywhere

正确方式：

先把：

数据
对象
关系
状态
日志
权限
Tool

做好。

AI 自然可以接入。

如果基础数据层混乱，再强的模型也无法稳定使用。

---

## 38. AI 能力必须建立在现有领域模型之上

未来：

“找服务器采购相关文件”

应基于：

Project
Node
Metadata
Content Index
Search Tool

而不是让 LLM 自己扫整个磁盘。

---

# 十二、反假大空规则

## 39. 禁止为了完整感创建无业务支撑模块

除非当前需求明确需要，否则不要主动添加：

- Dashboard
- 用户中心
- 消息中心
- 审批中心
- 报表中心
- AI 助手中心
- 工作台
- 系统管理
- 大屏
- 数据驾驶舱

首先证明：

核心 Domain Workflow 能跑。

---

## 40. 页面数量不是项目成熟度指标

如果：

一个页面

能够完整展示：

Drag / Import
→ Structure Discovery
→ Workspace Organize
→ Lazy Open
→ External Edit Refresh

那么它优于：

十个页面但没有完整数据流。

---

## 41. 不要预建大量空抽象

允许为明确的下一步留下接口。

禁止为了“未来可能需要”提前建设：

- 微服务
- Kafka
- Kubernetes
- Redis
- Graph DB
- Vector DB
- Event Bus
- MCP Server
- Agent Platform

除非真实需求已经出现。

---

# 十三、开发决策优先级

面对设计选择时，优先级如下：

1. 领域正确性
2. Original / Working Data 完整性
3. 用户文件处理闭环
4. 安全性
5. 复杂格式处理能力
6. 最小来源可恢复性
7. 状态与错误可解释性
8. Tool 可复用性
9. 可测试性
10. 扩展性
11. UI 体验
12. 视觉效果

不要为了 UI 简洁牺牲前面的原则。

---

# 十四、每次编码任务开始前必须回答

在实现非 trivial 功能之前，先确认：

### Domain
涉及哪些领域对象？

### Flow
数据从哪里来，到哪里去？

### State
有哪些状态变化？

### Lineage
来源关系是否需要保留？

### Log
什么事件应该被记录？

### Permission
是否存在读写或风险边界？

### Tool
它是否应该形成可复用 Tool？

### AI
真的需要模型吗？确定性程序是否已经足够？

### Automation
这是人工 Action、Workflow Step，还是 Event-driven Automation？

### UI
最小界面如何承载它，而不是反过来驱动架构？

---

# 十五、每次任务完成后必须说明

完成任何有意义的功能后，必须总结：

1. 本次修改了什么
2. 新增或修改了哪些领域对象
3. 数据完整流向是什么
4. 哪些状态会发生变化
5. 写入了哪些日志 / Event
6. 是否新增 Tool 或 Action
7. 权限 / 安全如何处理
8. 如何测试
9. 当前仍有哪些边界未闭环
10. 是否引入了未来技术债务

不得只回答：

“功能已完成”。

---

# 十六、当前 PIG V1 强制边界

当前阶段优先完成：

Project
→ Drag-and-drop Import
→ Immutable Original Snapshot
→ Container Structure Discovery
→ Editable Workspace Tree
→ Lazy Materialization
→ Controlled Open
→ External Edit Detection
→ Move / Add / Soft Delete / Restore
→ Confirmed Accidental Top-level Import Undo
→ SQLite Persistence
→ Search
→ Current / Previous Working Version Protection
→ Single-file / Multi-selection ZIP / Folder Export

现有 Source Lineage、Manifest 和 Processing Event 能力可以作为内部基础保留，
但当前不继续围绕它们扩大 UI 或验收范围。

旧领域模型创建的 Project 不在新 V1 的兼容范围内。不得为兼容旧 Project
增加双写、自动迁移或混合读写复杂度；不兼容时必须明确拒绝，而不是误读数据。

新 Project 必须使用 `<selected-parent>/<valid-project-name>/project.sqlite`，同时保留
UUID 作为内部身份。永久移除只允许作为已确认的顶层 Import Item 撤销：必须先预览
完整影响，不得影响同批 Sibling 或外部输入。任意节点 Hard Delete 仍不属于 V1。

当前明确不做：

- OCR
- RAG
- LLM Analysis
- AI Chat
- Knowledge Graph
- ERP Integration
- Cloud Sync
- Multi-user Collaboration
- Complex RBAC
- Enterprise Dashboard
- Transparent ZIP / RAR / 7z repack
- MSG / EML write-back
- Full document version history（V1 只允许当前版本加一个上一版本）

除非 Product Scope 被明确更新。

---

# Final Principle

始终记住：

**PIG 的价值不是简单罗列支持格式。**

而是：

> 将原本需要人工反复解压、保存附件和寻找文件的项目资料，快速转化为保留原始备份、结构清晰、可整理、可打开、可持续编辑的项目工作区，并为后续 Catalog、Lineage、Tool 和 AI 提供可靠基础。

如果一个新功能不能强化：

Domain
Process
Data
Workspace Usability
Original / Working Integrity
Minimal Origin
Tool
Workflow

中的至少一项，

就应该重新审视它是否值得现在开发。

---

# English Normative Translation

## 0. Project identity

PIG — Project Ingestion Gateway is not a general file manager, a simple archive
utility, or an AI-themed shell. Its immediate mission is to turn fragmented and
nested audit, finance, procurement, legal, and due-diligence inputs into a
project workspace that is quick to inspect, open, organize, and edit. It then
evolves that workspace into a traceable and machine-readable Project Data Layer.

The long-term chain is:

```text
Raw Files -> Original Snapshot -> Structure Discovery
-> Editable Project Workspace -> Catalog / Lineage
-> Structured Project Data -> Search / Tool / Workflow / Agent / Automation
```

V1 prioritizes complex-file ingestion, Workspace Tree, lazy materialization,
open/edit, one previous Working version, and explicit delivery export. Full
Lineage, Manifest, and audit presentation remain long-term
capabilities rather than V1 acceptance anchors. Do not implement AI, RAG, OCR,
or knowledge graphs unless the product scope explicitly changes.

## I. Foundation rules

### 1. Domain before screens

Before designing UI, define the real problem, domain objects and relationships,
data flow, state changes, reusable output, required events, and safety/permission
risks. Do not begin with dashboards, navigation, or empty modules.

### 2. Build one minimum closed loop at a time

Prefer input -> processing -> persistence -> query -> output. Every milestone
must state its input, processing, storage, state, output, verification method,
and remaining gaps.

### 3. Structured project data is the core asset

Prioritize Project, Original Snapshot, Source Structure Node, Workspace Item,
Working Artifact, Container, File, relationships, minimal origin, metadata,
state, events, and typed results. UI is a projection, never the source of truth.

### 4. Original data is immutable

Every accepted input must first become a read-only Project-owned Original
Snapshot. Open, edit, move, and delete affect only Workspace Items or Working
Artifacts. Never modify, overwrite, unpack into, silently rename, or silently
move an original. External Input, Original Snapshot, Workspace Copy, Extracted
Artifact, and Derived Data are distinct concepts.

### 5. Source Structure and Workspace Tree are separate

Users may organize the Workspace Tree without rewriting Source Structure. V1
must retain at least `Workspace Item -> Source Node -> Original Snapshot`.
Audit-grade transitive Lineage and graph queries may be completed later.

### 6. Current state and historical events are separate

Do not overwrite meaningful state history. Current state and append-only
Processing Events are distinct facts.

### 7. Errors are data

Never swallow file-processing failures. Persist explicit outcomes such as
`SUCCESS`, `UNSUPPORTED`, `PASSWORD_REQUIRED`, `CORRUPTED`, `LIMIT_EXCEEDED`,
`FAILED`, and `SKIPPED`, together with object, Handler, stage, code, safe message,
time, and retryability.

## II. Domain and data modeling

### 8. Do not replace domain concepts with strings

A concept requiring query, permission, state, relationship, log, or lifecycle
must be modeled explicitly rather than hidden in arbitrary JSON or text.

### 9. Model many-to-many relationships explicitly

Do not store relationship identifiers as delimited strings or arbitrary JSON.
JSON is for unstable metadata, raw parser payloads, external payloads, and
extension fields—not core relationships.

### 10. Separate logical and physical structures

Physical Path, immutable Source Path, and mutable Workspace Path are three
different facts and must never be used interchangeably. A stable Working path
uses a generated Workspace Item directory plus a sanitized display filename and
trusted detected suffix. Raw untrusted path syntax never selects a physical
destination.

### 11. A UI tree is not a database tree

Persist Source Node/Relationship, Workspace Item/Parent, and Origin Reference.
UI drag/drop must call a validated Application Action before becoming a fact.

## III. Architecture rules

### 12. Separate UI, Application, Domain, and Infrastructure

UI may present data and request actions. It must not implement extraction, email
parsing, SQL, permission rules, hashing, or filesystem safety.

### 13. Handler is the format capability boundary

Folder, ZIP, RAR, 7z, MSG, and EML use a common Handler contract. Processor
coordinates detect -> resolve -> inspect -> register -> update -> continue and
does not know format internals. `inspect/list_children` and
`materialize(target_entry)` are separate. Inspection may temporarily read an
inner Container but must not publish all terminal Working Files.

### 14. Use a controlled queue, not unbounded recursion

Queue-based traversal enables depth/file/size limits, progress, retry, recovery,
resource control, and later asynchronous execution.

### 15. Security is a core business boundary

Treat every input as untrusted. Central policy must cover traversal, archive
bombs, symlinks, duplicates, excessive depth/count/size, passwords, malicious
names, and corrupt content.

### 16. Configuration is centralized

Limits such as maximum depth, files, expanded bytes, single-file size, and
workspace path must not be scattered through code.

### 17. Backend rules are authoritative

The frontend cannot decide permission, format safety, legal states, or risky
filesystem actions, even in a single-user desktop application.

## IV. Logging and observability

### 18. Record core business actions structurally

At minimum consider Project creation, import/snapshot, discovery, Container
inspection, Working File materialization, Workspace add/move/delete/restore,
Working File modified/missing, processing lifecycle, failure, and file open.
Events include stable type, Project/object identity, actor, timestamp, and safe
metadata.

### 19. Separate Processing Log and Debug Log

Business outcomes belong to Processing Events. Stack traces, SQL timeouts, and
low-level diagnostics belong to Debug Logs.

## V. Permission and Action rules

### 20. Distinguish read and write

Every future Tool/API/Agent Action declares read/write risk. Search and get are
reads; delete, replace, export, send, or permission changes are writes/external
effects.

### 21. High-risk actions require explicit confirmation

Delete, overwrite, external send, source mutation, permission changes, system
submission, and communication cannot be performed silently by an Agent.

## VI. AI and Agent rules

### 22. AI is not the core database

Core facts come from Project Database, file metadata, processing, Tool Results,
or external systems. AI may understand, infer, classify, summarize, recommend,
or orchestrate Tools.

### 23. Prefer deterministic code for deterministic facts

Use ordinary code for size, hash, extension, paths, dates, statistics, and rule
checks. Use models only for genuine semantic or ambiguous reasoning.

### 24. Agent is not a chatbot

Agent value is context -> plan -> Tool -> result -> next step -> outcome. A chat
screen without real Tools and Workflow is not an Agent capability.

### 25. Agent acts only through Tools

An Agent must not write the database, edit files, or invoke arbitrary internal
functions directly. Stable Tool contracts enable permissions, events, retries,
Automation, and later MCP exposure.

## VII. Tool rules

### 26. A Tool is a stable business capability

Design Tools to be reusable by Desktop, Web, Agent, Workflow, Automation, and
MCP rather than tied to one caller.

### 27. Tools have explicit schemas

Each Tool defines name, purpose, input/output schema, permission, side effects,
error types, and idempotency. Arbitrary dictionaries and free-text contracts are
not sufficient.

### 28. A Tool is not every low-level function

Expose domain capabilities such as `get_project_tree`, not internal helpers such
as `calculate_sha256`.

## VIII. Prompt rules

### 29. Prompts are centrally managed

Future prompts require name, version, purpose, input/output schema, and model
requirement. Do not scatter prompt strings through business code.

### 30. Prefer structured model output

Machine-consumed results use a schema rather than prose parsed with regular
expressions.

### 31. Prompts cannot enforce business policy

Rules such as original immutability must be enforced by backend, permission, and
Tool boundaries—not merely stated in a prompt.

## IX. Workflow and Automation rules

### 32. Workflow is a repeatable production process

Stable steps and conditions belong in Workflow; only uncertain parts justify an
Agent decision.

### 33. Automation is event-driven behavior

Automation consumes explicit business Events, not an AI guess that something
happened.

### 34. Automation is idempotent

Repeated Event delivery must not duplicate writes, extraction, notifications,
or external actions. Use event/job/idempotency identity and processing state.

## X. Tool, Workflow, Skill, and MCP are distinct

### 35. Keep the four concepts separate

A Tool is one business capability; Workflow combines deterministic steps; Skill
is an AI capability recipe; MCP is a protocol that exposes Tools/Resources to an
external AI client.

### 36. Do not build MCP prematurely

Only expose mature internal Tool contracts through MCP. Do not add protocol
infrastructure without current business value.

## XI. AI-native architecture

### 37. Be AI-ready, not AI-everywhere

Build data, objects, relationships, state, events, permissions, and Tools first.

### 38. AI builds on the domain model

Future semantic tasks consume Project, Node, Metadata, Content Index, and Search
Tools; models must not crawl arbitrary disks directly.

## XII. Anti-theater rules

### 39. Do not add unsupported modules for appearance

Do not create dashboards, user centers, notification centers, approval centers,
AI home pages, admin panels, or data walls without real current requirements.

### 40. Page count is not maturity

One screen that completes Drag/Import -> Structure Discovery -> Workspace
Organization -> Lazy Open -> External Edit Refresh is better than ten empty
pages.

### 41. Do not prebuild speculative infrastructure

Do not introduce microservices, Kafka, Kubernetes, Redis, Graph DB, Vector DB,
Event Bus, MCP Server, or Agent Platform without a concrete current need.

## XIII. Decision priority

Prioritize: domain correctness; Original/Working integrity; the user file loop;
security; complex-format capability; minimal-origin recoverability; explainable
state/errors; Tool reuse; testability; extensibility; UX; and visuals—in that
order.

## XIV. Required pre-implementation impact check

Before a non-trivial implementation, state Domain, Flow, State, Lineage/minimal
origin, Log, Permission, Tool, AI, Automation, and minimal UI impact.

## XV. Required completion report

After meaningful work, report: what changed; affected domain objects; full data
flow; state changes; Events; Tool/Action impact; permission/safety; tests;
remaining gaps; and future technical debt.

## XVI. Current V1 hard boundary

Prioritize Project -> Drag-and-drop Import -> Immutable Original Snapshot ->
Container Structure Discovery -> Editable Workspace Tree -> Lazy Materialization
-> Controlled Open -> External Edit Detection -> Move/Add/Soft Delete/Restore ->
Confirmed Accidental Top-level Import Undo -> SQLite Persistence -> Search ->
Current/Previous Working Version Protection -> Single-file/Multi-selection ZIP/
Folder Export.

Existing Lineage, Manifest, and Events may remain internal, but do not expand
their UI or acceptance scope. Old-model Projects are incompatible; do not add
dual-write, automatic migration, or mixed read/write support. Reject an
unsupported model explicitly.

New Projects use `<selected-parent>/<valid-project-name>/project.sqlite` while
retaining UUID as internal identity. Permanent removal is limited to confirmed
undo of a top-level Import Item after complete impact preview; it never changes
same-session siblings or the external input. Arbitrary-node hard delete remains
outside V1.

V1 excludes OCR, RAG, LLM analysis, AI chat, Knowledge Graph, ERP integration,
cloud sync, multi-user collaboration, complex RBAC, enterprise dashboards,
transparent archive repack, MSG/EML write-back, and full document history beyond
the current version plus one previous Working version.

## Final principle

PIG is valuable not because it lists many formats, but because it turns project
material that otherwise requires repeated unpacking and attachment saving into
a protected, structured, organizable, openable, and continuously editable
workspace—while preserving a foundation for later Catalog, Lineage, Tools, and
AI. A feature should strengthen Domain, Process, Data, Workspace Usability,
Original/Working Integrity, Minimal Origin, Tool, or Workflow.
