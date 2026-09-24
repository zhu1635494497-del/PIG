# PIG V1 当前规划索引 / PIG V1 Active Planning Index

- 当前日期：2026-09-24 / Date: 2026-09-24
- 当前阶段：Workbench W9 发布资格实施 / Current phase: Workbench W9 release-qualification implementation
- 代码授权：W1–W9；D78–D91 已批准，正式外发仍受人工 Gate 约束 / Code authorization: W1-W9; D78-D91 approved, with official distribution still gated by human review

## 当前规范优先级 / Active authority order

1. `PIG Project Rules.md`
2. `docs/DOCUMENTATION-STYLE.md`（仅约束文档格式 / documentation format only）
3. `docs/decisions/ADR-010-v1-project-file-workbench-reset.md`
4. `docs/application/PIG-V1-workbench-scope.md`
5. `docs/domain/PIG-V1-workbench-domain-model.md`
6. `docs/domain/PIG-V1-workbench-state-machines.md`
7. `docs/application/PIG-V1-workbench-milestones.md`
8. `docs/application/PIG-V1-desktop-acceptance.md`
9. `docs/decisions/ADR-011-workbench-clean-schema-baseline.md`
10. `docs/application/PIG-V1-workbench-W1.md`
11. `docs/decisions/ADR-012-workbench-snapshot-import-boundary.md`
12. `docs/application/PIG-V1-workbench-W2.md`
13. `docs/decisions/ADR-013-workbench-structure-materialization-boundary.md`
14. `docs/application/PIG-V1-workbench-W3.md`
15. `docs/decisions/ADR-014-workbench-complex-container-boundary.md`
16. `docs/application/PIG-V1-workbench-W4.md`
17. `docs/decisions/ADR-015-workbench-mutable-tree-actions.md`
18. `docs/application/PIG-V1-workbench-W5.md`
19. `docs/decisions/ADR-016-workbench-stable-open-edit-reconciliation.md`
20. `docs/application/PIG-V1-workbench-W6.md`
21. `docs/decisions/ADR-017-workbench-desktop-ui-boundary.md`
22. `docs/application/PIG-V1-workbench-W7.md`
23. `docs/decisions/ADR-018-workbench-usability-closure.md`
24. `docs/application/PIG-V1-workbench-W7.1.md`
25. `docs/decisions/ADR-019-workbench-project-layout-import-undo-folder-export.md`
26. `docs/application/PIG-V1-workbench-W7.2.md`
27. `docs/decisions/ADR-020-workbench-recovery-performance-packaging-reset.md`
28. `docs/application/PIG-V1-workbench-W8.md`
29. `docs/decisions/ADR-021-v1-release-qualification.md`
30. `docs/application/PIG-V1-workbench-W9.md`

`docs/decisions/ADR-021-v1-release-qualification.md` 已接受，D78–D91 已批准。W9 可以
实施本地 Git、公开仓库准备、CI 和 Unsigned Internal RC；首次公开 Push 仍需精确文件
清单与最终确认，正式 V1 Release 仍需完成 License、Signing、Clean-host、真实 RAR 和
最终 Package Desktop Acceptance。

`docs/decisions/ADR-021-v1-release-qualification.md` is accepted and D78-D91 are
approved. W9 may implement local Git, public-repository preparation, CI, and an
unsigned Internal RC. The exact inventory and final confirmation remain required
before the first public push, and an official V1 Release still requires license,
signing, clean-host, real-RAR, and final-package desktop gates.

`ADR-020` 已接受。W8 自动实现、当前 Windows 主机机器验收和源码桌面人工验收已完成；
最终包与干净 Windows 主机发布资格验证转入 W9。

`ADR-020` is accepted. W8 automated implementation, current-host machine
acceptance, and source-desktop manual acceptance are complete. Final-package and
clean-Windows-host release qualification move to W9.

如果历史文档与上述当前文档冲突，以当前 Workbench 文档为准。

