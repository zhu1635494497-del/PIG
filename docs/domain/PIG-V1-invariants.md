# PIG V1 历史领域不变量 / Historical Domain Invariants

> Historical evidence-oriented invariants. They remain evidence of the existing
> implementation but do not override ADR-010 or the Workbench domain model.

> 中文摘要：本文记录旧系统的 Project/Source/Node/Relationship/Lineage/Artifact、
> Processing、Security、Event 和 Recovery 不变量。凡与 ADR-010 冲突之处均由
> Workbench 规范取代，其余内容用于理解现有实现。

- 状态：历史证据导向不变量 / Status: Historical evidence-oriented invariants
- 版本：0.2 / Version: 0.2
- 约束规则：`PIG Project Rules.md` / Governing rules: `PIG Project Rules.md`

An invariant is a rule that must remain true regardless of UI, Handler, storage adapter, or operating system.

## 1. Project boundary

1. Every Source, Node, Artifact, Relationship, Job, Attempt, Event, and Lineage record belongs to exactly one Project.
2. No relationship or lineage record may cross Project boundaries.
3. A Project's workspace locator cannot be changed as an incidental update. Relocation requires an explicit future migration operation.
4. A project database is authoritative only for its own Project.

## 2. External Original Source policy

5. PIG never writes to, renames, moves, deletes, or extracts into an external Source.
6. D1 reference mode does not claim physical immutability. It guarantees non-modification by PIG and detects external change when the Source is revalidated.
7. Source locator and accepted fingerprint are immutable historical facts.
8. Before reading bytes for processing, retry, export, or open, an external file is revalidated.
9. A missing external Source produces `SOURCE_MISSING`; it is not silently removed from the Project.
10. A fingerprint mismatch produces `SOURCE_CHANGED`; accepted hash, existing Nodes, and existing lineage are not rewritten.
11. New bytes at an existing path are imported as a new Source.
12. Restored bytes may reactivate an existing Source only when their accepted identity matches.
13. Folder Source descendants must remain inside the registered folder boundary after canonical path resolution.
14. Symbolic links are never followed in V1, even if their apparent target is inside the Source boundary.
15. Source authorization checks and subsequent byte access must refer to the same resolved object as far as the operating system permits; if that cannot be established safely, access fails closed.

## 3. Node identity and structure

16. Node identity is independent of name, path, and content hash.
17. Equal content in two structural locations produces two Nodes.
18. Every Node belongs to one Source.
19. The root Node has no structural parent and has depth 0.
20. Every non-root V1 Node has exactly one structural parent.
21. Parent and child belong to the same Project and Source.
22. A structural relationship cannot create a cycle.
23. Child depth equals parent depth plus one.
24. A Container may have zero children and still finish successfully.
25. An Unknown File is a valid Terminal File and does not fail a Project solely because its format is unknown.
26. XLSX, DOCX, and PPTX are Terminal Files in V1 and cannot be expanded by the generic ZIP capability.
27. Every safe directory prefix required by an accepted ZIP, 7z, or RAR member is persisted as a structural Folder Node and contributes Relationship and Lineage facts.
28. An explicit archive directory entry and the same implicit prefix collapse into one structural directory occurrence for that archive inspection; unsafe names cannot synthesize filesystem-accessible directories.

## 4. Relationship and lineage

29. Every discovered non-root Node has a persisted direct Relationship.
30. Relationship type explains the structural mechanism: folder containment, archive entry, email attachment, or embedded message.
31. A parent/type/discovery-key combination is idempotent for retry.
32. Duplicate names do not imply duplicate identity and must not overwrite one another.
33. Every Node has one distance-0 self Lineage record.
34. Every direct Relationship has one distance-1 Lineage record.
35. Every ancestor of a parent becomes an ancestor of its child at distance plus one.
36. Lineage must be derivable from direct Relationships.
37. If direct Relationships and closure disagree, direct Relationships are canonical and the inconsistency is recorded before repair.
38. UI tree state is never the source of Relationship or Lineage facts.

## 5. Logical and physical paths

