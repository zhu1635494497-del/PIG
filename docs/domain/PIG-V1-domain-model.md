# PIG V1 历史领域模型 / Historical Domain Model

> Historical evidence-oriented model. For all new V1 planning use
> `PIG-V1-workbench-domain-model.md` and ADR-010. Old Project compatibility is
> outside scope.

> 中文摘要：本文完整记录旧证据导向模型，包括 Project、External Source、Node、
> Artifact、Relationship、Lineage、Metadata、Job、Attempt、Event、Logical Path 和
> Physical Locator。新 V1 必须使用 Workbench Domain Model；旧模型只用于代码考古。

- 状态：历史证据导向模型 / Status: Historical evidence-oriented model
- 版本：0.1 / Version: 0.1
- 日期：2026-09-13 / Date: 2026-09-13
- 约束规则：`PIG Project Rules.md` / Governing rules: `PIG Project Rules.md`
- 已批准决策：`ADR-001` / Approved decisions: `ADR-001`

## 1. Purpose and boundary

PIG V1 answers two questions:

1. What evidence objects exist inside a project source?
2. Through which source and container chain was each object discovered?

The V1 domain ends after structural ingestion, cataloging, lineage, metadata, state, events, manifest, metadata search, and controlled opening. Document content extraction, business semantics, AI, workflow automation, and semantic graphs are outside this model.

## 2. Ubiquitous language

| Term | Meaning |
|---|---|
| Project | An isolated project-data boundary with its own lifecycle and database. |
| Source | One explicit import occurrence referencing an external folder or file. |
| Node | One logical evidence occurrence discovered in a Source's structure. |
| Container | A Node whose structure can yield child Nodes. |
| Terminal File | A Node that V1 catalogs but does not structurally expand. |
| Artifact | A byte-bearing object associated with a Node, either externally referenced or materialized in the workspace. |
| Relationship | A persisted direct edge explaining how a child Node was discovered from a parent Node. |
| Lineage | Persisted ancestry derived from direct structural relationships and anchored to a Source. |
| Processing Job | One requested batch of discovery, processing, recovery, or retry work. |
| Processing Attempt | One auditable attempt to process one Node within a Job. |
| Processing Event | An immutable business record of an action, state transition, warning, or failure. |
| Logical Path | A platform-neutral evidence path used for display and search. |
| Physical Locator | A controlled locator used to access external or workspace bytes. |
| Fingerprint | Evidence used to detect content replacement: SHA-256 plus observed size, with timestamps as supporting metadata. |

## 3. Identity rules

- All entity identifiers are opaque and globally unique. Exact UUID representation is deferred to Milestone 2.
- A Project is identified only by `ProjectId`.
- A Source is one import occurrence. Importing the same path twice creates two Sources.
- A Node is an evidence occurrence, not a unique content blob. Equal hashes do not merge Nodes.
- An Artifact is one physical-byte occurrence or reference. Equal hashes do not merge Artifacts in V1.
- A path, file name, logical path, hash, or external inode/file identifier is never the primary entity identity.

## 4. Entities

### 4.1 Project

Responsibility: owns the V1 project boundary and summarizes the current health of its ingestion work.

Conceptual fields:

- `id: ProjectId`
- `name: ProjectName`
- `description: Optional[Text]`
- `status: ProjectStatus`
- `workspace_locator: WorkspaceLocator`
- `model_version: DomainModelVersion`
- `created_at: Instant`
- `updated_at: Instant`

Rules:

- Project name is user-facing and is not a filesystem path.
- A Project cannot contain Sources, Nodes, Jobs, or Events belonging to another Project.
- Project status is a current projection. Historical changes exist as Processing Events.
- The entire Node graph must not be loaded as one in-memory Project aggregate.

### 4.2 Source

Responsibility: records one user-authorized external ingestion boundary.

Conceptual fields:

- `id: SourceId`
- `project_id: ProjectId`
- `kind: SourceKind` (`FILE` or `FOLDER`)
- `display_name: SourceDisplayName`
- `locator: ExternalSourceLocator`
- `path_flavor: PathFlavor` (`WINDOWS`, `POSIX`, or platform-neutral URI where supported)
- `status: SourceStatus`
- `root_node_id: Optional[NodeId]`
- `registered_at: Instant`
- `last_verified_at: Optional[Instant]`
- `observed_size: Optional[ByteCount]`
- `observed_sha256: Optional[Sha256Digest]`
- `observed_modified_at: Optional[Instant]`