If a historical document conflicts with an active document above, the active
Workbench document controls.

## 历史实现记录 / Historical implementation record

ADR-001 至 ADR-009、原领域/持久化规范以及 Milestone 3–10 描述当前已经实现的
证据导向系统。它们仍可用于代码考古和识别可复用组件，但不定义目标 V1
Workbench 产品。

ADR-001 through ADR-009, the original domain/persistence specifications, and
Milestones 3-10 explain the currently implemented evidence-oriented application.
They remain useful for code archaeology and identifying reusable components, but
they do not define the target V1 Workbench product.

## 已批准决策 / Approved decisions

- D17-B：复杂项目文件 Workbench 优先；
  complex project file Workbench focus.
- D18-B：项目内不可变 Original Snapshot；
  immutable Project-owned Original Snapshot.
- D19-B：不可变 Source Structure 加可变 Workspace Tree；
  immutable Source Structure plus mutable Workspace Tree.
- D20-B：主动结构检查加终端文件延迟物化；
  eager structure inspection plus lazy terminal materialization.
- D21-B：稳定可编辑 Working File 加确定性刷新；
  stable externally editable Working File plus deterministic refresh.
- D22-B：Workspace Overlay，不回写 Container；
  Workspace overlay with no Container write-back.
- D23-B：可恢复的 Workspace 软删除；
  reversible Workspace soft delete.
- D25-B：新 `0001_workbench` 干净 Schema 基线；
  new clean `0001_workbench` schema baseline.
- D26-A：生成标识 Original Layout 加显式 Snapshot Entry Tree；
  generated-identity Original layout plus explicit Snapshot Entry tree.
- D27-B：Import Session 跨 W2–W3，W2 成功停在 `INSPECTING`；
  Import Session spans W2-W3 and successful W2 capture ends at `INSPECTING`.
- D28-A：W2 创建 Snapshot-backed Source 与 Root Node；
  W2 creates the snapshot-backed Source and root Node.
- D29-A：每个顶层 Snapshot 严格完整，Sibling 可继续；
  strict completeness per top-level snapshot while siblings continue.
- D30-B：Workbench-native `inspect/materialize` Handler Contract；
  Workbench-native `inspect/materialize` Handler contract.
- D31-A：Direct Relationship 使用显式 typed Entry Locator；
  explicit typed Entry Locators on direct relationships.
- D32-A：Source Structure 完整投影为初始 Workspace Tree；
  full Source Structure projection into the initial Workspace Tree.
- D33-A：生成标识 Working Layout 与可信 Suffix；
  generated-identity Working layout with trusted suffixes.
- D34-A：Operation-scoped Inspection Cache 与 Recipe Replay；
  operation-scoped inspection cache and recipe replay.
- D35-A：独立 typed Inspection 与 Materialization Action；
  separate typed inspection and materialization actions.
- D36-A：`0003_structure_workspace` 前向 Migration；
  forward `0003_structure_workspace` migration.
- D37-A：单表显式 typed Complex-container Locator；
  explicit typed complex-container locators in one table.
- D38-A：Backend Identity 持久化到 `ProcessingAttempt`；
  backend identity persisted on `ProcessingAttempt`.
- D39-A：可用字节使用 Archive Signature-first Detection；
  archive signature-first detection when bytes are available.
- D40-A：`0004_complex_containers` 前向 Migration；
  forward `0004_complex_containers` migration.
- D41-A：Active Sibling 连续 Ordinal 与原子 Move/Reorder；
  dense active-sibling ordinals and atomic move/reorder.
- D42-A：Project 级 `workspace_revision` Optimistic Concurrency；
  Project-scoped `workspace_revision` optimistic concurrency.
- D43-A：根 Tombstone 与后代有效隐藏；
  root tombstone with effective descendant hiding.
- D44-A：Import Session 持久化定向 Add Target；
  targeted Add destination persisted on Import Session.
- D45-A：Logical Segment Name，允许同级重名；
  logical-segment names with same-parent duplicates allowed.
