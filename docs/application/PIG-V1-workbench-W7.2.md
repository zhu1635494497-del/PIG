# PIG V1 Workbench W7.2 实施记录 / Workbench W7.2 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-23 / Date: 2026-09-23
- 决策：ADR-019，D65-A 至 D68-A / Decision: ADR-019, D65-A through D68-A

## 中文实施记录

### 1. 本次修改了什么

新 Project 现在直接创建在用户所选父目录下的合法 Project 名称目录中。Workspace
Tree、Search Results 和 Deleted Items 增加后端 Action 驱动的右键入口。用户可对一
次批量拖入中的误选顶层项预览影响、二次确认并撤销；单个普通 Workspace Folder 可
导出为保留当前结构的普通目录。

### 2. 新增或修改的领域对象

`OriginalSnapshot`、`OriginalArtifact`、`Source` 和 `WorkspaceItem` 增加 `PURGED`
可用性终态；`WorkspaceExportKind` 明确区分 `FILE/DIRECTORY/ZIP`；新增
`ImportUndoImpact` 及 Preview/Undo Request/Result。`ImportSessionItem` 身份和 Capture
结果继续作为历史事实保留。

### 3. 数据完整流向

Create Project 将临时目录发布为 `<selected-parent>/<project-name>`。Import Undo 从
所选 Workspace Source Root 解析 Source、Snapshot、全部派生 Item、Working Artifact
和版本槽，先生成影响预览；确认后把受管字节移动到操作级暂存，事务写入 `PURGED`、
递增 `workspace_revision` 并发出完成 Event，再删除暂存。Folder Export 展开有效子树，
对 Virtual File 物化、对 Working File 刷新，再通过同级暂存目录发布到外部目标。

### 4. 状态变化

Snapshot 从可用/完整性异常状态进入 `PURGED`；Source 和 Original Artifact 同步进入
`PURGED`；该 Source 派生 Workspace Item 从 `ACTIVE/DELETED` 进入 `PURGED`。
`PURGED` 不出现在正常 Tree、Search 或 Deleted Items，且不能恢复。普通 Soft Delete
仍使用可恢复的 `DELETED`。

### 5. Event 与 Log

新增 `IMPORT_ITEM_UNDO_REQUESTED`、`IMPORT_ITEM_UNDO_COMPLETED`、
`IMPORT_ITEM_UNDO_FAILED`，并记录影响计数、移除字节和结构化失败码。Folder Export
继续使用 `WORKSPACE_EXPORT_REQUESTED/COMPLETED/FAILED`，details 增加明确的
`export_kind`。

### 6. Tool / Action

新增 `preview_import_undo` 和 `undo_imported_item` typed in-process Actions；
`export_workspace_items` 扩展为文件、普通目录和 ZIP 三种确定性输出。当前没有公共
API、MCP、Agent、Workflow 或 Automation Adapter。

### 7. 权限与安全

Import Undo 必须命中 Source Root、先预览再确认，并且永不删除外部输入；嵌入成员、
逻辑 Folder 和混入其他 Source 后代的树均拒绝。删除受管字节前先进入可回滚暂存；
Project 名称执行 Windows 路径段校验且不静默改名。Folder Export 拒绝 Project 内目标、
Symlink、Traversal、路径冲突和已有目录，不执行合并或覆盖。

### 8. 测试覆盖

专项测试覆盖名称目录与冲突、同批 Folder + 误选 File 的定向撤销、外部输入和 Sibling
不变、嵌入成员拒绝、状态/Event Tombstone、文件夹嵌套/空目录/当前 Working 字节导出、
已有目标拒绝，以及 Qt 右键入口与桌面导出。Alembic Upgrade/Downgrade、触发器保留和
全量回归均纳入验证。

### 9. 当前尚未闭环的边界

不提供任意节点 Hard Delete；Container Member 不能独立于其顶层 Import Item 清除；
已有 UUID Project 不迁移；目录 Export 不合并或覆盖已有目录；Rename、Container
Write-back 与完整版本历史仍不实现。

### 10. 技术债务与下一步

