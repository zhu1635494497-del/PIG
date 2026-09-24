# ADR-003：Processing Application 边界 / Processing Application Boundary

- 状态：已接受 / Status: Accepted
- 决策日期：2026-09-14 / Decision date: 2026-09-14
- 范围：PIG V1 Milestone 5 / Scope: PIG V1 Milestone 5
- 已批准方案：B / Approved option: B

## Context

> 中文摘要：本 ADR 将 Project 级 Queue/Job/Policy 聚合与单 Node 执行分开。
> `ProjectProcessingService` 负责 Orchestration，`NodeExecutor` 负责一次确定性执行，
> Handler 保持格式边界。该分层在 Workbench 中仍可复用。

Milestone 4 combined Job ownership, Source verification, one-Node execution, Handler dispatch, child persistence, and final status projection in one Application service. Milestone 5 must iteratively process newly discovered descendants while keeping one durable Job and one policy budget for the complete project run.

Keeping the Milestone 4 shape would either create one Job per Node or make the same service conditionally own and not own Job lifecycle. Both would make Job meaning, recovery detection, and global resource accounting ambiguous.

## Decision

The approved Option B separates orchestration from execution:

- `ProjectProcessingService` is the synchronous coordinator. It owns the Job, correlation ID, in-memory `deque`, global policy budget, aggregation, and final Project/Job projection.
- `NodeExecutor` executes exactly one `DISCOVERED` Node inside an existing `RUNNING` Job. It owns that Node's Attempt, input verification, detection, Handler dispatch, child registration, lineage persistence, and Node/Attempt terminal states.
- `process_project` creates one `PROCESS_PROJECT` Job and any number of per-Node Attempts.
- `process_node` remains a compatibility Application Action, but it uses the same coordinator and `NodeExecutor`; it does not retain a second implementation path.

The queue is process-local and synchronous in Milestone 5. Queue contents are not a new persistent domain object or table. Durable Nodes, statuses, Jobs, Attempts, and Events remain the business truth.

## Queue and recovery semantics

- Initial queue entries are all Project Nodes currently in `DISCOVERED`, ordered by Repository order (`depth`, `created_at`, `id`).
- Newly registered Children enter the tail only when their persisted status is `DISCOVERED`.
- Blocked, failed, unsupported, and explicit ZIP directory-marker Nodes are durable evidence but are not scheduled.
- A new processing action is rejected with `RECOVERY_REQUIRED` when an existing Job or Attempt is `QUEUED/RUNNING`, or a Node is `PENDING/PROCESSING`.
- Milestone 5 does not infer whether interrupted work is safe to replay and does not mutate interrupted state automatically. Recovery remains Milestone 10 scope.

## Resource semantics

- `max_depth` and `max_node_count` apply across the Project run.
- `max_total_expanded_size` is one Job-wide budget. Before each Node execution, the coordinator passes only the remaining byte allowance to the Handler path.
- The persisted Job policy snapshot always contains the original requested policy, not the decreasing internal allowance.
- Actual streamed output remains checked by the Artifact Store; declared archive metadata alone is not trusted.

## Consequences

- A recursive evidence chain shares one Job/correlation context while retaining one Attempt per Node.
- Job status has project-run meaning instead of container-call meaning.
- Handler contracts remain unchanged and never schedule descendants.
- There is intentionally no worker framework, persistent queue, pause/resume implementation, Redis, or message broker.
- A process crash can leave a durable active state which is explicitly detectable but not yet recoverable.
