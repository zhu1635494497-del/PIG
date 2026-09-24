# ADR-018：Workbench W7.1 可用性闭环 / Workbench W7.1 Usability Closure

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-23 / Decision date: 2026-09-23
- 决策：D61-A、D62-A（当前与上一版本）、D63-A、D64-A / Decisions: D61-A, D62-A (current and previous only), D63-A, D64-A
- 范围：Workbench Milestone W7.1 / Scope: Workbench Milestone W7.1

## 中文规范正文

### 背景

W7 源码桌面验收确认四个直接影响工作效率的缺口：外部拖放实际集中在 Tree；Host
Application 看到内部 `content.*` 名称；误保存后只能回到 Original Baseline；Workspace
完成后缺少明确交付出口。W7.1 在不进入 W8 Recovery/Packaging 的前提下闭合这些缺口。

### 决策

1. **D61-A**：整个中央 Workbench 接受外部文件/文件夹拖入。Tree 上明确的 Folder
   仍是定向 Add Target；其他区域统一添加到 Project Root。内部 Tree Drag/Drop 仍只
   表示单项 Move/Reorder。
2. **D62-A（收紧）**：每个 Working Artifact 只向用户保留当前版本和一个上一版本；
   Original Baseline 独立永久保留。PIG 不声称收到 Host Application Save 回调，只在
   Focus Return、Explicit Refresh、Before Open 或 Before Export 时，根据稳定 Size/
   SHA-256 捕获“已检测版本”。连续多次保存但未触发检测时，中间版本不保证存在。
3. **D63-A**：稳定 Working Path 使用生成的 Workspace Item 目录和安全处理后的 Display
   Name 加可信 Suffix。物理同名由生成目录隔离；由于 OS 默认关联不能报告 Host 内部
   拒绝，PIG 对本会话中可能仍打开的同名文件做事前警告，不伪造事后成功状态。
4. **D64-A**：新增 typed `export_workspace_items` Action。一个 Terminal File 直接导出；
   多个 Terminal File 导出为 ZIP，并保留安全的 Workspace 相对路径。导出当前可读
   Working bytes；Virtual File 先受控物化。V1 不把 Export 解释为 Container write-back。

### 版本存储不变量

用户可见的版本只有当前和上一版本。实现允许一个与当前版本同 Hash 的内部校验副本，
用于在 Host Application 覆盖 Working File 后保存旧字节；它不是第三个用户版本。
版本轮换和回滚不得修改 Original Snapshot、Source Structure 或 Origin Binding。回滚
必须显式确认，并把被覆盖的当前版本交换为新的上一版本。

### 导出不变量

导出目标必须位于受管 Project 目录之外；覆盖必须确认；Symlink、Directory 和其他
非普通目标不得替换。导出前必须刷新已物化文件；`MISSING/UNREADABLE` 不得静默退回
Original。多文件导出路径冲突必须失败并明确报告，不得静默改名。

### 被取代的局部决定

本 ADR 仅取代 ADR-016 D52-A 中“不增加观察历史表/版本历史”的部分，以及原
`content.<suffix>` Working basename。它不引入 Watcher、无限版本、Diff/Merge、Host
插件或 Container write-back。ADR-016 的其余 Open、Refresh、Restore 和安全约束继续有效。

## English normative text

## Context

W7 source-desktop acceptance identified four direct usability gaps: external
drop was effectively concentrated on the Tree, host applications saw internal
`content.*` names, an accidental save could only return to the Original
Baseline, and a completed Workspace had no explicit delivery path. W7.1 closes
these gaps without entering W8 recovery or packaging.

## Decisions

1. **D61-A**: the entire central Workbench accepts external files and folders.
   A specific Folder under the Tree remains a targeted Add destination; drops
   elsewhere go to the Project Root. Internal Tree drag/drop remains a
   single-item Move/Reorder operation.
2. **D62-A (narrowed)**: each Working Artifact exposes only the current version
   and one previous version. The Original Baseline remains independently and
   permanently available. PIG does not claim a Host Application save callback;
   it captures a detected version from stable Size/SHA-256 during focus return,
   explicit refresh, before open, or before export. Intermediate saves made
   without a detection trigger are not guaranteed.
3. **D63-A**: a stable Working Path uses the generated Workspace Item directory
   plus a sanitized Display Name and trusted suffix. Generated directories
   isolate physical duplicate names. Because default OS association cannot
   report an internal host rejection, PIG warns before handing off another same-
   name file in the current session and does not invent a successful outcome.
4. **D64-A**: add a typed `export_workspace_items` Action. One Terminal File is
   exported directly; multiple Terminal Files become a ZIP preserving safe
   Workspace-relative paths. Export uses current readable Working bytes and
   materializes a Virtual File under control first. Export is not Container
   write-back.

## Version-storage invariants

Only current and previous are user-visible versions. The implementation may
keep one internal checkpoint with the same hash as current so that old bytes
survive an in-place Host overwrite; that checkpoint is not a third user
version. Rotation and rollback never change Original Snapshot, Source Structure,
or Origin Binding. Rollback requires confirmation and swaps the replaced current
version into the new previous slot.

## Export invariants

The export destination is outside the managed Project directory. Replacement
requires confirmation, and symlink, directory, or other non-regular targets are
never replaced. Materialized files are refreshed before export;
`MISSING/UNREADABLE` never silently falls back to Original. Multi-file path
collisions fail explicitly and are never silently renamed.

## Locally superseded decisions

This ADR supersedes only the ADR-016 D52-A exclusion of an observation/history
table and the former `content.<suffix>` Working basename. It adds no watcher,
unbounded history, Diff/Merge, Host plugin, or Container write-back. All other
ADR-016 Open, Refresh, Restore, and safety constraints remain active.
