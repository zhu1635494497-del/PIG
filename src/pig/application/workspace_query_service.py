from __future__ import annotations

from pathlib import Path, PurePosixPath

from pig.application.contracts import (
    GetWorkspaceItemRequest,
    GetWorkspaceItemResult,
    GetWorkspaceTreeRequest,
    GetWorkspaceTreeResult,
    SearchWorkspaceItemsRequest,
    SearchWorkspaceItemsResult,
    WorkspaceItemView,
)
from pig.application.errors import ApplicationError
from pig.application.ports import ProjectDatabaseProvider
from pig.domain.enums import (
    NodeFormat,
    WorkingContentStatus,
    WorkingRevisionRole,
    WorkspaceItemLifecycleStatus,
)
from pig.domain.exceptions import EntityNotFoundError, InvariantViolationError
from pig.domain.model_version import WORKBENCH_MODEL_VERSION


class WorkspaceQueryService:
    """Read-only Workspace projection for UI and future Tool callers."""

    def __init__(self, *, database: ProjectDatabaseProvider) -> None:
        self._database = database

    def tree(self, request: GetWorkspaceTreeRequest) -> GetWorkspaceTreeResult:
        project_id, database_path = self._identity(
            request.project_id, request.database_path
        )
        project, views = self._project_views(project_id, database_path)
        active = tuple(
            view
            for view in views
            if view.item.lifecycle_status == WorkspaceItemLifecycleStatus.ACTIVE
            and view.effectively_active
        )
        deleted = tuple(
            view
            for view in views
            if view.item.lifecycle_status == WorkspaceItemLifecycleStatus.DELETED
        )
        return GetWorkspaceTreeResult(
            project=project,
            workspace_revision=project.workspace_revision,
            items=active,
            deleted_items=deleted,
        )

    def item(self, request: GetWorkspaceItemRequest) -> GetWorkspaceItemResult:
        project_id, database_path = self._identity(
            request.project_id, request.database_path
        )
        project, views = self._project_views(project_id, database_path)
        view = next(
            (value for value in views if value.item.id == request.workspace_item_id),
            None,
        )
        if view is None:
            raise EntityNotFoundError(
                f"workspace item not found: {request.workspace_item_id}"
            )
        return GetWorkspaceItemResult(project=project, view=view)

    def search(
        self, request: SearchWorkspaceItemsRequest
    ) -> SearchWorkspaceItemsResult:
        project_id, database_path = self._identity(
            request.project_id, request.database_path
        )
        if not isinstance(request.limit, int) or isinstance(request.limit, bool) or not 1 <= request.limit <= 500:
            raise ApplicationError("INVALID_REQUEST", "limit must be between 1 and 500")
        if not isinstance(request.offset, int) or isinstance(request.offset, bool) or request.offset < 0:
            raise ApplicationError("INVALID_REQUEST", "offset must be nonnegative")
        formats = self._enum_values(request.formats, NodeFormat, "formats")
        content = self._enum_values(
            request.content_statuses, WorkingContentStatus, "content_statuses"
        )
        lifecycle = self._enum_values(
            request.lifecycle_statuses,
            WorkspaceItemLifecycleStatus,
            "lifecycle_statuses",
        )
        query = "" if request.query is None else request.query.strip().casefold()
        _project, views = self._project_views(project_id, database_path)
        matched = []
        for view in views:
            if view.item.lifecycle_status not in lifecycle:
                continue
            if (
                view.item.lifecycle_status == WorkspaceItemLifecycleStatus.ACTIVE
                and not view.effectively_active
            ):
                continue
            if formats and (
                view.source_node is None or view.source_node.format not in formats
            ):
                continue
            status = (
                None
                if view.working_artifact is None
                else view.working_artifact.content_status
            )
            if content and status not in content:
                continue
            searchable = "\n".join(
                (
                    view.item.display_name,
                    view.workspace_path,
                    "" if view.source_node is None else view.source_node.original_name,
                    "" if view.source_node is None else view.source_node.logical_path,
                )
            ).casefold()
            if query and query not in searchable:
                continue
            matched.append(view)
        matched.sort(key=lambda value: (value.workspace_path.casefold(), value.item.id))
        total = len(matched)
        page = tuple(matched[request.offset : request.offset + request.limit])
        return SearchWorkspaceItemsResult(
            project_id=project_id,
            items=page,
            total=total,
            limit=request.limit,
            offset=request.offset,
            has_more=request.offset + len(page) < total,
        )

    def _project_views(self, project_id: str, database_path: Path):
        with self._database.unit_of_work(database_path) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise EntityNotFoundError(f"project not found: {project_id}")
            self._project(project, database_path)
            items = tuple(
                uow.workspace.items_for_project(project_id, include_deleted=True)
            )
            placements = {
                item.id: uow.workspace.get_placement(item.id) for item in items
            }
            by_id = {item.id: item for item in items}
            views = []
            for item in items:
                placement = placements[item.id]
                if placement is None:
                    raise InvariantViolationError("workspace item placement is missing")
                source_node = (
                    None
                    if item.origin_source_node_id is None
                    else uow.catalog.get_node(item.origin_source_node_id)
                )
                source = (
                    None
                    if source_node is None
                    else uow.catalog.get_source(source_node.source_id)
                )
                working = uow.workspace.working_artifact_for_item(item.id)
                current_revision = (
                    None
                    if working is None
                    else uow.workspace.working_revision_for_artifact(
                        working.id, WorkingRevisionRole.CURRENT_CHECKPOINT
                    )
                )
                previous_revision = (
                    None
                    if working is None
                    else uow.workspace.working_revision_for_artifact(
                        working.id, WorkingRevisionRole.PREVIOUS
                    )
                )
                views.append(
                    WorkspaceItemView(
                        item=item,
                        placement=placement,
                        workspace_path=self._workspace_path(
                            item.id, by_id, placements
                        ),
                        effectively_active=self._effectively_active(
                            item.id, by_id, placements
                        ),
                        source_node=source_node,
                        source=source,
                        working_artifact=working,
                        current_revision=current_revision,
                        previous_revision=previous_revision,
                    )
                )
        return project, tuple(views)

    @staticmethod
    def _workspace_path(item_id, by_id, placements) -> str:
        segments: list[str] = []
        current = item_id
        visited: set[str] = set()
        while current is not None:
            if current in visited:
                raise InvariantViolationError("workspace placement contains a cycle")
            visited.add(current)
            item = by_id.get(current)
            placement = placements.get(current)
            if item is None or placement is None:
                raise InvariantViolationError("workspace placement parent is missing")
            segments.append(item.display_name)
            current = placement.parent_workspace_item_id
        return str(PurePosixPath(*reversed(segments)))

    @staticmethod
    def _effectively_active(item_id, by_id, placements) -> bool:
        current = item_id
        visited: set[str] = set()
        while current is not None:
            if current in visited:
                raise InvariantViolationError("workspace placement contains a cycle")
            visited.add(current)
            item = by_id.get(current)
            placement = placements.get(current)
            if item is None or placement is None:
                raise InvariantViolationError("workspace placement parent is missing")
            if item.lifecycle_status != WorkspaceItemLifecycleStatus.ACTIVE:
                return False
            current = placement.parent_workspace_item_id
        return True

    @staticmethod
    def _enum_values(values, enum_type, field):
        if any(not isinstance(value, enum_type) for value in values):
            raise ApplicationError("INVALID_REQUEST", f"{field} contains an invalid value")
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _identity(project_id: str, database_path: Path) -> tuple[str, Path]:
        project = project_id.strip()
        path = Path(database_path).expanduser().resolve(strict=False)
        if not project or not path.is_absolute():
            raise ApplicationError(
                "INVALID_REQUEST", "project_id and absolute database_path are required"
            )
        return project, path

    @staticmethod
    def _project(project, database_path: Path) -> None:
        if project.model_version != WORKBENCH_MODEL_VERSION:
            raise ApplicationError(
                "UNSUPPORTED_PROJECT_MODEL_VERSION", "unsupported Project data model"
            )
        if database_path.parent.as_uri() != project.workspace_locator:
            raise ApplicationError(
                "PROJECT_DATABASE_MISMATCH", "database path is outside the Project workspace"
            )
