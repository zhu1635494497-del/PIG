# PIG V1 Workbench W3 实施记录 / Workbench W3 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-22 / Date: 2026-09-22
- 决策：`ADR-013` / Decision: `ADR-013`
- 后续状态：W7 已完成；W8 未授权 / Later status: W7 complete; W8 not authorized

## 中文实施记录

### 1. 本次修改了什么

实现了 Snapshot-backed Folder/ZIP 的完整结构发现、初始 Workspace Tree 投影和
单目标 Lazy Materialization。历史 Evidence Processing 路径未被重新启用，UI 未修改。

### 2. 涉及的领域对象

- `Source`、`Node`、`NodeRelationship`：保存不可变来源结构；
- `SourceEntryLocator`：保存 `SNAPSHOT_ENTRY` 或 `ZIP_MEMBER` typed 定位；
- `ImportSession`、`ProcessingJob`、`ProcessingEvent`：表达 W3 操作与结果；
- `WorkspaceItem`、`WorkspacePlacement`：保存初始可见结构和最小 Origin；
- `WorkingArtifact`：保存一个被明确选择的稳定 Working File。

### 3. 完整数据流

```text
INSPECTING ImportSession
-> verify Original Artifact SHA-256
-> Folder Snapshot Entry / ZIP inspect
-> queue nested ZIP through bounded .inspection cache
-> persist Source Nodes + direct Relationships + typed Locators
-> project complete Source Structure into virtual Workspace Items
-> finish Session and Project state

materialize_workspace_item
-> resolve Workspace Origin
-> replay direct Relationship/Locator chain from Original Snapshot
-> publish one stable Working Artifact atomically
-> persist baseline/current fingerprint
```

未选择的 Terminal 只存在于 Source/Workspace 结构，不产生 Working Artifact。

### 4. 状态变化

- `ImportSession`：`INSPECTING -> SUCCESS | PARTIAL_SUCCESS | FAILED`；
- `Project`：`IMPORTING -> PROCESSING -> READY | READY_WITH_WARNINGS | FAILED`；
- `Node`：`DISCOVERED -> PENDING -> PROCESSING -> terminal result`；
- `WorkspaceItem`：初始为 `VIRTUAL`；单文件物化进入
  `MATERIALIZING -> MATERIALIZED | FAILED | INTERRUPTED`；
- `WorkingArtifact`：成功创建时为 `CLEAN`。

### 5. Event 与 Log

记录 Job Created/Started/Finished、Project Status Changed、Node Format/Result、
Container Opened、Child Discovered、Relationship Created、Workspace Item Added、Import
Finished/Failed，以及 Working Materialization Started/Materialized/Failed。Unexpected
Snapshot Failure 进入 Debug Logger，不替代业务失败状态。

### 6. 新增 Action

- `inspect_import_session(request) -> InspectImportSessionResult`
- `materialize_workspace_item(request) -> MaterializeWorkspaceItemResult`

二者是 typed in-process Application Contract，不是公共 MCP Tool。

### 7. 权限与安全

- 只读取并重新验证 Project-owned Original；不再读取导入后的 External Input；
- ZIP Path Traversal、Absolute/Device Path、Symlink、Password、Corruption、Entry Count、
  Single Size、Expanded Total 和 Compression Ratio 均产生结构化结果；
- Working/Cache 路径只使用生成标识和可信 Suffix；
- `.inspection` 在成功和失败后清理；Working Publish 使用 Staging 与原子替换；
- W3 不修改 Original，不回写 ZIP。

### 8. 测试覆盖

覆盖 Nested ZIP、隐式目录、Folder Snapshot Entry、重复 ZIP 名称、Traversal、损坏
ZIP、密码条目、Compression Ratio、单目标物化、稳定文件复用、Cache 清理和应用重启
后的 Inspection 幂等结果。

最终全量结果：`95 passed, 95 skipped`。两个 Symlink Case 因当前 Windows Host 不允许
创建测试 Symlink 而 Skip；其余 Skip 是 ADR-010 隔离的历史 Evidence/UI 测试。重复
ZIP 名称测试产生一条 Python `zipfile` 预期 Warning。

### 9. 尚未闭环边界

EML、MSG、7z、RAR 属于 W4；Workspace Move/Add/Delete 属于 W5；Controlled Open、
External Edit Refresh 和覆盖确认属于 W6；PySide6 Workbench UI 属于 W7；Crash 后
Staging/Working 对账与真实性能验证属于 W8。

