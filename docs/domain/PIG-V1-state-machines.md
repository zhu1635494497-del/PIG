# PIG V1 历史状态机 / Historical State Machines

> Historical evidence-oriented state machines. New Workbench planning is defined
> in `PIG-V1-workbench-state-machines.md`.

> 中文摘要：本文定义旧 Project、Source、Node、Job、Attempt 和 Artifact Integrity
> 状态及 Event 要求。新 Workbench 的 ImportSession、Snapshot、Workspace Lifecycle、
> Materialization 和 Working Content 状态以新状态机文档为准。

- 状态：历史证据导向状态机 / Status: Historical evidence-oriented state machines
- 版本：0.1 / Version: 0.1
- 约束规则：`PIG Project Rules.md` / Governing rules: `PIG Project Rules.md`

## 1. State modeling rules

- Current state and historical events are separate.
- Every accepted state transition emits a Processing Event with previous and new state.
- Invalid transitions fail explicitly; callers cannot force arbitrary state values.
- Retry creates a new Processing Attempt and preserves previous events.
- Error reason and lifecycle state are related but not interchangeable.
- Project and Job summary states are projections over lower-level outcomes.

## 2. ProjectStatus

States:

```text
CREATED
IMPORTING
PROCESSING
READY
READY_WITH_WARNINGS
FAILED
```

Transitions:

```text
CREATED -> IMPORTING
IMPORTING -> PROCESSING
IMPORTING -> FAILED
PROCESSING -> READY
PROCESSING -> READY_WITH_WARNINGS
PROCESSING -> FAILED
READY -> IMPORTING
READY -> PROCESSING
READY_WITH_WARNINGS -> IMPORTING
READY_WITH_WARNINGS -> PROCESSING
FAILED -> IMPORTING
FAILED -> PROCESSING
```

Rules:

- `READY` means all required V1 work completed without warning/error outcomes.
- `READY_WITH_WARNINGS` means usable results exist and at least one Node is partial, unsupported, blocked, skipped, missing, changed, or failed.
- `FAILED` is reserved for failure to establish a usable project-level result, not for every child failure.
- Adding another Source starts a new import cycle; it does not erase prior Sources or events.

## 3. SourceStatus

States:

```text
REGISTERED
VERIFYING
AVAILABLE
MISSING
CHANGED
UNREADABLE
```

Transitions:

```text
REGISTERED -> VERIFYING
VERIFYING -> AVAILABLE
VERIFYING -> MISSING
VERIFYING -> CHANGED
VERIFYING -> UNREADABLE
AVAILABLE -> VERIFYING
MISSING -> VERIFYING
CHANGED -> VERIFYING
UNREADABLE -> VERIFYING
```

Rules:

- `CHANGED` does not permit overwriting the accepted fingerprint.
- If exact original bytes are restored, revalidation may return the Source to `AVAILABLE`.
- New bytes at the same path require a new Source.

## 4. NodeProcessingStatus

States:

```text
DISCOVERED
PENDING
PROCESSING
INTERRUPTED
SUCCESS
PARTIAL_SUCCESS
UNSUPPORTED
PASSWORD_REQUIRED
CORRUPTED
LIMIT_EXCEEDED
SECURITY_BLOCKED
SOURCE_MISSING
SOURCE_CHANGED
FAILED
SKIPPED
```

Primary transitions:

```text
DISCOVERED -> PENDING
DISCOVERED -> INTERRUPTED
PENDING -> PROCESSING
PENDING -> INTERRUPTED

PROCESSING -> SUCCESS
PROCESSING -> INTERRUPTED
PROCESSING -> PARTIAL_SUCCESS
PROCESSING -> UNSUPPORTED
PROCESSING -> PASSWORD_REQUIRED
PROCESSING -> CORRUPTED
PROCESSING -> LIMIT_EXCEEDED
PROCESSING -> SECURITY_BLOCKED
PROCESSING -> SOURCE_MISSING
PROCESSING -> SOURCE_CHANGED
PROCESSING -> FAILED
PROCESSING -> SKIPPED
```

Retry transitions:

```text
INTERRUPTED -> PENDING
PARTIAL_SUCCESS -> PENDING
UNSUPPORTED -> PENDING
PASSWORD_REQUIRED -> PENDING
CORRUPTED -> PENDING
LIMIT_EXCEEDED -> PENDING
SOURCE_MISSING -> PENDING
SOURCE_CHANGED -> PENDING
FAILED -> PENDING
```

Restricted transitions:

- `SECURITY_BLOCKED` may return to `PENDING` only after an explicit policy change or corrected safe input; automatic retry is forbidden.
- `SKIPPED` may return to `PENDING` only through an explicit retry action.
- `SOURCE_MISSING` or `SOURCE_CHANGED` may return to `PENDING` only after revalidation proves that the accepted original bytes are available again.
- `SUCCESS` is not automatically reprocessed. A deliberate reprocessing policy would require a later decision.
- `INTERRUPTED` is assigned only by explicit recovery when durable active state
  survives a stopped process. Recovery queues the same Node under a new Job and
  a new Attempt.

Outcome semantics:

- `SUCCESS`: the Node was successfully cataloged; a Container also completed child discovery under the active policy.
- `PARTIAL_SUCCESS`: at least one child was registered successfully and at least one child-level operation did not succeed.
- `UNSUPPORTED`: the object requires a capability or format feature not available in V1.
- `PASSWORD_REQUIRED`: encrypted content cannot be processed under D5.
- `CORRUPTED`: the claimed structure cannot be read consistently.
- `LIMIT_EXCEEDED`: a configured resource limit stopped work.
- `SECURITY_BLOCKED`: processing was rejected by a non-negotiable security rule such as path traversal or symbolic-link following.
- `SOURCE_MISSING`: externally referenced bytes are no longer present.
- `SOURCE_CHANGED`: externally referenced bytes differ from accepted identity.
- `FAILED`: an unclassified processing failure occurred and must carry a stable error code.
- `SKIPPED`: a deliberate, recorded decision omitted processing without claiming success.

Important distinction:

- An `UNKNOWN` Terminal File normally becomes `SUCCESS`: PIG successfully cataloged an unknown format.
- A recognized Container without an available Handler becomes `UNSUPPORTED`.

## 5. JobStatus

States:

```text
QUEUED
RUNNING
SUCCESS
PARTIAL_SUCCESS
FAILED
INTERRUPTED
CANCELLED
```

Transitions:

```text
QUEUED -> RUNNING
QUEUED -> CANCELLED
RUNNING -> SUCCESS
RUNNING -> PARTIAL_SUCCESS
RUNNING -> FAILED
RUNNING -> INTERRUPTED
RUNNING -> CANCELLED
```

Rules:

- `PARTIAL_SUCCESS` means usable work completed but one or more Node outcomes are non-success.
- Process disappearance or application shutdown does not imply `FAILED`; active work becomes `INTERRUPTED` after recovery inspection.
- An interrupted Job is immutable history and is never resumed in place.
  Recovery creates a new `RECOVER_INTERRUPTED` Job; a user-requested retry is a
  new `RETRY_NODE` Job.

## 6. AttemptStatus

States:

```text
QUEUED
RUNNING
COMPLETED
FAILED
INTERRUPTED
CANCELLED
```

Transitions:

```text
QUEUED -> RUNNING
QUEUED -> CANCELLED
RUNNING -> COMPLETED
RUNNING -> FAILED
RUNNING -> INTERRUPTED
RUNNING -> CANCELLED
```

Rules:

- Node outcome carries domain-specific results such as `PASSWORD_REQUIRED`; Attempt status records whether the attempt executed successfully as a unit.
- An Attempt may be `COMPLETED` while the resulting Node status is `PASSWORD_REQUIRED`, because encrypted-content detection completed correctly.
- Unexpected processing exceptions result in Attempt `FAILED` and normally Node `FAILED`.

## 7. ArtifactIntegrityStatus

States:

```text
UNVERIFIED
VERIFYING
VERIFIED
MISSING
MISMATCH
UNREADABLE
```

Transitions:

```text
UNVERIFIED -> VERIFYING
VERIFIED -> VERIFYING
MISSING -> VERIFYING
MISMATCH -> VERIFYING
UNREADABLE -> VERIFYING

VERIFYING -> VERIFIED
VERIFYING -> MISSING
VERIFYING -> MISMATCH
VERIFYING -> UNREADABLE
```

Rules:

- An external Original Reference must be `VERIFIED` before processing or direct opening.
- Verification failure changes integrity and relevant Source/Node operation outcomes but never changes the stored accepted hash.
- Workspace Extracted Artifacts also use integrity states; their mismatch is an internal integrity failure rather than `SOURCE_CHANGED`.

## 8. Required transition events

| Transition area | Required event examples |
|---|---|
| Project | `PROJECT_CREATED`, `PROJECT_STATUS_CHANGED` |
| Source | `SOURCE_REGISTERED`, `SOURCE_VERIFICATION_STARTED`, `SOURCE_VERIFIED`, `SOURCE_MISSING_DETECTED`, `SOURCE_CHANGED_DETECTED`, `SOURCE_UNREADABLE_DETECTED` |
| Node | `NODE_DISCOVERED`, `NODE_QUEUED`, `NODE_PROCESSING_STARTED`, `NODE_PROCESSING_FINISHED`, `NODE_PROCESSING_BLOCKED`, `NODE_PROCESSING_FAILED`, `NODE_PROCESSING_INTERRUPTED` |
| Job | `JOB_CREATED`, `JOB_STARTED`, `JOB_INTERRUPTED`, `JOB_CANCELLED`, `JOB_FINISHED` |
| Attempt | `ATTEMPT_QUEUED`, `ATTEMPT_STARTED`, `ATTEMPT_FINISHED`, `ATTEMPT_FAILED`, `ATTEMPT_INTERRUPTED`, `ATTEMPT_CANCELLED` |
| Artifact | `ARTIFACT_REGISTERED`, `ARTIFACT_VERIFIED`, `ARTIFACT_INTEGRITY_FAILED`, `ARTIFACT_VERIFICATION_INTERRUPTED` |
| Controlled open | `FILE_OPEN_REQUESTED`, `FILE_OPENED`, `FILE_OPEN_DENIED`, `FILE_OPEN_FAILED` |
| Recovery | `RECOVERY_STARTED`, `ORPHAN_QUARANTINED`, `RECOVERY_FINISHED`, `RECOVERY_FAILED` |

Exact persistence and event transaction mechanics are deferred to Milestone 2.
