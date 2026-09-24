# ADR-013：Workbench 结构检查与物化边界 / Workbench Structure Inspection and Materialization Boundary

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-22 / Decision date: 2026-09-22
- 决策：D30-B、D31-A、D32-A、D33-A、D34-A、D35-A、D36-A / Decisions: D30-B, D31-A, D32-A, D33-A, D34-A, D35-A, D36-A
- 范围：Workbench Milestone W3 / Scope: Workbench Milestone W3

## 中文规范正文

### 背景

W2 已将外部输入捕获为不可变 Original Snapshot，并为每个成功 Snapshot 创建
Source Root。W3 必须发现 Folder/ZIP 的完整允许结构，但不能重新采用历史
`NodeExecutor` 在检查阶段批量发布 Extracted Artifact 的行为。

### 决策

1. **D30-B**：W3 使用独立的 Workbench-native Handler Contract。ZIP Adapter 将
   `inspect`、签名读取和单成员 `materialize` 分离；历史 Processing Executor 保持
   隔离，不作为 Workbench 主流程。
2. **D31-A**：延迟物化定位是显式业务数据。`SourceEntryLocator` 一对一绑定 Direct
   `NodeRelationship`，类型为 `SNAPSHOT_ENTRY` 或 `ZIP_MEMBER`。不得从
   `logical_path`、Display Name 或任意 JSON 猜测物化目标。
3. **D32-A**：首次 Inspection 将 Source Structure 完整投影为 Workspace Tree。
   Folder 映射为 `FOLDER`，ZIP 映射为 `CONTAINER_VIEW`，Terminal 映射为 `FILE`；
   每个来源项保存不可变 `origin_source_node_id`。只有初始投影可以在
   `CONTAINER_VIEW` 下创建来源 Child，后续 Move/Add 仍被拒绝。
4. **D33-A**：Working Artifact 使用生成标识和可信格式 Suffix：

   ```text
   working/<workspace-item-id>/content.<trusted-suffix>
   .staging/materializations/<operation-id>/<workspace-item-id>/content.<trusted-suffix>
   ```

   Display Name 不参与物理路径。发布使用同一 Project 内的 Staging 和原子替换。
5. **D34-A**：嵌套 ZIP 仅使用 Operation-scoped Inspection Cache：

   ```text
   .inspection/<operation-id>/objects/<generated-id>/content
   ```

   Cache 同时受单文件和操作总展开量限制，并在成功或失败后清理。Terminal
   Materialization 根据 Direct Relationship Chain 从 Original Snapshot 重放，不建立
   长期 Extracted Cache。
6. **D35-A**：W3 提供两个 typed in-process Application Action：
   `inspect_import_session` 与 `materialize_workspace_item`。前者接续 W2 的
   `INSPECTING` Session；后者只物化一个成功 Terminal Workspace File。它们不是
   MCP Tool，也不由 UI 拥有状态。
7. **D36-A**：Schema 通过 `0003_structure_workspace` 前向演进。Migration 新增
   `source_entry_locators`、Inspection Job 到 Import Session 的显式绑定，并调整初始
   Workspace Projection Trigger；不迁移旧 Evidence Project。

### 状态与结果

Structure Inspection 使用受控队列。成功 Session 进入 `SUCCESS`，存在可用来源同时
含阻断结果时进入 `PARTIAL_SUCCESS`，没有可用来源时进入 `FAILED`。Terminal Node 的
`SUCCESS` 只表示可物化，不表示 Working Artifact 已存在。

首次物化执行 `VIRTUAL|FAILED|INTERRUPTED -> MATERIALIZING -> MATERIALIZED|FAILED|
INTERRUPTED`。成功后 Working Artifact 的 Baseline 与 Current Fingerprint 相同，状态
为 `CLEAN`。外部编辑识别仍属于 W6。

### 明确不做

W3 不接入 EML、MSG、7z 或 RAR，不实现 OS Open、外部编辑刷新、Workspace Move/Add/
Delete、Container 回写、UI、AI、Automation 或 MCP。

## English normative text

## Context

W2 captures external inputs as immutable Original Snapshots and creates a Source
root for each successful snapshot. W3 must discover the complete permitted
Folder/ZIP structure without restoring the historical `NodeExecutor` behavior
that published every extracted child during inspection.

## Decisions

1. **D30-B**: W3 uses a separate Workbench-native Handler contract. The ZIP
   adapter separates `inspect`, signature reads, and one-member `materialize`.
   The historical processing executor remains isolated from the Workbench path.
2. **D31-A**: lazy-materialization identity is explicit business data. One
   `SourceEntryLocator` binds each materializable direct `NodeRelationship` and
   has kind `SNAPSHOT_ENTRY` or `ZIP_MEMBER`. Materialization never guesses from
   logical paths, display names, or arbitrary JSON.
3. **D32-A**: initial inspection fully projects Source Structure into Workspace
   Tree. Folders map to `FOLDER`, ZIPs to `CONTAINER_VIEW`, and terminals to
   `FILE`; every source-backed item keeps immutable `origin_source_node_id`.
   Only initial projection may create source children below a `CONTAINER_VIEW`;
   later move/add actions remain prohibited.
4. **D33-A**: Working Artifacts use generated identities and trusted format
   suffixes:

   ```text
   working/<workspace-item-id>/content.<trusted-suffix>
   .staging/materializations/<operation-id>/<workspace-item-id>/content.<trusted-suffix>
   ```

   Display names do not select physical paths. Publication uses staging and an
   atomic replace within the same Project.
5. **D34-A**: nested ZIPs use only operation-scoped inspection cache:

   ```text
   .inspection/<operation-id>/objects/<generated-id>/content
   ```

   The cache enforces per-file and operation-total expansion limits and is
   removed after success or failure. Terminal materialization replays the direct
   relationship chain from Original Snapshot; no durable extracted cache is
   introduced.
6. **D35-A**: W3 exposes two typed in-process Application actions:
   `inspect_import_session` and `materialize_workspace_item`. The first continues
   W2's `INSPECTING` session; the second materializes exactly one successful
   terminal Workspace file. They are not MCP Tools and UI does not own state.
7. **D36-A**: schema evolves through forward revision
   `0003_structure_workspace`. It adds `source_entry_locators`, an explicit
   inspection-job/import-session binding, and the initial Workspace projection
   trigger adjustment. Old Evidence Projects are not migrated.

## State and outcomes

Structure inspection uses a bounded queue. A session becomes `SUCCESS` when all
accepted sources are usable, `PARTIAL_SUCCESS` when a usable result coexists
with blocked outcomes, and `FAILED` when no source is usable. Terminal Node
`SUCCESS` means materializable, not already materialized.

First materialization follows `VIRTUAL|FAILED|INTERRUPTED -> MATERIALIZING ->
MATERIALIZED|FAILED|INTERRUPTED`. A successful Working Artifact starts with
equal baseline/current fingerprints and `CLEAN` content status. External-edit
reconciliation remains W6.

## Explicit exclusions

W3 does not add EML, MSG, 7z, or RAR handlers, OS Open, external-edit refresh,
Workspace move/add/delete, Container write-back, UI, AI, Automation, or MCP.
