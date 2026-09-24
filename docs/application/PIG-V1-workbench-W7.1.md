# PIG V1 Workbench W7.1 实施记录 / Workbench W7.1 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-23 / Date: 2026-09-23
- 决策：ADR-018，D61-A 至 D64-A / Decision: ADR-018, D61-A through D64-A

## 中文实施记录

### 1. 本次修改了什么

中央 Workbench 现在统一接收外部拖入；Working File 使用安全友好文件名；每个
Working Artifact 维护当前校验副本和一个上一版本；用户可以确认后回滚；一个文件
直接导出，多个文件按 Workspace 相对路径导出 ZIP。Tree/Search 支持导出多选，但
Move/Reorder 仍保持单项动作。

### 2. 新增或修改的领域对象

新增 `WorkingRevision`，角色严格为 `CURRENT_CHECKPOINT` 或 `PREVIOUS`，每个
Working Artifact 每个角色最多一条。`WorkspaceItemView` 增加当前/上一版本只读投影。
Export 使用 typed Request/Result，不新增持久 Export Session。

### 3. 数据完整流向

首次 Materialize 生成友好 Working File 和同 Hash 当前校验副本。Refresh 发现新 Hash
时把旧校验副本轮换为上一版本，并从稳定 Working File 建立新校验副本。Rollback
交换当前和上一字节。Export 对 Virtual File 先 Materialize，对已有 Working File 先
Refresh，然后经外部目标暂存文件原子发布。

### 4. 状态变化

继续使用 `CLEAN/MODIFIED/MISSING/UNREADABLE`，没有新增 Content Status。Rollback
根据目标版本是否等于 Baseline 决定 `CLEAN` 或 `MODIFIED`。版本角色不是处理状态。

### 5. Event 与 Log

新增 `WORKING_VERSION_CAPTURED`、`WORKING_FILE_ROLLED_BACK`、
`WORKSPACE_EXPORT_REQUESTED/COMPLETED/FAILED`。Host Save 仍不是可直接证明的事件；
版本时间明确区分文件修改时间和 PIG 检测时间。

### 6. Tool / Action

新增 `rollback_working_artifact` 和 `export_workspace_items` typed in-process Actions。
它们尚未作为公共 Tool、Automation 或 MCP 暴露。

### 7. 权限与安全

Rollback 和覆盖导出必须确认。版本与导出拒绝 Symlink、非普通文件、Traversal、受管
Project 内导出目标和静默重名。Original Snapshot、Source Structure 与 Origin Binding
不受版本、回滚或导出影响。

### 8. 测试覆盖

专项测试覆盖友好文件名、两槽版本轮换、双向回滚、Original 不变、单文件当前字节
导出、多文件 ZIP、Virtual Materialization、Workspace 路径和重名拒绝，以及中央
Workbench Drop Surface。最终全量结果记录在本次完成汇报中。

### 9. 当前尚未闭环的边界

PIG 不接收 Host Application Save Callback；两次检测之间的多次保存只保留最后一次
可观察状态。PIG 只能对同名 Host 冲突做本会话事前警告，不能证明 Host 内部是否拒绝。
Folder/Container View 递归导出、Container write-back、Watcher 和 Save-As 跟踪不实现。

### 10. 技术债务与下一步

文件系统版本轮换与 SQLite 提交跨两个本地持久化介质；W7.1 使用暂存、Hash 校验和
原子替换降低风险，但进程在两者之间崩溃后的对账属于 W8 Recovery。下一步必须先
完成 W7.1 真实桌面验收，再由产品负责人单独授权 W8。

## English implementation record

## 1. What changed

The central Workbench now accepts external drops, Working Files use safe friendly
names, each Working Artifact maintains a current checkpoint and one previous
version, users can roll back after confirmation, one file exports directly, and
multiple files export as a ZIP preserving Workspace-relative paths. Tree/Search
support export multi-selection while Move/Reorder remains single-item.

## 2. Domain objects

`WorkingRevision` is new, with a strict `CURRENT_CHECKPOINT` or `PREVIOUS` role
and at most one row per role per Working Artifact. `WorkspaceItemView` adds
read-only current/previous version projections. Export uses typed Request/Result
contracts and adds no persisted Export Session.

## 3. End-to-end data flow

First materialization creates the friendly Working File and a same-hash current
checkpoint. When Refresh detects a new hash, the old checkpoint rotates to
previous and the stable Working File becomes the new checkpoint. Rollback swaps
current and previous bytes. Export materializes a Virtual File or refreshes an
existing Working File, then atomically publishes through a staging file beside
the external destination.

## 4. State changes

`CLEAN/MODIFIED/MISSING/UNREADABLE` remain the complete durable content states.
Rollback becomes `CLEAN` or `MODIFIED` according to the target hash versus the
Baseline. A revision role is not a processing status.

## 5. Events and logs

New Events are `WORKING_VERSION_CAPTURED`, `WORKING_FILE_ROLLED_BACK`, and
`WORKSPACE_EXPORT_REQUESTED/COMPLETED/FAILED`. Host Save remains unprovable;
version presentation distinguishes file modification time from PIG detection
time.

## 6. Tool and Action impact

`rollback_working_artifact` and `export_workspace_items` are new typed in-process
Actions. Neither is yet a public Tool, Automation, or MCP surface.

## 7. Permission and safety

Rollback and export replacement require confirmation. Version/export storage
rejects symlinks, non-regular files, traversal, destinations inside the managed
Project, and silent path collisions. Original Snapshot, Source Structure, and
Origin Binding never change.

## 8. Test coverage

Focused coverage includes friendly filenames, two-slot rotation, reversible
rollback, Original immutability, current-byte single export, ZIP export, Virtual
materialization, Workspace paths, collision rejection, and the central drop
surface. The final full-suite result is recorded in the completion report.

## 9. Open boundaries

PIG receives no Host Application save callback; multiple saves between two
detections collapse to the final observable state. Same-name Host conflicts can
only receive a current-session warning, not a proven Host rejection. Recursive
Folder/Container View export, Container write-back, watchers, and Save-As
tracking remain excluded.

## 10. Technical debt and next step

Version rotation spans filesystem publication and SQLite commit. W7.1 reduces
risk with staging, hashes, and atomic replacement, but reconciliation after a
crash between the two belongs to W8 Recovery. Complete real desktop W7.1
acceptance before the owner separately authorizes W8.
