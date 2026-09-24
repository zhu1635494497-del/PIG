# PIG 仓库指令 / PIG Repository Instructions

`PIG Project Rules.md` 是本仓库具有最高约束力的项目级长期规则。

`PIG Project Rules.md` is the authoritative, project-wide, long-term rule set
for this repository.

在规划、设计、编码、评审或测试任何非 trivial 变更前：

Before planning, designing, coding, reviewing, or testing any non-trivial change:

1. 使用 UTF-8 完整读取 `PIG Project Rules.md`。
   Read `PIG Project Rules.md` in full using UTF-8.
2. 将它视为持续约束，而不是某次任务的背景材料。
   Treat it as a persistent constraint, not as one task's background material.
3. 实现前说明 Domain、Flow、State、Lineage、Log、Permission、Tool、AI、
   Automation 和 UI 影响。
   State the Domain, Flow, State, Lineage, Log, Permission, Tool, AI,
   Automation, and UI impact before implementation.
4. 遵守 `ADR-001` 和 V1 Workbench 重置 `ADR-010`；使用
   `docs/PIG-V1-planning-index.md` 判断当前文档和历史文档。
   Respect `ADR-001` and the V1 Workbench reset `ADR-010`; use
   `docs/PIG-V1-planning-index.md` to resolve active versus historical documents.
5. 未经用户明确批准不得越过当前 Milestone。Workbench W9 的 D78–D91 已批准；允许
   本地 Git、公开仓库准备、CI 与 Unsigned Internal RC。首次公开 Push 仍需精确文件
   清单和最终确认；正式 V1 Release 仍需全部人工 Gate，W9 不实施 V2。
   Do not advance beyond the explicitly authorized milestone. Workbench W9
   D78-D91 are approved, allowing local Git, public-repository preparation, CI,
   and unsigned Internal RCs. The first public push still requires an exact file
   inventory and final confirmation; every human gate remains mandatory for an
   official V1 Release, and W9 does not implement V2.
6. 完成有意义的工作后，按照 `PIG Project Rules.md` 第十五节汇报。
   After meaningful work, report the completion items required by section 15 of
   `PIG Project Rules.md`.
7. PIG 自有 Markdown 遵循 `docs/DOCUMENTATION-STYLE.md` 的双语规范。
   First-party PIG Markdown follows the bilingual standard in
   `docs/DOCUMENTATION-STYLE.md`.

如果请求与项目规则或已批准 ADR 冲突，必须指出冲突并请求明确决策，不得静默覆盖。

If a request conflicts with the project rules or an approved architecture
decision, identify the conflict and ask for an explicit decision instead of
silently overriding it.
