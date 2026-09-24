# PIG V1 Workbench W7 实施记录 / Workbench W7 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-23 / Date: 2026-09-23
- 决策：`ADR-017` / Decision: `ADR-017`
- 下一阶段：W8 未授权 / Next stage: W8 not authorized

## 中文实施记录

### 1. 完成了什么

历史 Evidence Browser 已替换为单窗口 Project File Workbench。用户可以选择项目位置、
拖入或选择输入、查看 Workspace Tree、创建 Folder、Move/Reorder、Soft Delete/Restore、
延迟打开、刷新/恢复 Working File，并搜索当前 Workspace。所有文件和数据库规则仍由
W1–W6 Application 层执行。

### 2. 涉及的领域对象

W7 不新增持久化领域对象。新增 `WorkspaceItemView` 只读投影，组合 `Project`、
`WorkspaceItem`、`WorkspacePlacement`、Origin `Node` 和可选 `WorkingArtifact`。UI 显示
Workspace Revision、Lifecycle、Materialization 和 Content State，但不拥有这些事实。

### 3. 用户操作到输出

```text
Drop/select paths
-> AddWorkspaceInputsRequest
-> immutable Snapshot + eager structure inspection
-> Workspace projection
-> authoritative tree reload + accepted/failed summary

Drag Workspace Item
-> MoveWorkspaceItemRequest(expected revision)
-> backend validates target/cycle/order
-> SQLite Placement + Event
-> authoritative tree reload

Double-click File
-> OpenWorkspaceItemRequest
-> lazy materialize or refresh stable Working Artifact
-> OS default association handoff
-> tree/details/activity reload
```

### 4. 状态变化

UI 展示但不直接写入：Workspace `ACTIVE/DELETED`、Materialization
`VIRTUAL/MATERIALIZED/...` 和 Working Content `CLEAN/MODIFIED/MISSING/UNREADABLE`。
Tree 写 Action 使用最新 `workspace_revision`。Focus Refresh 只作用于当前选择且已经物化
的 File。

### 5. Event 与 Log

W7 不发明 UI Event。Import、Workspace Add/Move/Delete/Restore、Materialization、Open、
Refresh 和 Working Restore 继续由各自 Application Action 写入既有结构化 Event。
Activity Tab 只读展示最近 Event；Unexpected UI/Worker Failure 进入 Debug Log。

### 6. Tool 或 Action

新增三个 typed read Action：`get_workspace_tree`、`get_workspace_item`、
`search_workspace_items`。W2–W6 写 Action 被桌面复用，没有建立公共 Tool Server、MCP、
Agent、Workflow 或 Automation Adapter。

### 7. 安全和权限影响

- UI 不执行解压、Hash、SQL、路径验证或格式授权；
- 多路径输入仍先进入不可变 Original Snapshot；
- Drag/Drop 不做 Optimistic Tree Mutation，失败后不会留下虚假 UI Placement；
- Delete 和 Working Overwrite 使用显式确认；
- Unknown/Denied Format、Container Target、Cycle、Cross-project 和 Unsafe Path 仍由后端
  拒绝；
- 一个窗口最多一个后台 Action，避免 Revision 与确认竞争。

### 8. 测试覆盖

新增 Application Query 测试覆盖 Workspace Path、Origin、Working State、Revision、
Deleted Projection 和 Workspace Search。新增未跳过的 Qt 测试覆盖项目位置、Empty
Workspace Load、多路径 Drop Translation、Add/Inspect、Tree、稳定 Open、Explicit/
Focus Refresh、Search 双击 Open、Create/Move、Soft Delete/Restore、Working Restore、
Busy Protection 和 Original 不变。

全量结果：`126 passed, 95 skipped, 1 warning`。95 个 Skip 是 ADR-010 明确隔离的历史
Evidence 实现测试与当前 Host 不允许创建的 Symlink 场景；新的 W7 Qt 测试没有被跳过。
Warning 仍来自刻意构造的重复 ZIP Member Name。

### 9. 当前尚未闭环的边界

W8 尚未执行中断恢复对账、真实规模性能测试和 Windows Package 重建。当前 Picker 对
多个文件支持一次多选，文件夹通过单次 Folder Picker 或与文件混合拖放进入；系统不
跟踪 Project 外 Save-As，不实现 Watcher、Rename、Preview 或 Content Search。