### 10. 技术债务

历史 Evidence Handler/Executor 仍保留在代码库并由测试隔离；在 W4 将剩余 Container
迁入新 Contract 后，应单独评估删除时机。W3 使用同步本地 Queue 和 SQLite Transaction，
符合当前单机范围，不引入异步 Worker。

## English implementation record

## 1. What changed

Implemented complete structure discovery for snapshot-backed Folder/ZIP inputs,
initial Workspace Tree projection, and one-target lazy materialization. The
historical Evidence processing path was not reactivated and UI was unchanged.

## 2. Domain objects

- `Source`, `Node`, and `NodeRelationship` persist immutable source structure;
- `SourceEntryLocator` persists typed `SNAPSHOT_ENTRY` or `ZIP_MEMBER` identity;
- `ImportSession`, `ProcessingJob`, and `ProcessingEvent` describe W3 execution;
- `WorkspaceItem` and `WorkspacePlacement` persist the initial visible tree and
  minimum origin binding;
- `WorkingArtifact` represents one explicitly selected stable Working File.

## 3. Complete data flow

```text
INSPECTING ImportSession
-> verify Original Artifact SHA-256
-> Folder Snapshot Entry / ZIP inspect
-> queue nested ZIP through bounded .inspection cache
-> persist Source Nodes + direct Relationships + typed Locators
-> project complete Source Structure into virtual Workspace Items
-> finish Session and Project state

materialize_workspace_item
-> resolve Workspace Origin
-> replay direct Relationship/Locator chain from Original Snapshot
-> publish one stable Working Artifact atomically
-> persist baseline/current fingerprint
```

Unselected terminal members exist only as Source/Workspace structure and do not
receive Working Artifacts.

## 4. State changes

- `ImportSession`: `INSPECTING -> SUCCESS | PARTIAL_SUCCESS | FAILED`;
- `Project`: `IMPORTING -> PROCESSING -> READY | READY_WITH_WARNINGS | FAILED`;
- `Node`: `DISCOVERED -> PENDING -> PROCESSING -> terminal result`;
- `WorkspaceItem`: initially `VIRTUAL`; one-file materialization follows
  `MATERIALIZING -> MATERIALIZED | FAILED | INTERRUPTED`;
- `WorkingArtifact`: starts as `CLEAN` after successful publication.

## 5. Events and logs

W3 records Job Created/Started/Finished, Project Status Changed, Node
Format/Result, Container Opened, Child Discovered, Relationship Created,
Workspace Item Added, Import Finished/Failed, and Working Materialization
Started/Materialized/Failed. Unexpected snapshot failures also reach the debug
logger without replacing persisted business failure state.

## 6. New actions

- `inspect_import_session(request) -> InspectImportSessionResult`
- `materialize_workspace_item(request) -> MaterializeWorkspaceItemResult`

Both are typed in-process Application contracts, not public MCP Tools.

## 7. Permission and safety

- W3 reads and re-verifies only Project-owned Originals; it does not return to
  the external input after import.
- ZIP traversal, absolute/device paths, symlinks, passwords, corruption, entry
  count, single size, expanded total, and compression ratio produce structured
  outcomes.
- Working/cache paths use generated identities and trusted suffixes only.
- `.inspection` is removed after success or failure; Working publication uses
  staging and atomic replace.
- W3 never modifies Original bytes or writes back ZIP content.

## 8. Tests

Coverage includes nested ZIP, implicit directories, Folder Snapshot Entries,
duplicate ZIP names, traversal, corrupt ZIP, encrypted entries, compression
ratio, one-target materialization, stable-file reuse, cache cleanup, and
idempotent inspection after application restart.

Final full-suite result: `95 passed, 95 skipped`. Two symlink cases are skipped
because this Windows host cannot create test symlinks; the other skips are
historical Evidence/UI tests quarantined by ADR-010. The duplicate-name ZIP test
emits one expected Python `zipfile` warning.

## 9. Open boundaries

EML/MSG/7z/RAR belong to W4; Workspace move/add/delete to W5; controlled open,
external-edit refresh, and overwrite confirmation to W6; PySide6 Workbench UI
to W7; crash reconciliation and realistic performance qualification to W8.

## 10. Technical debt

Historical Evidence handlers/executors remain in the repository under test
quarantine. Their removal should be evaluated separately after W4 ports the
remaining Containers. W3 deliberately uses a synchronous local queue and SQLite
transaction for the current desktop scope; no asynchronous worker was added.
