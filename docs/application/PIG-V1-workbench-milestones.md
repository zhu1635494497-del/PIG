# PIG V1 工作台里程碑计划 / Workbench Milestone Plan

- 状态：规划基线 / Status: Planning baseline
- 日期：2026-09-24 / Date: 2026-09-24
- 当前授权：W8 验收通过；W9 仅授权规划 / Current authorization: W8 accepted; W9 planning only
- 约束决策：`ADR-010`、`ADR-018`、`ADR-019`、`ADR-020` / Governing decisions: `ADR-010`, `ADR-018`, `ADR-019`, `ADR-020`

## 中文规范正文

历史 Milestone 1–10 只描述证据导向实现，不授权 Workbench 代码变化。以下每个
Milestone 必须单独批准，并在进入下一阶段前完成可运行、可测试的数据闭环。

### W0：产品与架构重置

- **目标**：确定唯一无冲突的 V1 Scope、Dual-tree Model、State Machine、Legacy
  Boundary 和 Acceptance。
- **输入**：D17-B 至 D23-B；旧 Project 无需兼容。
- **核心实现**：更新长期规则、ADR-010、Source/Workspace 边界、Snapshot/Lazy
  Materialization/Edit Refresh/Soft Delete，并标记历史文档。
- **数据落库**：无。
- **测试**：文档一致性和冲突语句检查。
- **验收**：可以无歧义地批准 W1，且没有修改代码、Migration、Package 或 UI。

### W1：Workbench Domain 与 Persistence Foundation

- **目标**：在不实现 Import/UI 的前提下表达新模型。
- **输入**：已批准 Domain Model 和 State Machine。
- **核心实现**：ImportSession、OriginalSnapshot/Artifact、WorkspaceItem/Placement、
  WorkingArtifact、Invariant/Transition、Repository；决定新 Schema Baseline 还是
  Forward Alembic Revision；明确拒绝旧 Model Version。
- **数据落库**：新 Table、Constraint、Index 和 Event Vocabulary；不迁移旧 Row。
- **测试**：Domain Transition、Cycle/Relationship Constraint、Repository Round-trip、
  Rollback 和 Clean DB Migration。
- **验收**：新空 Workbench Project 可持久化并重载核心对象，尚不导入字节。

### W2：不可变 Snapshot Import Application Loop

- **目标**：通过 Typed Action 把外部文件/文件夹复制为已验证 Original。
- **输入**：一个或多个用户授权绝对路径。
- **核心实现**：Preflight/Containment、Bounded Streaming、Staging/Atomic Publish、
  Folder/File Ownership 和 Partial-success Contract。
- **数据落库**：ImportSession、Snapshot、OriginalArtifact、Source Root、Fingerprint、
  Status/Event。
- **测试**：File/Folder、Duplicate、导入后移除 Source、复制中变化、Symlink、
  Unreadable、Limit、Interrupt、Original Immutable。
- **验收**：导入成功后移除外部输入仍可验证 Project-owned Snapshot。

### W3：Folder/ZIP Inspect 与 Materialize 分离

- **目标**：证明 Structure Eager Discovery 与 Terminal Lazy Materialization。
- **输入**：Snapshot-backed Folder/ZIP，包括 Nested ZIP。
- **核心实现**：Handler 分离、结构持久化但不批量发布 Working File、内层 Container
  Operation Cache、基于 Direct Relationship 的 Materialization Recipe、初始化
  Workspace Tree。
- **数据落库**：Source Node/Relationship、Origin Binding、Workspace Item/Placement、
  Processing/Materialization State。
- **测试**：Nested Path、Implicit Folder、Duplicate、Traversal、Zip Bomb、Corrupt/
  Encrypted ZIP、Single-target Materialization、Restart。
- **验收**：Nested ZIP Tree 可见，未选择 Terminal 没有 Working Artifact，选择一个
  只物化该文件。

### W4：Email、7z 与 RAR 复杂 Container

- **目标**：把 W3 边界一致应用到剩余 Container。
- **输入**：EML、MSG、7z、RAR 及混合嵌套链。
- **核心实现**：各 Adapter 的 Inspect/Materialize；保持 RAR 的 7-Zip Trust/Version
  Boundary；Bounded Cache；Format-specific Error Mapping，Processor 不分支。
