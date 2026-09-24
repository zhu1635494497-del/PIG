# ADR-010：V1 项目文件工作台重置 / V1 Project File Workbench Reset

- 状态：已接受；W1–W7.2 已完成 / Status: Accepted; W1-W7.2 complete
- 决策日期：2026-09-21 / Decision date: 2026-09-21
- 范围：PIG V1 产品与领域重置 / Scope: PIG V1 product and domain reset
- 已批准决策：D17-B 至 D23-B / Approved decisions: D17-B through D23-B
- 旧项目边界：现有 Project 不在兼容范围 / Legacy boundary: existing Projects are outside the compatibility scope

## 中文规范正文

### 背景

已实现的 V1 主要围绕外部只读引用、结构化目录、持久化 Lineage、Processing
Event、Manifest、Search 和受控打开。产品复盘确认，第一个真正有用的版本必须
优先减少用户在复杂项目资料中反复解压、定位、整理和打开文件的时间。

PIG 仍然是项目级系统，而不是任意磁盘文件管理器。它必须保护导入原件，处理
Folder、Archive、Email 的嵌套结构，并提供受控的可编辑工作区。完整审计级
Lineage 保留为长期能力，但不再是 V1 用户主流程和验收中心。

### D17-B：V1 是复杂项目文件工作台

V1 主流程为：

```text
拖入文件和文件夹
  -> 创建不可变 Original Snapshot
  -> 发现嵌套 Source Structure
  -> 初始化可编辑 Workspace Tree
  -> 仅在需要时物化文件
  -> 打开并编辑 Working File
  -> 刷新当前状态
  -> 移动、增加、软删除或恢复 Workspace Item
```

现有 Catalog、Lineage、Manifest 和 Event 能力可以作为内部基础继续存在。不应
仅为了简化 UI 而删除它们，但新的 V1 工作也不再以扩大这些能力的展示为目标。

### D18-B：导入必须创建不可变 Original Snapshot

每个接受的外部文件或文件夹，在成为结构发现或物化的来源前，都必须复制到
Project 边界内。外部输入在授权读取后不得被修改。Snapshot 使用生成的标识存储，
保存实际 size 和 SHA-256；不可信名称不得决定物理路径。

本决策对新的 Workbench Project 取代 ADR-001 D1。V1 Workbench 不提供仅外部
引用的导入模式。

### D19-B：不可变 Source Structure 与可变 Workspace Tree

系统拥有两套独立结构：

- `Source Structure`：从 Original Snapshot 发现的不可变 Node 和 Relationship；
- `Workspace Tree`：表达用户当前整理结果的可变 Workspace Item。

Workspace Item 可以通过最小来源绑定引用一个 Source Node。移动或删除 Workspace
Item 不得重写 Source Relationship。用户创建的逻辑文件夹可以没有 Source Node；
从 PIG 外部增加的字节文件必须先形成 Snapshot 和 Source Node，再创建 Workspace
Item。

UI 以 Workspace Tree 为主要界面。Application 仍保留 Source Structure，用于重新
物化、恢复、诊断和未来 Lineage 能力。

### D20-B：主动检查结构，延迟物化终端文件

导入时在资源限制内发现完整允许的 Container 结构，但不把所有终端成员发布为
Working File。

为了发现嵌套 Container，Handler 可以在受控检查缓存中流式读取或临时物化其
字节。内层 ZIP、MSG、EML、7z 或 RAR 不读取字节就无法检查，这一点不能被“延迟
解压”掩盖。只有 Open 等明确需求出现时，终端成员才成为持久 Working File。

Handler 能力在概念上拆分为：

```text
inspect / list_children
materialize(target_entry)
```

### D21-B：外部程序编辑稳定 Working File

首次允许打开虚拟 Workspace Item 时，在 Project 内创建带可信扩展名的稳定
Working Artifact，并由操作系统直接打开；后续打开复用同一文件。

PIG 在物化时保存 baseline fingerprint，并通过确定性刷新识别外部原地修改。
文件系统通知和 UI 焦点变化只是刷新提示，size/SHA-256 校验才是权威依据。保存到
Project 外部的 Save As 文件不自动跟踪。

### D22-B：Workspace Overlay，V1 不回写 Container

修改 Archive 或 Email 成员时，只修改它的 Working Artifact。V1 不静默重建或
覆盖 ZIP、RAR、7z、MSG 或 EML。移动 Workspace Item 也不改变来源 Container。

向 Container “内部”移动或增加项目意味着重新打包，因此不是 V1 Action。未来
若提供显式导出或重打包，必须另行定义 Contract 和决策。普通文件夹形式的
Workspace 导出可在核心闭环完成后独立规划。

### D23-B：删除只作用于 Workspace 且可恢复