### 10. 技术债务与下一步最小建议

Workspace Path 和有效 Lifecycle 当前由 Application Read Model 在内存组合，符合本地
V1，但超大项目查询复杂度需在 W8 Benchmark 中测量后再决定是否增加专用 Read Index。
UI 后台执行器当前不支持取消；中断与残留处理属于 W8。下一步最小建议是先进行一次
源码桌面真实验收，确认交互无偏差，再单独决定是否进入 W8。

## English implementation record

## 1. What changed

The historical Evidence Browser was replaced by a one-window Project File
Workbench. Users can choose Project storage, drop or select inputs, inspect the
Workspace Tree, create folders, move/reorder, soft-delete/restore, lazily open,
refresh/restore Working Files, and search the current Workspace. W1-W6
Application services remain authoritative for file and database rules.

## 2. Domain objects

W7 adds no persisted domain object. The new read-only `WorkspaceItemView`
combines Project, WorkspaceItem, WorkspacePlacement, origin Node, and optional
WorkingArtifact facts. UI displays Workspace revision, lifecycle,
materialization, and content state but does not own them.

## 3. User action to output

```text
Drop/select paths
-> AddWorkspaceInputsRequest
-> immutable Snapshot + eager structure inspection
-> Workspace projection
-> authoritative tree reload + accepted/failed summary

Drag Workspace Item
-> MoveWorkspaceItemRequest(expected revision)
-> backend validates target/cycle/order
-> SQLite Placement + Event
-> authoritative tree reload

Double-click File
-> OpenWorkspaceItemRequest
-> lazy materialize or refresh stable Working Artifact
-> OS default association handoff
-> tree/details/activity reload
```

## 4. State changes

UI displays but does not directly write Workspace `ACTIVE/DELETED`,
materialization `VIRTUAL/MATERIALIZED/...`, or Working content
`CLEAN/MODIFIED/MISSING/UNREADABLE`. Tree writes use the latest
`workspace_revision`. Focus refresh applies only to the selected materialized
file.

## 5. Events and logs

W7 invents no UI-owned business Event. Import, Workspace
add/move/delete/restore, materialization, Open, refresh, and Working Restore keep
using Events written by their Application actions. Activity is a read-only view
of recent Events. Unexpected UI/worker failures go to the Debug Log.

## 6. Tool or action impact

Added typed read actions `get_workspace_tree`, `get_workspace_item`, and
`search_workspace_items`. Desktop reuses W2-W6 writes. No public Tool server,
MCP, Agent, Workflow, or Automation adapter was introduced.

## 7. Permission and safety

- UI performs no extraction, hashing, SQL, path validation, or format
  authorization.
- Multi-path input still enters immutable Original Snapshot first.
- Drag/drop does not optimistically mutate the tree; failed actions leave no
  fabricated placement.
- Delete and Working overwrite require explicit confirmation.
- Backend still rejects Unknown/Denied formats, Container targets, cycles,
  cross-Project identity, and unsafe paths.
- One background action per window prevents revision and confirmation races.

## 8. Tests

New Application query tests cover Workspace path, origin, Working state,
revision, deleted projection, and Workspace Search. New non-skipped Qt tests
cover selected Project storage, empty Workspace load, multi-path drop
translation, add/inspect, tree display, stable Open, explicit/focus refresh,
Search-result Open, create/move, soft-delete/restore, Working Restore, busy
protection, and unchanged Original input.

The full result is `126 passed, 95 skipped, 1 warning`. The 95 skips are
ADR-010-quarantined historical Evidence tests and symlink scenarios unavailable
on this host. New W7 Qt tests are not skipped. The warning remains the deliberate
duplicate ZIP member-name fixture.

## 9. Open boundaries

W8 has not performed interrupted-write reconciliation, realistic-scale
performance tests, or Windows package rebuild. The picker supports multi-file
selection; folders enter through one folder picker or mixed file/folder drop.
The system does not track Save-As outside the Project and adds no watcher,
rename, preview, or content search.

## 10. Technical debt and smallest next step

Workspace path and effective lifecycle are currently composed in the
Application read model, appropriate for local V1. W8 benchmarks must measure
large Projects before any dedicated read index is justified. The UI background
executor does not support cancellation; interruption and residue handling belong
to W8. The smallest next step is one real source-run desktop acceptance before
separately deciding whether to enter W8.