- **数据落库**：沿用 W3 Contract，并保存 Backend Identity 和明确失败结果。
- **测试**：ZIP→MSG/EML→ZIP/7z→Office/PDF、Attachment Collision、Malformed Mail、
  Encrypted、7-Zip Missing/Rejected、Limit。
- **验收**：所有支持 Container 使用相同 Framework 和 Lazy Terminal Semantics。

### W5：可变 Workspace Tree Action

- **目标**：让用户整理 Project，且独立于 Source Structure。
- **输入**：由 Source 初始化的 Workspace Item 和新增输入。
- **核心实现**：Create Folder、Move/Reorder、Add Snapshotted Input、Soft Delete/
  Restore；拒绝 Cycle、Cross-project 和 Container Write-back Target。
- **数据落库**：Placement/Lifecycle、Restore Placement、Structured Event。
- **测试**：Move Subtree/Root、Cycle/Target Rejection、Add、Delete/Restore、Restart、
  Concurrent Action Rejection、Source Fact Unchanged。
- **验收**：重启不丢布局，Original Hash 与 Source Relationship 不变。

### W6：稳定 Open 与外部 Edit Reconciliation

- **目标**：让 Workspace 成为真实编辑面。
- **输入**：Virtual 或 Materialized Terminal Workspace Item。
- **核心实现**：Safe-suffix Stable Working Artifact、Allowlist/Open、Reuse、Focus/
  Explicit Refresh、Content State，以及会覆盖 Current Bytes 时的确认。
- **数据落库**：Baseline/Current Fingerprint、Content State、Observation、Open/
  Change Event。
- **测试**：Edit、Return to Baseline、Missing/Unreadable、Save-As Boundary、Event
  Deduplication、Unsafe Path、Host Failure。
- **验收**：测试文档能打开、原地保存、识别 Modified、关闭后以修改字节重开。

### W7：PySide6 Workbench UI

- **目标**：在一个一致桌面界面呈现已完成能力。
- **输入**：W2–W6 Typed Action/Query。
- **核心实现**：Multi-path Drag/Drop、Progress/Summary、Workspace Tree、Move/Add/
  Create/Delete/Restore、State Badge、Search/Open、Refresh，以及非主界面的 Source
  Detail。
- **数据落库**：UI 不拥有业务状态，所有变化经 Application Contract。
- **测试**：Qt Drag/Drop Request、Confirmation、Busy Protection、Persistence、Error、
  Open、Refresh、Restart。
- **验收**：标准桌面流程无需用户直接操作 DB 或 Project Filesystem。

### W7.1：桌面验收可用性闭环

- **目标**：闭合 W7 真实验收发现的拖入、误保存保护、Host 文件名和交付出口缺口。
- **输入**：W7 源码桌面闭环与 D61-A 至 D64-A。
- **核心实现**：中央 Workbench Drop Surface、当前/上一 Working 版本槽与确认回滚、
  安全友好 Working 文件名、单文件导出和多文件 ZIP 导出。
- **数据落库**：`working_revisions` 两角色槽；版本捕获、回滚和导出 Event。
- **测试**：版本轮换/回滚、Original 不变、友好名称、重名、导出原子发布、路径冲突、
  整体拖放和 UI 多选。
- **验收**：用户可以从导入、外部编辑和误保存恢复一直完成到可传递的导出文件。

### W7.2：项目可辨识性、误导入撤销与文件夹交付

- **目标**：闭合真实办公流程中的 Project 目录辨识、批量拖入误选撤销、右键操作和
  完整文件夹交付缺口。
- **输入**：W7.1 闭环与 D65-A、D66-B（收紧）、D67-A、D68-A。
- **核心实现**：`<selected-parent>/<project-name>/project.sqlite`；顶层
  `ImportSessionItem` 影响预览与确认撤销；Workspace/Deleted Items 右键菜单；单个
  普通 Workspace 文件夹导出为普通目录。
- **数据落库**：Snapshot、Source、Original Artifact 和 Workspace Item 的 `PURGED`
  可用性状态；Requested/Completed/Failed Event；Project Revision 递增。Import Capture
  历史身份不删除。
- **测试**：合法/冲突 Project 名称；同批 Folder + 误选 File 的定向撤销；外部输入
  不变；嵌入成员拒绝；目录结构、空目录和当前 Working 字节导出；Qt 右键入口。
- **验收**：用户可直观看到 Project 存储目录、只撤销一次拖入中的误选顶层项，并把
  一个整理后的 Workspace 文件夹按当前结构交付。

