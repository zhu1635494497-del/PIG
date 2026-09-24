# PIG V1 历史领域测试场景 / Historical Domain Test Scenarios

> Historical evidence-oriented scenarios. New implementation acceptance follows
> ADR-010 and `PIG-V1-desktop-acceptance.md`.

> 中文摘要：本文记录旧 V1 的 Source、Node、Lineage、Security、Retry、Archive 和
> Error 场景。它们继续作为现有代码回归资料；新产品验收使用 Workbench Acceptance。

- 状态：历史证据导向场景 / Status: Historical evidence-oriented scenarios
- 版本：0.2 / Version: 0.2
- 约束规则：`PIG Project Rules.md` / Governing rules: `PIG Project Rules.md`

These scenarios define expected domain behavior before implementation. They are not filesystem fixtures or executable tests yet. Later milestones should translate them into unit, repository, integration, security, and cross-platform tests without changing their business meaning.

## 1. Canonical example model

Input evidence structure:

```text
采购资料.zip
└── 邮件资料/
    └── 供应商报价.msg
        └── 报价附件.zip
            └── 最终报价.xlsx
```

Expected facts:

- 1 Project
- 1 Source referencing `采购资料.zip`
- 5 Nodes: 4 byte-bearing Nodes plus the persisted structural Folder `邮件资料`
- 4 direct Relationships
- 5 distance-0 Lineage records
- 4 distance-1 Lineage records
- 15 total Lineage records across distances 0 through 4
- the leaf Source ID equals the root Source ID
- the leaf LogicalPath preserves every container boundary
- the XLSX Node is a Terminal File and is not expanded as ZIP

Expected leaf path:

```text
/采购资料.zip!/邮件资料/供应商报价.msg!/报价附件.zip!/最终报价.xlsx
```

Expected direct edges:

| Parent | Child | Relationship |
|---|---|---|
| 采购资料.zip | 邮件资料 | `ARCHIVE_ENTRY` |
| 邮件资料 | 供应商报价.msg | `FOLDER_CONTAINS` |
| 供应商报价.msg | 报价附件.zip | `EMAIL_ATTACHMENT` |
| 报价附件.zip | 最终报价.xlsx | `ARCHIVE_ENTRY` |

## 2. Project and Source scenarios

### S01 — Register an external file Source

Given a new Project and an accessible external file

When the user registers that file

Then PIG creates one Source in `REGISTERED`, creates or schedules creation of one root Node, records the external locator without modifying the file, and emits `SOURCE_REGISTERED`.

### S02 — Same path imported twice

Given an external path already registered as Source A

When the user explicitly imports the same path again

Then PIG creates Source B with a different identity, and Source A's facts remain unchanged.

### S03 — Referenced Source disappears

Given a Source with an accepted fingerprint

When verification cannot find its external bytes

Then Source becomes `MISSING`, the requested Node operation results in `SOURCE_MISSING`, no historical facts are deleted, and structured events identify the Source and operation.

### S04 — Referenced Source changes

Given a Source whose accepted SHA-256 is H1

When the same locator now resolves to bytes with SHA-256 H2

Then Source becomes `CHANGED`, the operation results in `SOURCE_CHANGED`, H1 is not overwritten, and the H2 bytes require a new Source import.

### S05 — Exact Source bytes are restored

Given a Source in `CHANGED` or `MISSING`

When the original bytes matching the accepted fingerprint become available and verification runs

Then Source may return to `AVAILABLE`, with a new verification event and unchanged identity.

## 3. Node and format scenarios

### S06 — Unknown file is cataloged successfully

Given a readable file whose format is not recognized

When detection completes

Then its format is `UNKNOWN`, kind is `FILE`, status is `SUCCESS`, and no Container Handler is required.

### S07 — OOXML is not treated as generic ZIP

Given valid XLSX, DOCX, and PPTX files

When detection evaluates their ZIP-based signatures

