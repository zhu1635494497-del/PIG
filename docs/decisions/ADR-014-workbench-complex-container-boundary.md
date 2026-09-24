# ADR-014：Workbench 复杂 Container 边界 / Workbench Complex Container Boundary

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-22 / Decision date: 2026-09-22
- 决策：D37-A、D38-A、D39-A、D40-A / Decisions: D37-A, D38-A, D39-A, D40-A
- 范围：Workbench Milestone W4 / Scope: Workbench Milestone W4

## 中文规范正文

### 背景

W3 已证明 Folder/ZIP 的主动结构发现、Operation-scoped Cache 和单目标延迟物化。
W4 必须让 EML、MSG、7z 和 RAR 遵守同一边界，且不得重新启用历史 Evidence
`NodeExecutor`、批量 Extracted Artifact 或按格式分支的 Application Processor。

ADR-004 与 ADR-005 的 Backend 决策继续有效：EML 使用 Python `email`，MSG 使用
`extract-msg`，7z 使用 `py7zr`，RAR 使用显式配置并受信任校验的系统 7-Zip。

### 决策

1. **D37-A**：`SourceEntryLocator` 保持单表一对一绑定 Direct Relationship，并扩展
   `EML_PART`、`MSG_ATTACHMENT`、`SEVEN_Z_MEMBER` 与 `RAR_MEMBER`。Container
   Locator 使用 `member_ordinal`、`expected_name` 和 `member_role`；不得保存 Parser
   Token、任意 JSON 或临时路径。
2. **D38-A**：Backend Identity 属于 `ProcessingAttempt`。Attempt 保存 Handler Name/
   Version、Backend Name/Version 和可选 SHA-256。RAR 保存受信任 Executable 的版本与
   Hash，但不保存本机路径。Node 当前状态、Attempt 历史和 Event 各自保持独立。
3. **D39-A**：当字节已安全可用时，ZIP、7z、RAR 使用确定性 Signature-first
   Detection；Office Open XML 的可信扩展优先，避免误判为普通 ZIP；MSG/EML 由扩展
   选择 Handler 后再由 Parser 验证。对于尚未物化的 Terminal Member，不得为了嗅探
   签名而违反 Lazy Materialization。
4. **D40-A**：Schema 使用前向 `0004_complex_containers` Migration，扩展 Locator
   Constraint 和 Attempt Backend 字段，同时保持从干净数据库受控升级。

### 统一执行边界

ZIP、EML、MSG、7z 和 RAR 注册到同一个 Workbench Handler Registry。Application 只
执行 Detect、Resolve、Inspect、Persist、Queue 和 Recipe Replay。Format Adapter 负责
Parser/Backend 细节与错误映射。Archive 恢复安全的显式/隐式目录；Email 只投影附件和
嵌套消息，不把正文合成为文件。

结构检查只把内层 Container 物化到 `.inspection/<operation-id>/...`，操作结束即清理。
Terminal 只保存 Source Node、Workspace Item 与 Locator；明确 Materialize Action 才
产生稳定 Working Artifact。

### 结构化结果

- 损坏邮件或档案：`CORRUPTED / CORRUPTED_CONTAINER`；
- 密码档案：`PASSWORD_REQUIRED`，不收集密码；
- 不支持的格式能力：`UNSUPPORTED / UNSUPPORTED_FEATURE`；
- 7-Zip 缺失：`UNSUPPORTED / DEPENDENCY_UNAVAILABLE`；
- 7-Zip 版本拒绝：`UNSUPPORTED / DEPENDENCY_VERSION_UNSUPPORTED`；
- 外部进程、展开量、单文件、数量或 Ratio 超限：`LIMIT_EXCEEDED`；
- Traversal、Symbolic Link 或 Remote Reference：`SECURITY_BLOCKED`。

### 明确不做

W4 不实现邮件正文文件、密码输入、Archive/Email 回写、Workspace Move/Add/Delete、
OS Open、外部编辑刷新、UI、AI、Automation 或 MCP。

## English normative text

## Context

W3 proved eager Folder/ZIP structure discovery, operation-scoped cache, and
single-target lazy materialization. W4 applies the same boundary to EML, MSG,
7z, and RAR without reactivating the historical Evidence `NodeExecutor`, bulk
Extracted Artifacts, or format branches in the Application processor.

ADR-004 and ADR-005 remain authoritative: EML uses Python `email`, MSG uses
`extract-msg`, 7z uses `py7zr`, and RAR uses an explicitly configured and
validated system 7-Zip executable.

## Decisions

1. **D37-A**: `SourceEntryLocator` remains one table bound one-to-one to a direct
   Relationship and adds `EML_PART`, `MSG_ATTACHMENT`, `SEVEN_Z_MEMBER`, and
   `RAR_MEMBER`. Container locators use `member_ordinal`, `expected_name`, and
   `member_role`; parser tokens, arbitrary JSON, and temporary paths are
   prohibited.
2. **D38-A**: backend identity belongs to `ProcessingAttempt`. An Attempt stores
   Handler name/version, backend name/version, and optional SHA-256. RAR records
   the trusted executable version and hash but not its local path. Current Node
   state, Attempt history, and Events remain distinct.
3. **D39-A**: ZIP, 7z, and RAR use deterministic signature-first detection when
   bytes are safely available. Trusted Office Open XML extensions take priority
   over their ZIP signature. MSG/EML select a Handler by extension and are then
   validated by the parser. PIG does not materialize an otherwise terminal
   member merely to sniff its signature because that would violate lazy
   materialization.
4. **D40-A**: schema evolution uses forward revision
   `0004_complex_containers`, extending Locator constraints and Attempt backend
   fields while preserving controlled clean-database migration.

## Unified execution boundary

ZIP, EML, MSG, 7z, and RAR register in one Workbench Handler Registry. The
Application only detects, resolves, inspects, persists, queues, and replays a
recipe. Format adapters own parser/backend mechanics and error mapping. Archives
restore safe explicit/implicit directories. Email projects attachments and
embedded messages only; it does not synthesize body files.

Inspection materializes only nested Containers into
`.inspection/<operation-id>/...` and removes that cache when the operation ends.
A terminal member persists only Source Node, Workspace Item, and Locator facts
until an explicit Materialize action publishes its stable Working Artifact.

## Structured outcomes

- malformed mail/archive: `CORRUPTED / CORRUPTED_CONTAINER`;
- encrypted archive: `PASSWORD_REQUIRED`, with no password workflow;
- unsupported format capability: `UNSUPPORTED / UNSUPPORTED_FEATURE`;
- missing 7-Zip: `UNSUPPORTED / DEPENDENCY_UNAVAILABLE`;
- rejected 7-Zip version: `UNSUPPORTED / DEPENDENCY_VERSION_UNSUPPORTED`;
- process, expanded-byte, single-file, count, or ratio limit:
  `LIMIT_EXCEEDED`;
- traversal, symbolic link, or remote reference: `SECURITY_BLOCKED`.

## Explicit exclusions

W4 does not add synthesized email-body files, password input, archive/email
write-back, Workspace move/add/delete, OS open, external-edit refresh, UI, AI,
Automation, or MCP.
