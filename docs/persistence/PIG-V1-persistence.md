# PIG V1 历史持久化设计 / Historical Persistence Design

> Historical evidence-oriented persistence. No legacy data migration is required;
> new Workbench schema planning starts at Milestone W1 after explicit approval.

> 中文摘要：本文记录当前 SQLite、SQLAlchemy Mapping、Repository、Trigger、Index、
> Alembic 0001–0005 和 Transaction Boundary。新 Workbench 不迁移旧数据；新 Schema
> 设计只有进入 W1 后才能开始。

- 状态：历史证据导向 Schema / Status: Historical evidence-oriented schema
- 版本：0.5 / Version: 0.5
- 日期：2026-09-15 / Date: 2026-09-15
- 约束规则：`PIG Project Rules.md` / Governing rules: `PIG Project Rules.md`
- 历史领域基线：`PIG-V1-domain-model.md` / Historical domain baseline: `PIG-V1-domain-model.md`
- 初始 Migration：`0001_initial_project_schema.py` / Initial migration: `0001_initial_project_schema.py`
- Current migration: `migrations/versions/0005_recovery_vocabulary.py`

## 1. Persistence boundary

Each Project owns one SQLite database inside its Project workspace. The database is authoritative for that Project's catalog, relationships, lineage, current processing state, and processing-event history.

Milestone 2 does not create Project workspaces or import external files. A database path is supplied by a later Application boundary.

## 2. Layer boundary

```text
Domain dataclasses and repository Protocols
            ↓
SQLAlchemy repository adapters
            ↓
SQLAlchemy persistence-only Models
            ↓
One Project SQLite database
```

- `pig.domain` imports neither SQLAlchemy nor Alembic.
- ORM Models are not returned to Application or UI callers.
- Repositories map between domain dataclasses and persistence Models.
- `SqlAlchemyUnitOfWork` owns one explicit Session transaction.
- Repository writes flush for immediate constraint validation but never commit.
- Only the Unit of Work commits or rolls back.

## 3. Tables

| Table | Purpose |
|---|---|
| `projects` | Single Project identity and current summary status. |
| `sources` | External Source references, accepted fingerprints, and availability state. |
| `source_roots` | Explicit immutable Source-to-root-Node assignment without a cyclic insert dependency. |
| `nodes` | Logical evidence occurrences and current processing outcome. |
| `artifacts` | External byte references and workspace-extracted byte locations. |
| `node_relationships` | Canonical direct structural parent-child facts. |
| `node_lineage` | Persisted ancestor-descendant closure. |
| `node_metadata` | Typed secondary Node observations. |
| `processing_jobs` | Requested processing/recovery batches and policy snapshots; one active Job per Project. |
| `processing_attempts` | Per-Node attempt history and structured error outcome. |
| `processing_events` | Append-only business event history. |
| `alembic_version` | Current database schema revision. |

## 4. Key database constraints

### One Project per database

`projects.singleton_key` is fixed to `1` and unique. A second Project row is rejected.

### Same-Project and same-Source relationships

Composite foreign keys ensure:

- Source belongs to Project.
- Node belongs to Source and Project.
- Artifact belongs to Node and Project.
- Relationship parent and child belong to the same Source and Project.
- Lineage ancestor and descendant belong to the same Source and Project.
- Job, Attempt, and Event references stay in the same Project.

The redundant `project_id` and `source_id` columns are deliberate integrity guards, not denormalized UI data.

### Structural tree rules

- One non-root Node can have at most one direct structural parent.
- A parent cannot directly contain itself.
- Repository validation checks depth increment and known-cycle closure before inserting an edge.
- Repository validation requires a Container parent and a relationship type compatible with Folder, archive, or email semantics.
- Direct Relationships are immutable and canonical.
- `(project, parent, relationship type, discovery key)` is unique for retry idempotency.

### Lineage rules

- Primary key: `(project, ancestor, descendant)`.
- Self record requires distance 0.
- Non-self record requires positive distance.
- Repository validation prevents cross-Source Lineage.
- Closure remains repairable because direct Relationships are canonical.

### Typed Metadata

A check constraint requires exactly one value column matching `value_type`:

```text
TEXT, INTEGER, REAL, BOOLEAN, DATETIME, JSON
```

Core identity, state, and relationship data cannot be stored as Metadata.

### Active processing attempts

A partial unique index permits at most one `QUEUED` or `RUNNING` Attempt for a Node. Historical completed, failed, interrupted, and cancelled Attempts remain queryable.

### Immutable evidence guards