Then each is classified as its Office format, remains a Terminal File in V1, and produces no archive-entry children.

### S08 — Empty Container succeeds

Given a valid empty folder or archive

When processing completes within policy

Then the Container has zero children and status `SUCCESS`.

### S09 — Recognized Container has no capability

Given a structurally recognized Container for which no supported Handler is available

When processing is attempted

Then the Node becomes `UNSUPPORTED`, the Attempt completes as an expected outcome, and the Project may become `READY_WITH_WARNINGS`.

## 4. Relationship and lineage scenarios

### S10 — Register one child

Given parent P with self and ancestor Lineage records

When child C is accepted

Then exactly one direct Relationship is created, C receives a self record, and every ancestor of P becomes an ancestor of C at distance plus one.

### S11 — Retry does not duplicate a child

Given parent P already has a child with discovery key K

When P is retried and produces K again

Then the existing child occurrence is reused or reconciled, no duplicate structural edge is created, and the retry has a distinct Attempt history.

### S12 — Duplicate archive names remain distinct

Given an archive containing two entries named `报价.xlsx` at different entry ordinals

When both are accepted

Then two Nodes exist with different discovery keys and identities, neither Artifact overwrites the other, and UI display disambiguation does not alter original names.

### S13 — Cross-project relationship rejected

Given Node A in Project 1 and Node B in Project 2

When a relationship from A to B is requested

Then the domain rejects it and records no relationship or lineage.

### S14 — Structural cycle rejected

Given A is an ancestor of B

When a relationship making B the parent of A is requested

Then the domain rejects the cycle and preserves the existing graph.

### S15 — Lineage inconsistency is detectable

Given direct Relationships and Lineage closure do not agree

When consistency validation runs

Then direct Relationships are treated as canonical, an integrity event is required, and closure repair is specified without rewriting Node identities.

## 5. State and event scenarios

### S16 — Normal Node processing

Given a Node in `DISCOVERED`

When it is queued, started, and successfully cataloged

Then its states are `DISCOVERED -> PENDING -> PROCESSING -> SUCCESS`, and every transition has a corresponding immutable event.

### S17 — Password-protected archive

Given an encrypted archive or entry

When encryption is detected

Then Node becomes `PASSWORD_REQUIRED`, no password is requested or stored, an event records the condition as expected and non-destructive, and automatic password retries do not occur.

### S18 — Corrupted archive

Given an archive whose structure is corrupt

When its Handler attempts inspection

Then Node becomes `CORRUPTED`, the error records Handler, stage, code, safe message, time, and retryability, and sibling Nodes remain intact.

### S19 — Unexpected exception

Given a Node in `PROCESSING`

When an unexpected implementation exception escapes normal format handling

Then Attempt becomes `FAILED`, Node becomes `FAILED`, a Processing Event records a diagnostic reference, and the stack trace exists only in Debug Log.

### S20 — Interrupted work

Given a Job and Attempt are `RUNNING`

When the process ends before completion

Then recovery marks the execution `INTERRUPTED`, does not claim domain failure, and preserves enough state for a later resume or retry.

### S21 — Retry preserves history

Given a Node previously failed in Attempt 1

When the user requests a retry

Then Attempt 2 is created, Attempt 1 and all its events remain immutable, and Node follows an allowed retry transition through `PENDING`.

## 6. Security scenarios

### S22 — Archive path traversal

Given an archive entry named `../../outside.txt`

When the entry is evaluated

Then it is never written, a safely represented evidence Node may be recorded as `SECURITY_BLOCKED`, and the event uses a stable path-traversal error code.

### S23 — Absolute and drive-qualified archive paths

Given entries such as `/etc/passwd`, `C:\\Windows\\x`, or a device path

When they are evaluated on any supported platform

Then none can become a workspace PhysicalLocator and all are blocked consistently.

### S24 — Symbolic link in a Source folder