39. LogicalPath and PhysicalLocator are distinct types and are never interchangeable.
40. LogicalPath cannot contain unresolved traversal segments.
41. Original unsafe names are retained as evidence but never passed directly to filesystem operations.
42. Workspace storage keys are project-relative and resolve inside the owning Project workspace.
43. External locators resolve inside the registered Source boundary for descendant access.
44. Platform-specific separators and drive syntax are infrastructure concerns; logical paths use platform-neutral semantics.
45. Changing physical storage layout must not change Node identity, Relationship, or Lineage.

## 6. Artifact integrity

46. Every readable byte-bearing Node has at least one Artifact reference or materialization.
47. A Node may exist without readable bytes when processing was blocked or failed.
48. SHA-256 is calculated from actual bytes, never trusted from an archive declaration.
49. Declared size and actual Artifact size are separate observations.
50. External Artifact use requires successful current verification.
51. Extracted Artifact paths must be inside the Project workspace.
52. Manifest outputs must use a generated safe ID under the owning Project's
    `manifests/` directory; callers cannot supply a destination path.
53. A published Manifest ID is immutable and cannot be overwritten by another
    export.
54. A completed Manifest export has one request Event and one correlated success
    or failure Event; the success Event records the exported byte identity.
55. Hash equality does not cause physical deduplication in V1.
56. Artifact integrity failure does not erase the Node or its history.

## 7. Processing and retry

57. Container traversal is queue-based; domain behavior must not depend on unbounded call-stack recursion.
58. Every active Node processing operation belongs to a Job and an Attempt.
59. A Node has at most one active Attempt in V1.
60. Retry creates a new Attempt with a higher attempt number.
61. Retry preserves all earlier states, errors, and events.
62. Retry cannot create a duplicate Child for the same parent/type/discovery key.
63. Node state transitions must follow the declared state machine.
64. Project and Job summary state cannot hide child failures.
65. A child failure does not discard already accepted siblings.
66. Unexpected exceptions are converted to structured failures and diagnostic references; they are never silently swallowed.

## 8. Security and resource policy

67. All input is untrusted.
68. Resource limits are supplied by centralized immutable Processing or Catalog Policy values.
69. Handlers cannot relax, override, or bypass centralized limits.
70. Path traversal, absolute archive paths, drive injection, device paths, and symbolic-link following are blocked.
71. Limits are checked against observed output, not only untrusted declared metadata.
72. Exceeding a limit records `LIMIT_EXCEEDED` and preserves already committed facts.
73. Password-protected content records `PASSWORD_REQUIRED`; V1 does not request or persist a password.
74. Security-blocked entries are retained as evidence records when they can be described safely.
75. Potentially executable, script, shortcut, or unknown files are not handed to the operating system by Open File; an allowed extracted file is handed off only through a contained, typed copy whose bytes match the persisted Artifact size and SHA-256.
76. An Open File decision is made in the backend/application boundary, never only in UI state.

## 9. Status and event history

77. Current status and historical events are stored separately.
78. Every accepted status transition has an immutable event containing previous and new state.
79. Processing Events are business facts; Debug Logs are diagnostics.
80. Business history is append-only during normal operations.
81. Event payload JSON may extend an event but cannot replace entity identity, state, or relationships.
82. Errors contain Node, Job/Attempt, processing stage, stable code, safe message, time, and retryability.
83. A successful detection of a blocked condition may produce Attempt `COMPLETED` and a non-success Node outcome; these meanings must not be conflated.

## 10. Recovery and concurrency

84. Process disappearance never becomes `FAILED` merely by inference; explicit
    recovery converts durable active state to `INTERRUPTED` or `CANCELLED`.
85. Recovery creates a new Job and new Attempts; it never reuses an interrupted
    execution identity.
86. A Project has at most one `QUEUED` or `RUNNING` Job, enforced by SQLite.
87. Uncommitted Workspace output is quarantined reversibly and is never deleted
    by recovery.
88. Known persisted Artifact and Manifest outputs cannot be quarantined as
    orphans.
89. Every completed quarantine move has an append-only Event with project-relative
    original and quarantine storage keys.
90. UI threading cannot weaken Application validation, state, event, or
    transaction rules.

## 11. Scope invariants

91. Content extraction and semantic classification are outside V1 domain behavior.
92. Future graph or AI capabilities must consume the established domain facts rather than replace them.
93. Milestone 10 introduces no persistent async task system, AI, Tool adapter,
    Workflow engine, Automation engine, or MCP server.