Rules:

- Source locator is immutable after registration.
- PIG reads a Source but never modifies it.
- V1 does not create an Original Snapshot by default.
- A file Source records size and SHA-256 once bytes are first accepted.
- A folder Source has no aggregate SHA-256 in V1; file descendants are fingerprinted individually.
- Missing or changed bytes do not rewrite the Source's accepted fingerprint.
- Re-importing changed bytes creates a new Source.

### 4.3 Node

Responsibility: represents one logical occurrence in the Evidence structure.

Conceptual fields:

- `id: NodeId`
- `project_id: ProjectId`
- `source_id: SourceId`
- `kind: NodeKind` (`CONTAINER` or `FILE`)
- `format: NodeFormat`
- `original_name: OriginalName`
- `display_name: SafeDisplayName`
- `logical_path: LogicalPath`
- `depth: NonNegativeInteger`
- `media_type: Optional[MediaType]`
- `declared_size: Optional[ByteCount]`
- `status: NodeProcessingStatus`
- `detection: Optional[DetectionEvidence]`
- `discovery_key: DiscoveryKey`
- `created_at: Instant`
- `updated_at: Instant`

Supported V1 format vocabulary:

```text
FOLDER, ZIP, RAR, SEVEN_Z, MSG, EML,
XLSX, XLS, CSV, PDF, DOCX, DOC,
PPTX, PPT, TXT, JPG, JPEG, PNG, UNKNOWN
```

Rules:

- Every Node belongs to exactly one Project and one Source.
- The Source of every descendant equals the Source of its structural root.
- The root Node has depth 0 and no structural parent.
- A non-root V1 Node has exactly one structural parent.
- `UNKNOWN` is a valid Terminal File format and may finish with `SUCCESS`.
- OOXML formats are Terminal Files in V1 even though their byte format contains ZIP structures.
- `logical_path` is evidence data, never an instruction for filesystem access.
- `original_name` may contain unsafe input and must never be passed directly to filesystem APIs.
- `display_name` may be sanitized for safe display but must not replace `original_name`.
- An archive member's full internal path is retained in `logical_path`, and every safe directory prefix required by that path is persisted as a structural `FOLDER` Node.
- An explicit archive directory entry and the same implicit path prefix collapse into one structural directory occurrence within that archive inspection.
- The archive owns each top-level member through `ARCHIVE_ENTRY`; descendants below a persisted archive directory use `FOLDER_CONTAINS`.

### 4.4 Artifact

Responsibility: describes bytes associated with a Node without conflating logical evidence identity and storage.

Conceptual fields:

- `id: ArtifactId`
- `project_id: ProjectId`
- `node_id: NodeId`
- `role: ArtifactRole`
- `scope: ArtifactScope`
- `locator: PhysicalLocator`
- `size: Optional[ByteCount]`
- `sha256: Optional[Sha256Digest]`
- `integrity_status: ArtifactIntegrityStatus`
- `observed_at: Optional[Instant]`
- `created_at: Instant`

V1 roles:

- `ORIGINAL_REFERENCE`: bytes remain at the registered external source.
- `EXTRACTED_ARTIFACT`: bytes materialized by PIG in the Project workspace.

Reserved but not produced by the approved V1 import mode:

- `WORKSPACE_COPY`

Future-only roles:

- `DERIVED_DATA`
- `EXTRACTED_TEXT`
- `THUMBNAIL`
- `NORMALIZED_DATASET`

Rules:

- An Artifact belongs to the same Project as its Node.
- External references are revalidated before use.
- Extracted Artifacts must be located inside the owning Project workspace.
- A Node may exist without a readable Artifact, such as a blocked archive entry.
- Artifact integrity state is independent from Node processing state.

### 4.5 NodeRelationship

Responsibility: stores one direct, semantically typed parent-to-child discovery fact.

Conceptual fields:

- `id: RelationshipId`
- `project_id: ProjectId`
- `parent_node_id: NodeId`
- `child_node_id: NodeId`
- `type: RelationshipType`
- `ordinal: NonNegativeInteger`
- `discovery_key: DiscoveryKey`
- `created_by_job_id: JobId`
- `created_at: Instant`