Given a symbolic link under a registered folder Source

When discovery reaches it

Then PIG does not follow it, records the blocked/skipped observation when safe, and does not read the target.

### S25 — Symbolic-link archive entry

Given an archive represents an entry as a symbolic link

When the entry is inspected

Then extraction of the link target is blocked independent of its apparent destination.

### S26 — Single-file limit

Given an entry whose actual output exceeds the configured single-file limit

When bytes are streamed

Then writing stops, partial staging bytes do not become a valid Artifact, Node records `LIMIT_EXCEEDED`, and already committed siblings remain valid.

### S27 — Total expanded-size limit

Given many individually valid entries whose observed total exceeds the Job policy

When the budget is exhausted

Then no further bytes are accepted, affected Nodes record `LIMIT_EXCEEDED` or `SKIPPED` according to the later processing contract, and the Job is not reported as full success.

### S28 — Excessive depth

Given nested Containers deeper than the policy limit

When the next child would exceed maximum depth

Then the child is not processed recursively, the limit outcome is recorded, and no call-stack recursion is required.

### S29 — Open allowed file

Given a verified PDF Artifact with an approved locator and format

When Open File is requested

Then backend policy authorizes the request, current Artifact bytes are verified,
the verified absolute regular-file path is handed to the OS association, and a
correlated `FILE_OPENED` Event is recorded.

### S30 — Open unknown or executable file

Given an Unknown, executable, script, or shortcut Artifact

When Open File is requested

Then backend policy denies direct opening regardless of UI state and records the denial.

### S31 — Source changes before open

Given an externally referenced allowed document that changed after import

When Open File is requested

Then revalidation fails with `SOURCE_FINGERPRINT_MISMATCH`, Source becomes
`CHANGED`, Artifact becomes `MISMATCH`, no OS handoff occurs, and the accepted
fingerprint remains unchanged.

### S31a — Host file association rejects handoff

Given an allowed file passes current integrity verification

When the platform association API rejects the handoff

Then the operation returns `OPEN_HANDOFF_FAILED`, records `FILE_OPEN_FAILED`,
does not misreport `FILE_OPENED`, and keeps the successful integrity result.

## 7. Cross-platform path scenarios

### S32 — Logical path is stable across platforms

Given equivalent evidence structures processed on Windows, macOS, and Linux

When LogicalPaths are generated

Then they use the same `/` and `!/` semantics without drive letters or platform separators.

### S33 — Physical locator uses platform adapter

Given a workspace storage key

When it is resolved on a supported platform

Then only the platform filesystem adapter creates a native path and verifies containment in the Project workspace.

### S34 — Foreign path flavor is not blindly executed

Given a Project records a Windows external locator but is opened on Linux

When source access is requested

Then PIG reports the locator as unavailable or requiring explicit remapping; it does not reinterpret the string as a safe local path.

### S35 — Implicit archive directory is persisted as structure

Given an archive contains a member named `邮件资料/供应商报价.msg` but no explicit directory entry for `邮件资料/`

When the member is cataloged

Then PIG persists a `邮件资料` Folder Node as a direct `ARCHIVE_ENTRY` child of the archive, persists the MSG as its `FOLDER_CONTAINS` child, retains the full LogicalPath, and creates the corresponding Lineage edges. The UI renders these persisted facts rather than inventing a presentation-only group.

## 8. Milestone 1 completion checks

Milestone 1 is complete when:

- every core term has one non-overlapping definition;
- state transitions and outcome meanings are explicit;
- Source reference-mode risks are modeled rather than hidden;
- direct Relationships and persisted Lineage semantics are unambiguous;
- security rules are expressible without Handler-specific exceptions;
- the canonical nested evidence example is representable;
- the scenarios above can be converted to executable tests in later milestones;
- no database, Handler, UI, AI, Tool adapter, Workflow, Automation, or MCP implementation has been introduced.