- D46-A：`0005_workspace_actions` 前向 Migration；
  forward `0005_workspace_actions` migration.
- D47-A：统一 Open Action，Virtual 先物化、Materialized 先刷新；
  unified Open action with materialization for Virtual and refresh for Materialized.
- D48-A：`CHECKING` 仅为操作态，直接持久化最终 Content Status；
  operation-only `CHECKING` with direct final content-status persistence.
- D49-A：格式 Allowlist 加 OS 默认 File Association；
  format allowlist plus host default file association.
- D50-A：显式 Restore、覆盖确认与非普通路径永不替换；
  explicit restore, overwrite confirmation, and no replacement of non-regular paths.
- D51-A：显式 Refresh Reason、变化 Event 去重、每次 Open Attempt 留痕；
  explicit refresh reasons, deduplicated change Events, and every Open attempt recorded.
- D52-A：复用现有 Working 字段、受限 Hash、不增加 `0006`；
  reuse existing Working fields, bounded hashing, and no `0006` migration.
- D53-A：单窗口 Workspace-first Workbench；
  one-window Workspace-first Workbench.
- D54-A：typed Workspace Read Model Query；
  typed Workspace read-model queries.
- D55-A：多路径 Add 自动 Snapshot/Inspect；
  multi-path Add with automatic snapshot/inspection.
- D56-A：后端权威的 Tree Drag/Drop Move/Reorder；
  backend-authoritative tree drag/drop move/reorder.
- D57-A：独立 Deleted Items Restore 入口；
  separate Deleted Items restore surface.
- D58-A：W6 Open/Refresh/Restore 桌面接入与选中项 Focus Refresh；
  desktop W6 open/refresh/restore with selected-item focus refresh.
- D59-A：Workspace Search 与结果直接打开；
  Workspace Search with direct result Open.
- D60-A：单后台 Action Busy Policy，不增加 Migration；
  single-background-action busy policy with no migration.
- D61-A：中央 Workbench 全区域外部拖入，非 Tree 定向目标进入 Project Root；
  central Workbench external drop surface with non-Tree drops targeting Project Root.
- D62-A：只保留当前与上一 Working 版本，Original Baseline 独立保留；
  current and one previous Working version with a separate Original Baseline.
- D63-A：生成 Item 目录中的安全友好 Working 文件名与同名事前警告；
  safe friendly Working filename under a generated Item directory with pre-handoff duplicate warning.
- D64-A：单文件直接导出，多文件按 Workspace 相对路径导出 ZIP；
  direct single-file export and multi-file ZIP export using Workspace-relative paths.
- D65-A：新 Project 使用所选父目录下的合法 Project 名称目录；
  new Projects use a valid Project-name directory under the selected parent.
- D66-B（收紧）：按顶层 Import Item 撤销误导入，不建设任意节点硬删除；
  undo an accidental top-level Import Item without arbitrary-node hard deletion.
- D67-A：右键上下文菜单与 Toolbar 并存；
  context menus coexist with the toolbar.
- D68-A：单个 Workspace 文件夹导出为保留结构的普通目录；
  one Workspace folder exports as an ordinary structure-preserving directory.

旧 Project 兼容性明确不在范围内。由于产品负责人指示无需考虑 D24，因此这里不
记录任何 D24 选项。

Existing Project compatibility is explicitly outside scope. This is not recorded
as a D24 option because the owner instructed that D24 need not be considered.

## 当前授权门 / Current authorization gate

产品负责人已确认 W8 源码桌面人工验收通过，并批准 W9 D78-A 至 D91-A。W9 当前实施
公开源码仓库和 Release Qualification；正式签名外发必须等待全部人工 Gate。W9 不实施
V2。

The owner confirmed W8 source-desktop manual acceptance and approved W9 D78-A
through D91-A. W9 now implements the public-source repository and release
qualification. Official signed distribution waits for every human gate. W9 does
not implement V2.