用户明确确认后，Delete 将 Workspace Item 生命周期改为 `DELETED`。它不删除
Original Snapshot 或 Source Node。Working Artifact 字节必须保持可恢复。永久清理
不是 V1 常规操作；ADR-019 只为撤销一个误导入的顶层 Import Item 定义了收紧例外，
任意节点清理仍需要未来保留策略。

### 旧 Project 边界

产品负责人明确移除了旧 Project 兼容需求，这不是 D24 选项：

- 现有开发和验收 Project 可以废弃；
- 新应用可以用明确的“不支持模型版本”错误拒绝旧数据库；
- 不建设原地转换、关系修复、旧版只读模式或新旧混合支持；
- Schema 仍需受控演进，但使用新 baseline 还是 forward Alembic revision，必须在
  开始 Schema 编码前决定；无需迁移旧数据。

### 最小来源 Contract

V1 不要求把审计级传递闭包作为产品能力，但必须保留支持延迟物化和恢复所需的
来源关系：

```text
Workspace Item
  -> 可选 Source Node
  -> Source Relationship chain
  -> 不可变 Original Snapshot
```

Workspace Item 移动时不得修改该绑定。

### 对早期 ADR 的影响

- ADR-001 D1 被取代；D2-D8 在未被本 ADR 冲突修改时继续有效。
- ADR-002 只作为不可变 Extracted Artifact 的历史记录；新 Original/Working 存储
  由 Workbench 模型定义。
- ADR-003 至 ADR-005 的 Handler/Backend 约束仍可复用，但 Handler 需要演进为
  inspect/materialize 分离。
- ADR-006 的 Manifest 和结构 Search 不再是 V1 验收中心。
- ADR-007 保留 PySide6 和后端受控 OS handoff，但 Working Artifact 是可编辑的。
- ADR-008 的 Recovery 和 Packaging 需要针对可写 Workspace 重新验证。
- ADR-009 D13/D15 对 Source Structure 和 Project 标识仍有用；D16 的临时
  open-handoff 被稳定 Working Artifact 取代。

### 实施授权边界

本 ADR 最初只授权规划文档。产品负责人随后授权并完成 W1–W7.2；D25-B 记录在
ADR-011，D26-A 至 D29-A 记录在 ADR-012，D30-B 至 D36-A 记录在 ADR-013，
D37-A 至 D40-A 记录在 ADR-014，D41-A 至 D46-A 记录在 ADR-015，D47-A 至 D52-A
记录在 ADR-016，D53-A 至 D60-A 记录在 ADR-017，D61-A 至 D64-A 记录在
ADR-018，D65-A 至 D68-A 记录在 ADR-019。当前授权不延伸到 W8 或更后阶段。

V1 仍不实现透明 Container 重打包、MSG/EML 回写、任意节点永久清理、完整文档版本历史、
内容索引、OCR、RAG、AI、Agent、Workflow Engine、Automation Engine、MCP、云同步、
多人协作、Graph DB、Vector DB 或分布式 Worker。

## English normative text

## Context

The implemented V1 concentrated on immutable external references, structural
cataloging, persisted Lineage, Processing Events, Manifest export, Search, and
controlled opening. Real product review established that the first useful
release must instead reduce the time users spend unpacking, locating, arranging,
and opening complex project files.

PIG remains a project-scoped system rather than a general disk file manager. It
must protect an imported original, handle nested Folder/archive/email structures,
and provide a controlled editable workspace. Full audit-grade Lineage remains a
long-term capability but is not the V1 user journey or acceptance center.

## Decisions

### D17-B - V1 is a complex project file workbench

The primary V1 workflow is:

```text
Drop files and folders
  -> create an immutable Original Snapshot
  -> discover nested Source Structure
  -> initialize an editable Workspace Tree
  -> materialize a file only when needed
  -> open and edit the Working File
  -> refresh its current state
  -> move, add, soft-delete, or restore Workspace Items
```

Existing Catalog, Lineage, Manifest, and Event capabilities may remain as
internal infrastructure. They are not removed merely to simplify the UI, but
new V1 work is not driven by expanding their presentation.

### D18-B - import creates an immutable Original Snapshot

Every accepted external file or folder is copied into the Project boundary
before it becomes the backing source for discovery or materialization. External
input remains untouched after the authorized read. The snapshot is stored with
generated identities and verified size/SHA-256 facts; untrusted names do not
select physical storage paths.

This supersedes ADR-001 D1 for new Workbench Projects. External-reference-only
ingestion is not a V1 Workbench mode.

### D19-B - immutable Source Structure and mutable Workspace Tree

The system owns two separate structures:

- `Source Structure`: immutable Nodes and Relationships discovered from the
  Original Snapshot;
- `Workspace Tree`: mutable Workspace Items representing the user's current
  organization.

