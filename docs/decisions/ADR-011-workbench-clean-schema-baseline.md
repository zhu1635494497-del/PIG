# ADR-011：Workbench 干净 Schema 基线 / Workbench Clean Schema Baseline

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-21 / Decision date: 2026-09-21
- 决策：D25-B / Decision: D25-B
- 范围：Workbench Milestone W1 / Scope: Workbench Milestone W1
- 取代：旧 `0001`–`0005` Migration 链 / Supersedes: legacy `0001`–`0005` migration chain

## 中文规范正文

### 背景

产品负责人已明确旧 Project 不在兼容范围。现有 `0001`–`0005` Migration 链服务于
证据导向模型，其中 External Reference、Extracted Artifact 和临时 Open Handoff
语义已经被 ADR-010 取代。

### 决策

采用 D25-B：Workbench 使用单一的新 Alembic 基线 `0001_workbench`。旧 Revision
不参与新数据库升级链，也不迁移旧 Row。

新 Project 的 `model_version` 固定为 `workbench-v1`。应用读取其他版本时必须返回
`UNSUPPORTED_PROJECT_MODEL_VERSION`，不得猜测、转换或混合读取。

基线保留仍有价值的 Source Node、Source Relationship、Queue Processing 和
Append-only Event 内部结构，同时新增：

- `import_sessions`
- `original_snapshots`
- `original_artifacts`
- `workspace_items`
- `workspace_placements`
- `working_artifacts`

旧 `artifacts` 表只服务尚未重构的历史 Source Processing 代码，不代表新的
Original Artifact 或 Working Artifact。新功能不得向该表写入这两种新语义。

### 后果

- 新数据库从一条可审查基线创建；
- 旧 Project 不可直接打开；
- 不建设数据转换、双写或旧版只读模式；
- 历史 Milestone 3–10 Acceptance Tests 保留但从当前默认验收中隔离；
- W2 必须通过新的 Snapshot Import Action 写入 Workbench 表，不得恢复 External
  Reference Import。

## English normative text

## Context

The product owner explicitly excluded old Projects from compatibility scope. The
existing `0001` through `0005` migration chain served the evidence-oriented
model whose external-reference, extracted-artifact, and temporary open-handoff
semantics were superseded by ADR-010.

## Decision

D25-B is selected. Workbench uses one new Alembic baseline,
`0001_workbench`. Legacy revisions are not part of the new database upgrade
chain, and no legacy rows are converted.

Every new Project has `model_version = "workbench-v1"`. Reading any other model
version must fail with `UNSUPPORTED_PROJECT_MODEL_VERSION`; the application must
not guess, convert, or mix model generations.

The baseline retains useful internal Source Node, Source Relationship, queue
processing, and append-only Event structures. It adds:

- `import_sessions`;
- `original_snapshots`;
- `original_artifacts`;
- `workspace_items`;
- `workspace_placements`;
- `working_artifacts`.

The legacy `artifacts` table exists only for historical Source Processing code
that has not yet been refactored. It does not represent the new Original
Artifact or Working Artifact, and new functionality must not write those new
semantics into it.

## Consequences

- New databases start from one reviewable baseline.
- Old Projects cannot be opened directly.
- No conversion, dual-write, or legacy read-only mode is built.
- Historical Milestone 3-10 acceptance tests remain available but are isolated
  from current default acceptance.
- W2 must write the Workbench tables through a new snapshot-import action and
  must not restore external-reference ingestion.