### W8：Recovery、Performance 与 Packaging 重置

- **目标**：验证可写 Workbench 在真实规模和中断下的可靠性。
- **输入**：W1–W7.2 完整闭环。
- **核心实现**：Snapshot Staging、Inspection Cache、Working Publish 对账；保护
  Modified Working File；Benchmark；重建 Windows Package 并复核跨平台行为。
- **数据落库**：Recovery Job/Event 和必要的 Reversible Quarantine Record。
- **测试**：Crash Point、Orphan Classification、Large/Deep Fixture、Resource
  Exhaustion、Packaged Runtime、Desktop Flow、Original/Working Integrity。
- **验收**：自动化和 Prepared-data Desktop Acceptance 通过；External Distribution
  仍需 License Review 与 Signing。

### W9：V1 Release Qualification 与发布闭环（提案）

- **目标**：把已通过功能验收的 Workbench 转化为可明确发布或阻断的 V1 Candidate，
  不增加新业务能力。
- **输入**：W8 源码桌面人工验收结果、内部 `onedir` Package、SBOM、Audit、Notice、
  Benchmark 和 Build Inventory。
- **核心实现**：版本冻结、干净 Git 历史与 GitHub 仓库、可复现 Portable ZIP、
  GitHub Actions 校验、GitHub Releases、人工 License Review、受控 Code Signing、
  干净 Windows x64 主机矩阵、真实 RAR/7-Zip、最终 Package Desktop Acceptance 和
  Release/Blocked 判定。
- **数据落库**：默认不修改 Project SQLite 或 Migration；Release Evidence 保存在构建
  资产中。若必须改变 Schema，返回新的重大决策门。
- **测试**：无 7-Zip/标准位置 7-Zip、真实 RAR、无 Python 开发环境、Project 新建与
  W8 Project 副本重开、编辑/恢复/导出、Hash/签名验证和干净主机桌面流程。
- **验收**：D78–D91 全部批准；首次 Push 不含本地数据或 Secret；License、Signing、
  Clean-host、RAR、最终包人工验收全部通过；GitHub Release 资产与 Hash 一致，才能
  标记 V1 Release。否则保持 Internal RC。W9 不实施 V2 或应用内 Auto-update。

## English normative text

Historical Milestones 1-10 describe the evidence-oriented implementation and do
not authorize Workbench code changes. Each milestone below requires explicit
entry approval and must finish a runnable, testable data loop before the next.

## W0 - Product and architecture reset

**Goal**

Establish one non-conflicting V1 product scope, dual-tree domain model, state
machines, legacy boundary, and acceptance procedure.

**Input**

D17-B through D23-B and the instruction that old Projects need no compatibility.

**Core work**

- update the authoritative Project rules;
- record ADR-010;
- define Source Structure versus Workspace Tree;
- define snapshot, lazy materialization, edit refresh, and soft-delete behavior;
- mark old Milestones as historical.

**Persistence**

None. No schema or data is changed.

**Tests**

Documentation consistency checks and repository search for contradictory active
scope statements.

**Acceptance**

The owner can approve W1 without unresolved product semantics. No source code,
Migration, package, or UI has changed.

## W1 - Workbench domain and persistence foundation

**Goal**

Make the new model representable without implementing import or UI.

**Input**

Approved Workbench domain model and state machines.

**Core work**

- domain entities/value objects for ImportSession, OriginalSnapshot,
  OriginalArtifact, WorkspaceItem, WorkspacePlacement, and WorkingArtifact;
- invariants and transitions;
- Repository interfaces;
- decide clean schema baseline versus forward Alembic revision;
- reject unsupported old model versions clearly.

**Persistence**

New tables, constraints, indexes, append-only Event vocabulary, and one-Project
SQLite identity. No legacy row conversion.

**Tests**

Domain transition tests, relationship/cycle constraints, repository round trips,
transaction rollback, and clean-database migration.

**Acceptance**

A new empty Workbench Project can persist/reload all core objects. No filesystem
bytes are imported yet.

## W2 - Immutable snapshot import Application loop

**Goal**

Copy external files/folders into verified Project-owned Original storage through
a typed Application action.

**Input**

One or more absolute user-authorized paths.

**Core work**

- import preflight and containment checks;
- bounded streaming copy with staging and atomic publish;
- file/folder snapshot ownership;
- partial-success result contract;
- external input remains untouched.