V1 relationship types:

- `FOLDER_CONTAINS`
- `ARCHIVE_ENTRY`
- `EMAIL_ATTACHMENT`
- `EMBEDDED_MESSAGE`

Rules:

- Parent and child must belong to the same Project and Source.
- A Node cannot be its own direct parent.
- A new relationship must not create a structural cycle.
- A parent, relationship type, and discovery key identify the same discovered occurrence for idempotent retry.
- Duplicate archive names remain distinct through entry ordinal/discovery key.

### 4.6 LineageRecord

Responsibility: represents one persisted ancestor-to-descendant fact for fast and reliable lineage queries.

Conceptual fields:

- `project_id: ProjectId`
- `ancestor_node_id: NodeId`
- `descendant_node_id: NodeId`
- `distance: NonNegativeInteger`

Rules:

- Every Node has exactly one self record with distance 0.
- Every direct relationship has a corresponding distance-1 lineage record.
- Creating a child copies every parent ancestor to the child with distance incremented by one.
- Lineage records must be derivable from direct relationships.
- Direct relationships are canonical if a repair is required.
- Deleting or rewriting lineage history is not a V1 normal operation.

### 4.7 NodeMetadata

Responsibility: stores secondary typed observations that do not deserve a stable first-class domain field.

Conceptual fields:

- `id: MetadataId`
- `node_id: NodeId`
- `namespace: MetadataNamespace`
- `key: MetadataKey`
- `value: TypedMetadataValue`
- `provenance: MetadataProvenance`
- `observed_at: Optional[Instant]`
- `created_at: Instant`

Rules:

- Core identity, status, relationship, lineage, permission, and lifecycle facts cannot be moved into Metadata.
- Metadata values are explicitly typed.
- Parser raw payload may be retained as diagnostic metadata later, but it is never the only representation of a core fact.

### 4.8 ProcessingJob

Responsibility: represents one requested batch of ingestion-related work.

Conceptual fields:

- `id: JobId`
- `project_id: ProjectId`
- `type: JobType`
- `status: JobStatus`
- `requested_by: ActorId`
- `policy_snapshot: ProcessingPolicySnapshot`
- `created_at: Instant`
- `started_at: Optional[Instant]`
- `finished_at: Optional[Instant]`
- `warning_count: NonNegativeInteger`
- `error_count: NonNegativeInteger`

V1 job types:

- `IMPORT_SOURCE`
- `PROCESS_PROJECT`
- `RETRY_NODE`
- `RECOVER_INTERRUPTED`

Rules:

- A Job belongs to exactly one Project.
- Resource policy values are captured at Job creation for auditability.
- Job counters are projections and must be reproducible from Attempts/Events.

### 4.9 ProcessingAttempt

Responsibility: represents one attempt to process one Node in one Job.

Conceptual fields:

- `id: AttemptId`
- `job_id: JobId`
- `node_id: NodeId`
- `attempt_number: PositiveInteger`
- `status: AttemptStatus`
- `stage: ProcessingStage`
- `handler_name: Optional[HandlerName]`
- `handler_version: Optional[HandlerVersion]`
- `queued_at: Instant`
- `started_at: Optional[Instant]`
- `finished_at: Optional[Instant]`
- `error: Optional[ProcessingError]`

Rules:

- Attempt numbers are monotonically increasing per Node.
- A retry creates a new Attempt; it never erases or reuses a completed Attempt.
- A Node has at most one active Attempt at a time in V1.
- Failure details are structured, including retryability.

### 4.10 ProcessingEvent

Responsibility: stores an immutable business-history fact.

Conceptual fields:

- `id: EventId`
- `event_type: EventType`
- `project_id: ProjectId`
- `source_id: Optional[SourceId]`
- `node_id: Optional[NodeId]`
- `job_id: Optional[JobId]`
- `attempt_id: Optional[AttemptId]`
- `actor: ActorId`
- `occurred_at: Instant`
- `previous_status: Optional[StatusCode]`
- `new_status: Optional[StatusCode]`
- `error_code: Optional[ErrorCode]`
- `details: EventDetails`
- `correlation_id: CorrelationId`