Import Undo 跨文件系统暂存和 SQLite 提交。当前保证进程内失败恢复，但在暂存与事务
之间强制终止后的孤儿识别和自动对账属于 W8 Recovery。产品负责人已在 W7.2 人工
验收通过后授权进入 W8 决策门；D69–D77 批准前不实施 Recovery 或 Packaging 代码。

## English implementation record

## 1. What changed

New Projects now use a valid Project-name directory directly under the selected
parent. Workspace Tree, Search Results, and Deleted Items expose backend Action
context menus. A user can preview, confirm, and undo one accidentally selected
top-level input from a multi-path drop. One ordinary Workspace folder exports as
a normal directory preserving its current structure.

## 2. Domain objects

`OriginalSnapshot`, `OriginalArtifact`, `Source`, and `WorkspaceItem` gain the
terminal availability state `PURGED`. `WorkspaceExportKind` distinguishes
`FILE/DIRECTORY/ZIP`. `ImportUndoImpact` and typed Preview/Undo Request/Result
contracts are new. `ImportSessionItem` identity and capture outcome remain
historical facts.

## 3. End-to-end data flow

Create Project publishes a temporary workspace as
`<selected-parent>/<project-name>`. Import Undo resolves the selected Workspace
Source Root to its Source, Snapshot, every derived Item, Working Artifact, and
version slot, then returns an impact preview. After confirmation, managed bytes
move to operation staging, one transaction writes `PURGED`, advances
`workspace_revision`, and emits completion, after which staging is deleted.
Folder Export expands the active subtree, materializes Virtual Files, refreshes
Working Files, and publishes through a sibling staging directory.

## 4. State changes

Snapshot, Source, Original Artifacts, and all Source-derived Workspace Items
enter `PURGED`. Purged items appear in neither the normal tree, Search, nor
Deleted Items and cannot be restored. Ordinary Soft Delete remains the
recoverable `DELETED` state.

## 5. Events and logs

New Events are `IMPORT_ITEM_UNDO_REQUESTED`,
`IMPORT_ITEM_UNDO_COMPLETED`, and `IMPORT_ITEM_UNDO_FAILED`, with impact counts,
removed bytes, and structured failure codes. Folder Export reuses
`WORKSPACE_EXPORT_REQUESTED/COMPLETED/FAILED` and records explicit
`export_kind` details.

## 6. Tool and Action impact

`preview_import_undo` and `undo_imported_item` are new typed in-process Actions.
`export_workspace_items` now has deterministic file, ordinary-directory, and
ZIP outputs. No public API, MCP, Agent, Workflow, or Automation adapter is added.

## 7. Permission and safety

Import Undo must target a Source Root, preview impact, and receive confirmation;
it never deletes the external input. Embedded members, logical folders, and a
tree containing descendants from another Source are rejected. Managed bytes
move to recoverable staging before database mutation. Project names receive
strict Windows segment validation without silent rewriting. Folder Export
rejects managed-Project destinations, symlinks, traversal, path collisions, and
existing directories; it never merges or replaces a directory.

## 8. Test coverage

Focused coverage includes named directory collision, targeted undo of an
accidental File beside a Folder in one drop, unchanged external input and
sibling, embedded-member rejection, state/Event tombstones, nested and empty
directory export with current Working bytes, existing-destination refusal, and
Qt context-menu/desktop export paths. Alembic upgrade/downgrade, trigger
preservation, and full regression are also verified.

## 9. Open boundaries

There is no arbitrary-node hard delete. A Container member cannot be purged
independently of its top-level Import Item. Existing UUID Projects are not
migrated. Directory export never merges or replaces an existing directory.
Rename, Container write-back, and full version history remain excluded.

## 10. Technical debt and next step

Import Undo spans filesystem staging and SQLite commit. Current code restores
in-process failures, but orphan classification and automatic reconciliation
after forced termination between those media belong to W8 Recovery. After W7.2
manual acceptance, the owner authorized entry into the W8 decision gate; no
Recovery or Packaging code begins before D69-D77 are approved.