**Persistence**

ImportSession, OriginalSnapshot, OriginalArtifact, Source roots, status changes,
fingerprints, and Events.

**Tests**

Files, folders, duplicate names, source removed after import, changed source
during copy, symlinks, unreadable files, resource limits, interruption, and
Original immutability.

**Acceptance**

After successful import, removing the external test input does not prevent PIG
from verifying its Project-owned snapshot.

## W3 - Folder and ZIP inspect/materialize split

**Goal**

Prove eager structure discovery and lazy terminal materialization with the
simplest Container backends.

**Input**

Snapshot-backed Folder and ZIP Sources, including nested ZIP.

**Core work**

- separate Handler inspection from target materialization;
- persist Source Structure without publishing all terminal Working Files;
- operation-scoped inspection cache for inner Containers;
- materialization recipe based on direct Source Relationships;
- initialize Workspace Items that mirror discovered structure.

**Persistence**

Source Nodes/Relationships, minimum origin bindings, Workspace Items/Placements,
processing results, and materialization state.

**Tests**

Nested paths, implicit folders, duplicate entries, traversal, ZIP bomb policy,
corrupt/encrypted ZIP, only-selected-file materialization, and restart.

**Acceptance**

A nested ZIP tree is visible while unselected terminal files have no Working
Artifact; selecting one materializes exactly that file.

## W4 - Email, 7z, and RAR complex Container coverage

**Goal**

Apply the W3 boundary consistently to the remaining V1 Containers.

**Input**

EML, MSG, 7z, and RAR snapshots and mixed nested chains.

**Core work**

- inspect/materialize adapters for EML/MSG/7z/RAR;
- preserve the approved 7-Zip trust/version boundary for RAR;
- bounded nested-Container cache;
- format-specific error mapping without Processor branching.

**Persistence**

The same Source/Workspace contracts as W3 plus backend identity metadata and
explicit unsupported/password/corruption results.

**Tests**

Mixed chains such as ZIP -> MSG/EML -> ZIP/7z -> Office/PDF, attachment name
collisions, malformed mail, encrypted content, absent/rejected 7-Zip, and limits.

**Acceptance**

Every supported Container uses the same processing framework and lazy terminal
materialization semantics.

## W5 - Mutable Workspace Tree actions

**Goal**

Allow safe project organization independent from Source Structure.

**Input**

Workspace Items initialized from discovered Sources plus newly added inputs.

**Core work**

- create ordinary Workspace folders;
- move/reorder Items;
- add snapshotted files/folders;
- soft-delete and restore;
- prohibit cycles, cross-Project moves, and Container write-back targets.

**Persistence**

Workspace Placement/lifecycle, prior restore placement, and structured Events.

**Tests**

Move subtree, root move, cycle rejection, invalid target, add, delete/restore,
restart persistence, concurrent action rejection, and Source facts unchanged.

**Acceptance**

The user can reorganize a Project and restart PIG without losing layout; Original
Snapshot and Source Structure hashes/relationships remain unchanged.

## W6 - Stable open and external edit reconciliation

**Goal**

Make the materialized Workspace a real editing surface.

**Input**

Virtual or materialized terminal Workspace Items.

**Core work**

- stable safe-suffix Working Artifact publication;
- controlled allowlist and OS open;
- reuse on subsequent Open;
- explicit and focus-triggered deterministic refresh;
- CLEAN/MODIFIED/MISSING/UNREADABLE outcomes;
- confirmed rematerialization/restore when it would replace current bytes.

**Persistence**

Baseline/current fingerprints, content state, last observation, Open and content
change Events.

**Tests**

Edit in place, return to baseline, missing file, unreadable path, Save-As
non-tracking boundary, repeated observations without duplicate Events, tampered
paths, and host open failure.

**Acceptance**

An Office/PDF/text test file can be opened, saved in place, detected as modified,
closed, and reopened with the edited bytes intact.

## W7 - PySide6 Workbench UI

**Goal**

Expose only the completed Workbench capabilities in one coherent desktop view.

**Input**

W2-W6 typed Application actions and queries.

**Core work**

- multi-path drag/drop import with progress/result summary;
- Workspace Tree as primary tree;
- move/add/create-folder/delete/restore interactions;
- virtual/materialized/modified/missing badges;
- Search and controlled double-click Open;
- explicit Refresh file state;
- optional Source Structure details without making Lineage the main screen.