SQLite triggers protect:

- Project workspace locator.
- Source locator, kind, path flavor, and accepted fingerprint after first assignment.
- Source root assignment.
- Node evidence identity fields.
- Artifact identity and accepted fingerprint after first assignment.
- Direct Relationships.
- Processing Events from update or deletion.

Current status fields remain mutable so later Application services can record valid transitions and matching events in one Unit of Work.

## 5. Time and JSON

- Time values must be timezone-aware at the repository boundary.
- They are normalized to UTC and stored as ISO-8601 text ending in `Z`.
- Naive datetimes are rejected.
- JSON is limited to policy snapshots, detection details, event details, and explicitly typed JSON Metadata.
- JSON does not replace core relationships or current state.

## 6. SQLite connection policy

Application-created engines enable:

```text
PRAGMA foreign_keys=ON
PRAGMA busy_timeout=5000
PRAGMA journal_mode=WAL
```

Alembic migration connections enable foreign keys and busy timeout. Milestone
10 records a 10,000-Node reference baseline without changing this tuning.

## 7. Migration policy

- Current revision: `0005`.
- Revisions are self-contained and do not import application-defined SQLAlchemy types.
- Alembic `target_metadata` points to the infrastructure Base for schema comparison.
- Every schema change requires a new revision; revision `0001` becomes immutable after release.
- Tests apply the migration to a new database, compare it with current metadata, and downgrade to base.

Revision `0002` extends the constrained Attempt/Event error-code values with
`DEPENDENCY_UNAVAILABLE`, `DEPENDENCY_VERSION_UNSUPPORTED`,
`EXTERNAL_PROCESS_TIMEOUT`, and `EXTERNAL_PROCESS_OUTPUT_EXCEEDED`. It introduces
no new table or relationship representation and preserves the append-only Event
triggers across SQLite table recreation.

Revision `0003` adds `MANIFEST_SIZE_EXCEEDED` and `MANIFEST_EXPORT_FAILED` to
the same constrained error vocabularies. Manifest identity, storage key, size,
hash, schema version, and Event boundary are retained as structured append-only
Events; M8 adds no Manifest table or search index table.

Revision `0004` adds `OPEN_HANDOFF_FAILED` to constrained Attempt/Event error
codes and `SOURCE_UNREADABLE_DETECTED` to constrained Event types. M9 adds no UI,
session, recent-project, or open-history table: current integrity belongs to
Source/Artifact and immutable action history remains in Processing Events.

Revision `0005` adds explicit Node `INTERRUPTED`, recovery/integrity error and
Event vocabulary, and a partial unique index enforcing one active Job per
Project. SQLite table recreation restores the Node identity-immutable and Event
append-only triggers. Recovery facts remain in existing Job, Attempt, Node,
Artifact, Source, and Event structures; no generic JSON recovery table is added.

Programmatic migration entry points:

```text
upgrade_database(project_database_path)
downgrade_database(project_database_path)
```

These functions migrate only a supplied Project database. They do not discover or create a Project workspace.

## 8. Repository boundaries

### ProjectRepository

- Add Project.
- Get Project by identity.
- Get the database's singleton Project for the desktop load query.

### CatalogRepository

- Add/get Source and assign its root.
- Register a root Node together with its self-Lineage and immutable Source-root assignment.
- Register a child Node together with its direct Relationship, self-Lineage, and inherited ancestor closure.
- Get Node.
- Add/query Artifact.
- Add/query direct Relationship.
- Add/query Lineage.
- Add/query typed Metadata.
- Search bounded Project Nodes by literal structural/Metadata text and typed
  Source/kind/format/status filters.
- Read complete, deterministically ordered Project Artifact, Relationship,
  Lineage, and Metadata collections for Manifest generation.

### ProcessingRepository

- Add/get Job.
- Add/get Attempt.
- Append and query Processing Events.

### UnitOfWork

- Creates all repositories over one Session.
- Requires explicit commit.
- Rolls back uncommitted work or exceptions.

Status-transition commands are intentionally not added in Milestone 2. They belong to the Application use cases authorized in Milestone 3 and must persist current state plus the corresponding Event atomically.

## 9. Deferred boundaries

- Automatic recovery, resumable checkpoints, Manifest retention, and streaming
  serialization.
- FTS/content indexes and locale-aware collation.
- Installer, code signing, and native macOS/Linux release qualification.

No AI, Agent, public Tool adapter, Workflow, Automation, MCP, OCR, RAG, or
content-index implementation is introduced through Milestone 10.