A Workspace Item may reference one Source Node through a minimal origin binding.
Moving or deleting a Workspace Item never rewrites Source Relationships. A
user-created logical folder may have no Source Node; a byte-bearing file added
from outside PIG is snapshotted and receives a Source Node before it becomes a
Workspace Item.

The UI shows the Workspace Tree as the primary surface. Source Structure remains
available to the Application for rematerialization, restore, troubleshooting,
and later Lineage features.

### D20-B - eager structure inspection and lazy terminal materialization

Import discovers the complete permitted Container structure within configured
resource limits but does not publish every terminal member as a Working File.

To discover a nested Container, the Handler may stream or temporarily materialize
that Container's bytes in a controlled inspection cache. This is unavoidable:
an inner ZIP, MSG, EML, 7z, or RAR cannot be inspected without reading its bytes.
Terminal member bytes become durable Working Files only on an explicit need such
as Open.

Handler capability is split conceptually into:

```text
inspect / list_children
materialize(target_entry)
```

### D21-B - external applications edit a stable Working File

The first permitted Open of a virtual Workspace Item creates a stable Working
Artifact with a trusted suffix inside the Project. The operating system opens
that file directly. Subsequent opens reuse the same Working Artifact.

PIG records a baseline fingerprint at materialization and detects in-place
external edits through deterministic refresh checks. File-system notifications
and UI focus changes are hints; size/SHA-256 reconciliation is authoritative.
Save-As outside the Project is not automatically tracked.

### D22-B - Workspace overlay, no Container write-back in V1

Editing an archive or email member changes only its Working Artifact. V1 does
not silently rebuild or overwrite ZIP, RAR, 7z, MSG, or EML content. Moving an
item in the Workspace Tree also does not change its source Container.

Moving or adding an item "inside" a Container would imply repack/write-back and
is therefore not a V1 action. A future explicit export/repack capability requires
its own contract and decision. Exporting an organized Workspace as an ordinary
folder may be planned separately after the core loop works.

### D23-B - deletion is workspace-only and reversible

Delete changes Workspace Item lifecycle to `DELETED` after explicit user
confirmation. It does not delete the Original Snapshot or Source Node. Durable
Working Artifact bytes remain recoverable for Restore. Permanent purge is not a
normal V1 action. ADR-019 defines one narrow exception for undoing an accidental
top-level Import Item; arbitrary-node purge still requires a future retention
policy.

## Legacy Project boundary

The product owner explicitly removed old Project compatibility from scope. This
is not a D24 option selection: no legacy migration mode is required.

- Existing development/acceptance Projects are disposable.
- The new application may reject databases created for the previous domain
  model with a clear unsupported-model message.
- No in-place conversion, relationship repair, legacy read-only mode, or mixed
  old/new Project support is planned.
- SQL schema changes must still be managed deliberately; whether implementation
  uses a new baseline or a forward Alembic revision is decided before schema
  code begins. There is no legacy data-migration requirement.

## Minimum origin contract

V1 does not require audit-grade transitive Lineage as a product feature, but it
must preserve enough origin to support lazy materialization and restore:

```text
Workspace Item
  -> optional Source Node
  -> Source Relationship chain
  -> immutable Original Snapshot
```

This binding is not rewritten when the Workspace Item moves.

## Consequences for earlier ADRs

- ADR-001 D1 is superseded. D2 through D8 remain unless contradicted here.
- ADR-002 remains historical for immutable extracted Artifacts; new Original and
  Working storage contracts are defined by the Workbench model.
- ADR-003 through ADR-005 remain useful Handler/backend constraints, but Handler
  execution must evolve toward inspect/materialize separation.
- ADR-006 Manifest and structural Search are no longer V1 acceptance anchors.
- ADR-007 retains PySide6 and backend-controlled OS handoff; its assumption that
  opened bytes are immutable is replaced for Working Artifacts.
- ADR-008 recovery/packaging is historical and must be reevaluated for the new
  writable Workspace.
- ADR-009 D13/D15 remain useful for Source Structure and Project identity. D16's
  temporary open-handoff cache is superseded by stable Working Artifacts.

## Implementation authorization boundary

This ADR originally authorized planning only. The product owner subsequently
authorized and completed W1 through W7.2. ADR-011 records D25-B, ADR-012 records
D26-A through D29-A, ADR-013 records D30-B through D36-A, ADR-014 records D37-A
through D40-A, ADR-015 records D41-A through D46-A, ADR-016 records D47-A
through D52-A, ADR-017 records D53-A through D60-A, and ADR-018 records D61-A
through D64-A, and ADR-019 records D65-A through D68-A. Current authority does
not extend to W8 or later milestones.

Still outside V1: transparent Container repack, MSG/EML write-back,
arbitrary-node permanent purge, full document version history, content indexing, OCR, RAG, AI, Agent,
Workflow engine, Automation engine, MCP, cloud sync, multi-user collaboration,
Graph DB, Vector DB, or distributed workers.