Rules:

- Events are append-only.
- A state transition and its event are one consistency requirement.
- Event details may carry extensible data but cannot replace core entity relationships.
- Stack traces and low-level diagnostics belong to Debug Logs, not Processing Events.

## 5. Value objects and controlled vocabularies

### 5.1 LogicalPath

- Uses `/` as a platform-neutral separator.
- Uses `!/` to display a transition into an archive or email container.
- Is absolute within a Source evidence namespace, not within an operating-system filesystem.
- Is normalized deterministically.
- Cannot contain unresolved `.` or `..` segments.
- Is not required to be globally unique; Node ID remains identity.
- Every safe archive-internal directory segment is backed by a persisted structural Node and therefore contributes a Relationship and Lineage edge.

Example:

```text
/采购资料.zip!/邮件资料/供应商报价.msg!/报价附件.zip!/最终报价.xlsx
```

### 5.2 PhysicalLocator

A tagged value object:

- `EXTERNAL_SOURCE`: resolved only through the registered Source boundary.
- `PROJECT_WORKSPACE`: project-relative storage key resolved only through the Project workspace boundary.

Raw input names and logical paths cannot be converted directly into PhysicalLocator values.

### 5.3 Fingerprint

For byte-bearing files:

- SHA-256 is the accepted content identity check.
- Actual byte size is required when hashing succeeds.
- Modified timestamp is supporting evidence, not a content identity substitute.
- A hash mismatch is `SOURCE_CHANGED` or `INTEGRITY_MISMATCH`; it is not silently accepted as a new version.

### 5.4 DetectionEvidence

Conceptual fields:

- `detected_format`
- `extension_hint`
- `media_type_hint`
- `signature_hint`
- `method`
- `confidence`
- `conflict_code`

Detection precedence and implementation belong to later milestones. Domain rules require that OOXML terminal formats are distinguishable from generic ZIP containers.

### 5.5 ProcessingError

Conceptual fields:

- `code: ErrorCode`
- `category: ErrorCategory`
- `stage: ProcessingStage`
- `message: SafeUserMessage`
- `retryable: Boolean`
- `technical_reference: Optional[DiagnosticReference]`

Technical details must not expose secrets or uncontrolled file content in user-facing messages.

Initial error-code vocabulary:

```text
SOURCE_NOT_FOUND
SOURCE_FINGERPRINT_MISMATCH
SOURCE_OUTSIDE_BOUNDARY
SYMLINK_BLOCKED
PATH_TRAVERSAL_BLOCKED
ABSOLUTE_PATH_BLOCKED
DEVICE_PATH_BLOCKED
INVALID_FILENAME
PASSWORD_REQUIRED
CORRUPTED_CONTAINER
UNSUPPORTED_FORMAT
UNSUPPORTED_FEATURE
DEPENDENCY_UNAVAILABLE
DEPENDENCY_VERSION_UNSUPPORTED
EXTERNAL_PROCESS_TIMEOUT
EXTERNAL_PROCESS_OUTPUT_EXCEEDED
MANIFEST_SIZE_EXCEEDED
MANIFEST_EXPORT_FAILED
MAX_DEPTH_EXCEEDED
MAX_NODE_COUNT_EXCEEDED
MAX_ARCHIVE_ENTRIES_EXCEEDED
MAX_SINGLE_FILE_SIZE_EXCEEDED
MAX_TOTAL_EXPANDED_SIZE_EXCEEDED
MAX_COMPRESSION_RATIO_EXCEEDED
ARTIFACT_MISSING
ARTIFACT_HASH_MISMATCH
OPEN_FORMAT_DENIED
OPEN_INTEGRITY_REQUIRED
HANDLER_FAILURE
INTERNAL_ERROR
```

Initial processing-stage vocabulary:

```text
REGISTER_SOURCE
VERIFY_SOURCE
DISCOVER_NODE
DETECT_FORMAT
INSPECT_CONTAINER
EXTRACT_CHILD
REGISTER_CHILD
PERSIST_RELATIONSHIP
UPDATE_LINEAGE
VERIFY_ARTIFACT
OPEN_FILE
EXPORT_MANIFEST
```

### 5.6 ProcessingPolicySnapshot

Conceptual fields:

- maximum depth
- maximum total Node count
- maximum archive entry count
- maximum email MIME/attachment part count
- maximum single-file size
- maximum total expanded size
- maximum compression ratio
- maximum external-process listing/diagnostic output size
- external-process timeout
- symbolic-link policy
- encrypted-archive policy
- allowed-open formats
- path and filename limits

Values are centralized configuration, not Handler constants.

### 5.7 CatalogPolicy

Milestone 8 adds immutable Application-level limits for:

- maximum structural/Metadata search query length;
- maximum search page size;
- maximum generated Manifest byte size.

These values constrain read/export capabilities and are distinct from the
per-Processing-Job `ProcessingPolicySnapshot`.

## 6. Event catalog

Required V1 event vocabulary:

```text
PROJECT_CREATED
PROJECT_STATUS_CHANGED
SOURCE_REGISTERED
SOURCE_VERIFICATION_STARTED
SOURCE_VERIFIED
SOURCE_MISSING_DETECTED
SOURCE_CHANGED_DETECTED
NODE_DISCOVERED
NODE_FORMAT_DETECTED
NODE_QUEUED
NODE_PROCESSING_STARTED
CONTAINER_OPENED
CHILD_DISCOVERED
CHILD_EXTRACTED
RELATIONSHIP_CREATED
LINEAGE_UPDATED
NODE_PROCESSING_FINISHED
NODE_PROCESSING_BLOCKED
NODE_PROCESSING_FAILED
JOB_CREATED
JOB_STARTED
JOB_INTERRUPTED
JOB_FINISHED
ATTEMPT_QUEUED
ATTEMPT_STARTED
ATTEMPT_FINISHED
ATTEMPT_FAILED
ARTIFACT_REGISTERED
ARTIFACT_VERIFIED
ARTIFACT_INTEGRITY_FAILED
ARTIFACT_VERIFICATION_INTERRUPTED
FILE_OPEN_REQUESTED
FILE_OPENED
FILE_OPEN_DENIED
FILE_OPEN_FAILED
MANIFEST_EXPORT_REQUESTED
MANIFEST_EXPORTED
MANIFEST_EXPORT_FAILED
LINEAGE_INTEGRITY_FAILED
LINEAGE_REBUILT
ATTEMPT_INTERRUPTED
ATTEMPT_CANCELLED
RECOVERY_STARTED
RECOVERY_FINISHED
RECOVERY_FAILED
JOB_CANCELLED
NODE_PROCESSING_INTERRUPTED
ORPHAN_QUARANTINED
```

The catalog may be extended through an explicit domain change. Event names are stable machine-readable codes, not localized display text.

## 7. Aggregate and consistency boundaries

PIG does not treat the entire project tree as one aggregate because real projects may contain many Nodes.

Required consistency boundaries are:

1. Project lifecycle transition plus Project event.
2. Source registration plus root Node plus registration events.
3. Child registration: Artifact observation/materialization, Child Node, direct Relationship, Lineage records, queue item, and events.
4. Processing transition: Node current state, Attempt current state, Job projection updates, and events.

Exact database transaction design is deferred to Milestone 2.

## 8. Domain services required later

These are named capabilities, not Milestone 1 implementations:

- `SourceIdentityPolicy`: accepts and revalidates external-source fingerprints.
- `LogicalPathPolicy`: produces normalized evidence paths without filesystem access.
- `RelationshipPolicy`: validates parent-child legality and cycles.
- `LineagePolicy`: specifies closure updates and consistency checks.
- `ProcessingTransitionPolicy`: validates current-state transitions.
- `ResourceLimitPolicy`: evaluates centralized limits.
- `OpenAuthorizationPolicy`: evaluates whether a Node may be externally opened.

None is an AI Tool. They are deterministic domain policies.

## 9. Future application action boundaries

Milestone 1 only names these candidate actions:

- `create_project`
- `register_source`
- `process_project`
- `retry_node`
- `get_project_tree`
- `get_node`
- `get_lineage`
- `search_nodes`
- `open_node`
- `export_manifest`
- `recover_project`

Through Milestone 10 these are Application contracts where implemented; they
are not public AI Tool adapters. Tool, Workflow, Agent, Automation, and MCP
adapters remain outside V1.
