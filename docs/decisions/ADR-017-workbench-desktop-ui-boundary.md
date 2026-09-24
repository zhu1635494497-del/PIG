# ADR-017：Workbench 桌面 UI 边界 / Workbench Desktop UI Boundary

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-23 / Decision date: 2026-09-23
- 决策：D53-A、D54-A、D55-A、D56-A、D57-A、D58-A、D59-A、D60-A / Decisions: D53-A, D54-A, D55-A, D56-A, D57-A, D58-A, D59-A, D60-A
- 范围：Workbench Milestone W7 / Scope: Workbench Milestone W7

## 中文规范正文

### 背景

W1–W6 已完成 Workbench Domain、Original Snapshot、复杂 Container Structure、可变
Workspace Tree 和稳定 Open/Edit。历史 PySide6 界面仍以 Evidence Node、手工 Process
和临时 Open Handoff 为主，不能继续作为目标 V1 的用户入口。

### 决策

1. **D53-A**：用单一 Workbench 主界面替换 Evidence Browser。Workspace Tree 是主树，
   Item Details/Origin 和 Activity 是次级信息，不把 Lineage 作为主流程。
2. **D54-A**：新增 `get_workspace_tree`、`get_workspace_item` 和
   `search_workspace_items` typed Application Query。UI 不直接访问 Repository 或 SQL。
3. **D55-A**：多路径 Drop/Picker 形成一次 `add_workspace_inputs` Action，自动执行
   Snapshot 和 Inspection；目标只能是 Root 或普通 Workspace Folder。
4. **D56-A**：内部 Drag/Drop 表达 Move/Reorder，但 UI 不预先修改事实；后端成功后按
   新 `workspace_revision` 重新加载。支持 Drop-on-Folder、Sibling Order 和 Root。
5. **D57-A**：Normal Tree 隐藏 Deleted Item；显式 Tombstone 在独立 Deleted Items
   Tab 中显示并可 Restore。
6. **D58-A**：File 双击使用 W6 `open_workspace_item`；Folder/Container 只展开。提供
   Explicit Refresh、Selected Materialized File 的 Debounced Focus Refresh，以及受确认
   保护的 Working Restore。
7. **D59-A**：Search 面向 Workspace，而不是 Source Node；检索 Display Name、Workspace
   Path、Original Name 和 Source Logical Path，支持 Format/Content Status 多选并可双击
   打开。V1 不搜索文件内容。
8. **D60-A**：每个窗口一次只执行一个可能阻塞或写入的 Application Action。使用单个
   后台执行器，主线程领取结果并更新 UI；不允许并行写入，不在 W7 实现 Cancel、Crash
   Recovery 或新 Schema Migration。

### UI 与业务事实边界

- Workspace Tree、Search Result、Deleted List 都是 Application Read Model 的投影；
- UI 只提交 typed Request，后端继续负责 Revision、Cycle、Target、Format、Path、Hash
  和 Confirmation 校验；
- UI Tree 只有在后端 Action 成功后才刷新；失败不保留虚假移动结果；
- Window Focus 只是 Refresh Trigger，SHA-256 Observation 才是 Content State 事实；
- UI State 不写入 Project Database，不增加 `0006` Migration。

### 明确不做

W7 不实现 W8 Crash Recovery、Benchmark、Packaging、多人并发、Watcher、Preview、
Thumbnail、Rename、Permanent Purge、Container Write-back、内容索引、AI、Agent、
Workflow、Automation 或 MCP。

## English normative text

## Context

W1-W6 completed the Workbench domain, immutable snapshots, complex Container
structure, mutable Workspace Tree, and stable open/edit loop. The historical
PySide6 UI still centered on Evidence Nodes, manual processing, and temporary
open handoff, so it cannot remain the target V1 user entry point.

## Decisions

1. **D53-A**: replace the Evidence Browser with one Workbench window. Workspace
   Tree is primary; Item Details/Origin and Activity are secondary. Lineage is
   not a primary user flow.
2. **D54-A**: add typed Application queries `get_workspace_tree`,
   `get_workspace_item`, and `search_workspace_items`. UI never accesses a
   Repository or SQL directly.
3. **D55-A**: one multi-path drop/picker operation creates one
   `add_workspace_inputs` action and automatically performs snapshot plus
   inspection. A target is Project root or an ordinary Workspace folder only.
4. **D56-A**: internal drag/drop expresses move/reorder, but UI does not mutate
   facts optimistically. It reloads the authoritative revision after backend
   success. Drop-on-folder, sibling ordering, and root placement are supported.
5. **D57-A**: normal tree hides deleted Items. Explicit tombstones appear in a
   separate Deleted Items tab and can be restored there.
6. **D58-A**: file double-click calls W6 `open_workspace_item`; folders and
   Containers only expand. Explicit refresh, debounced focus refresh of the
   selected materialized file, and confirmation-protected Working Restore are
   exposed.
7. **D59-A**: Search targets Workspace Items, not Source Nodes. It searches
   display name, Workspace path, original name, and Source logical path, supports
   multi-select format/content-state filters, and opens file results. V1 does
   not search file contents.
8. **D60-A**: one window runs only one potentially blocking or writing
   Application action at a time. A single background executor runs work and the
   main thread consumes results. W7 adds no concurrent writes, cancellation,
   crash recovery, or schema migration.

## UI and business-fact boundary

- Workspace Tree, Search Result, and Deleted List are projections of typed
  Application read models.
- UI submits typed requests; backend remains authoritative for revision, cycle,
  target, format, path, hash, and confirmation checks.
- UI reloads the tree only after a backend action succeeds; a failure leaves no
  fabricated move result.
- Window focus is only a refresh trigger. SHA-256 observation determines content
  state.
- UI state is not stored in the Project database and no `0006` migration exists.

## Explicit exclusions

W7 does not implement W8 crash recovery, benchmarks, packaging, multi-user
concurrency, watchers, preview, thumbnails, rename, permanent purge, Container
write-back, content indexing, AI, Agent, Workflow, Automation, or MCP.
