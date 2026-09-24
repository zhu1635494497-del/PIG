import pytest

from pig.domain.enums import (
    AttemptStatus,
    JobStatus,
    NodeProcessingStatus,
    ProjectStatus,
    SourceStatus,
)
from pig.domain.exceptions import InvariantViolationError
from pig.domain.transitions import (
    require_attempt_transition,
    require_job_transition,
    require_node_transition,
    require_project_transition,
    require_source_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProjectStatus.CREATED, ProjectStatus.IMPORTING),
        (ProjectStatus.IMPORTING, ProjectStatus.PROCESSING),
        (ProjectStatus.IMPORTING, ProjectStatus.FAILED),
        (ProjectStatus.PROCESSING, ProjectStatus.READY),
        (ProjectStatus.PROCESSING, ProjectStatus.READY_WITH_WARNINGS),
        (ProjectStatus.PROCESSING, ProjectStatus.FAILED),
        (ProjectStatus.READY, ProjectStatus.IMPORTING),
        (ProjectStatus.READY, ProjectStatus.PROCESSING),
        (ProjectStatus.READY_WITH_WARNINGS, ProjectStatus.IMPORTING),
        (ProjectStatus.READY_WITH_WARNINGS, ProjectStatus.PROCESSING),
        (ProjectStatus.FAILED, ProjectStatus.IMPORTING),
        (ProjectStatus.FAILED, ProjectStatus.PROCESSING),
    ],
)
def test_accepted_project_transitions(current, target) -> None:
    require_project_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProjectStatus.CREATED, ProjectStatus.READY),
        (ProjectStatus.IMPORTING, ProjectStatus.READY),
        (ProjectStatus.PROCESSING, ProjectStatus.IMPORTING),
        (ProjectStatus.READY, ProjectStatus.FAILED),
    ],
)
def test_invalid_project_transitions_are_rejected(current, target) -> None:
    with pytest.raises(InvariantViolationError):
        require_project_transition(current, target)


def test_processing_lifecycle_transitions_used_by_milestone_4() -> None:
    require_source_transition(SourceStatus.AVAILABLE, SourceStatus.VERIFYING)
    require_source_transition(SourceStatus.VERIFYING, SourceStatus.AVAILABLE)
    require_node_transition(
        NodeProcessingStatus.DISCOVERED, NodeProcessingStatus.PENDING
    )
    require_node_transition(
        NodeProcessingStatus.PENDING, NodeProcessingStatus.PROCESSING
    )
    for outcome in (
        NodeProcessingStatus.SUCCESS,
        NodeProcessingStatus.PARTIAL_SUCCESS,
        NodeProcessingStatus.CORRUPTED,
        NodeProcessingStatus.LIMIT_EXCEEDED,
        NodeProcessingStatus.SECURITY_BLOCKED,
        NodeProcessingStatus.SOURCE_CHANGED,
        NodeProcessingStatus.FAILED,
    ):
        require_node_transition(NodeProcessingStatus.PROCESSING, outcome)
    require_job_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    require_job_transition(JobStatus.RUNNING, JobStatus.SUCCESS)
    require_attempt_transition(AttemptStatus.QUEUED, AttemptStatus.RUNNING)
    require_attempt_transition(AttemptStatus.RUNNING, AttemptStatus.COMPLETED)
    require_node_transition(
        NodeProcessingStatus.PROCESSING, NodeProcessingStatus.INTERRUPTED
    )
    require_node_transition(
        NodeProcessingStatus.INTERRUPTED, NodeProcessingStatus.PENDING
    )


@pytest.mark.parametrize(
    ("function", "current", "target"),
    [
        (require_source_transition, SourceStatus.AVAILABLE, SourceStatus.CHANGED),
        (
            require_node_transition,
            NodeProcessingStatus.DISCOVERED,
            NodeProcessingStatus.SUCCESS,
        ),
        (require_job_transition, JobStatus.QUEUED, JobStatus.SUCCESS),
        (
            require_attempt_transition,
            AttemptStatus.COMPLETED,
            AttemptStatus.RUNNING,
        ),
    ],
)
def test_processing_lifecycle_rejects_shortcuts(function, current, target) -> None:
    with pytest.raises(InvariantViolationError):
        function(current, target)