**Persistence**

No UI-owned business state. Every change goes through Application contracts.

**Tests**

Qt interaction tests for drag/drop requests, action confirmations, busy-state
protection, tree persistence, error display, Open, refresh, and restart.

**Acceptance**

The standard desktop acceptance document can be executed without database or
filesystem intervention outside the application.

## W7.1 - Desktop-acceptance usability closure

**Goal**

Close the drop, accidental-save protection, Host filename, and delivery-output
gaps discovered during real W7 acceptance.

**Input**

The W7 source-desktop loop and D61-A through D64-A.

**Core work**

- central Workbench drop surface;
- current/previous Working slots with confirmed rollback;
- safe friendly Working filename;
- direct single-file and multi-file ZIP export.

**Persistence**

Two-role `working_revisions` slots plus version-capture, rollback, and export
Events.

**Tests**

Version rotation/rollback, Original immutability, friendly and duplicate names,
atomic export, path collisions, central drop, and UI multi-selection.

**Acceptance**

The user can proceed from import through external editing and accidental-save
recovery to a transferable export file.

## W7.2 - Project recognition, accidental-import undo, and folder delivery

**Goal**

Close the real office-workflow gaps in recognizable Project storage, undo of an
accidental selection within one multi-path drop, context-menu access, and whole
folder delivery.

**Input**

The completed W7.1 loop plus D65-A, narrowed D66-B, D67-A, and D68-A.

**Core work**

- `<selected-parent>/<project-name>/project.sqlite` for new Projects;
- impact preview and confirmed undo for one top-level `ImportSessionItem`;
- Workspace and Deleted Items context menus;
- ordinary-directory export for one ordinary Workspace folder.

**Persistence**

`PURGED` availability state for Snapshot, Source, Original Artifact, and
Workspace Item; Requested/Completed/Failed Events; and an advanced Project
revision. Import-capture identity remains historical.

**Tests**

Valid/colliding Project names, targeted undo of an accidental File beside a
Folder in one drop, unchanged external input, embedded-member rejection,
directory/empty-directory/current-Working-byte export, and Qt context entry.

**Acceptance**

The user can recognize Project storage, undo only an accidentally selected
top-level input, and deliver an organized Workspace folder in its current tree.

## W8 - Recovery, performance, and packaging reset

**Goal**

Qualify the writable Workbench for realistic project sizes and interruption.

**Input**

Completed W1-W7.2 loop.

**Core work**

- reconcile snapshot staging, inspection cache, and Working Artifact publication;
- protect modified Working Files from automatic replacement/quarantine;
- benchmark import, structure load, materialization, move, and refresh;
- rebuild Windows internal package and reevaluate cross-platform behavior.

**Persistence**

Recovery Jobs/Events and reversible quarantine records where required.

**Tests**

Crash points, orphan classification, large/deep fixtures, resource exhaustion,
packaged runtime, real desktop flow, and Original/Working integrity.

**Acceptance**

The complete Workbench flow passes automated and prepared-data desktop
acceptance. External distribution still requires license review and signing.

## W9 - V1 release qualification and closure (proposed)

**Goal**

Turn the functionally accepted Workbench into a V1 candidate with an explicit
release-or-block decision, without adding business capability.

**Input**

W8 source-desktop acceptance, the internal `onedir` package, SBOM, audit,
notices, benchmark, and build inventory.

**Core work**

Version freeze, clean Git history and GitHub repository, reproducible portable
ZIP, GitHub Actions checks, GitHub Releases, human license review, controlled
code signing, clean Windows x64 host matrix, real RAR/7-Zip qualification,
final-package desktop acceptance, and a release/blocked decision.

**Persistence**

No Project SQLite or migration change by default. Release evidence remains a
build asset. Any required schema change returns to a new major decision gate.

**Tests**

No-7-Zip and standard-location-7-Zip cases, real RAR, no Python development
environment, new Project and copied W8 Project reopen, edit/recovery/export,
hash/signature verification, and clean-host desktop flow.

**Acceptance**

V1 is marked released only after D78-D91 are approved, the first push is free of
local data and secrets, every license, signing, clean-host, RAR, and final-package
manual gate passes, and the GitHub Release assets match their hashes. Otherwise
it remains Internal RC. W9 implements neither V2 nor in-application auto-update.
