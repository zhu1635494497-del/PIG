from __future__ import annotations

import shutil
from pathlib import Path

from pig.application.errors import ApplicationError
from pig.application.ports import WorkspaceReservation


class LocalWorkspaceManager:
    """Owns the controlled `<selected-root>/<project-name>` workspace layout."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = self._validated_root(workspace_root)

    @staticmethod
    def _validated_root(workspace_root: Path) -> Path:
        raw_root = Path(workspace_root)
        if not raw_root.is_absolute():
            raise ApplicationError(
                code="INVALID_WORKSPACE_ROOT",
                message="workspace root must be absolute",
                details={"value": str(raw_root)},
            )
        if raw_root.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="workspace root must not be a symbolic link",
                details={"path": str(raw_root)},
            )
        return raw_root.resolve(strict=False)

    def reserve(
        self,
        project_id: str,
        project_name: str,
        workspace_root: Path | None = None,
    ) -> WorkspaceReservation:
        if not project_id or any(char in project_id for char in ("/", "\\", ":")):
            raise ApplicationError(
                code="INVALID_PROJECT_ID",
                message="project id is not a safe workspace segment",
            )
        directory_name = self._validated_project_directory_name(project_name)
        root = (
            self._root
            if workspace_root is None
            else self._validated_root(workspace_root)
        )
        self._ensure_directory(root, "workspace root")
        temporary = root / f".creating-{project_id}"
        final = root / directory_name
        self._require_direct_child(root, temporary)
        self._require_direct_child(root, final)
        if temporary.exists() or temporary.is_symlink() or final.exists() or final.is_symlink():
            raise ApplicationError(
                code="WORKSPACE_COLLISION",
                message="project workspace already exists",
                details={"project_id": project_id},
            )
        temporary.mkdir()
        return WorkspaceReservation(
            project_id=project_id,
            project_directory_name=directory_name,
            workspace_root=root,
            temporary_path=temporary,
            final_path=final,
            temporary_database_path=temporary / "project.sqlite",
            final_database_path=final / "project.sqlite",
        )

    def publish(self, reservation: WorkspaceReservation) -> None:
        self._validate_reservation(reservation.workspace_root, reservation)
        if reservation.final_path.exists() or reservation.final_path.is_symlink():
            raise ApplicationError(
                code="WORKSPACE_COLLISION",
                message="final project workspace already exists",
                details={"project_id": reservation.project_id},
            )
        reservation.temporary_path.rename(reservation.final_path)

    def abandon(self, reservation: WorkspaceReservation) -> None:
        self._validate_reservation(reservation.workspace_root, reservation)
        temporary = reservation.temporary_path
        if temporary.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="refusing to remove a symlinked temporary workspace",
            )
        if temporary.exists():
            shutil.rmtree(temporary)

    @staticmethod
    def _ensure_directory(path: Path, label: str) -> None:
        if path.is_symlink():
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message=f"{label} must not be a symbolic link",
                details={"path": str(path)},
            )
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise ApplicationError(
                code="INVALID_WORKSPACE_ROOT",
                message=f"{label} is not a directory",
                details={"path": str(path)},
            )

    @staticmethod
    def _require_direct_child(parent: Path, child: Path) -> None:
        if child.parent != parent:
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="project workspace escaped its configured parent",
            )

    @staticmethod
    def _validated_project_directory_name(project_name: str) -> str:
        value = project_name.strip()
        invalid = '<>:"/\\|?*'
        reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        if (
            not value
            or len(value) > 180
            or value in {".", ".."}
            or value.endswith((" ", "."))
            or any(character in invalid for character in value)
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or value.split(".", 1)[0].upper() in reserved
        ):
            raise ApplicationError(
                code="INVALID_PROJECT_DIRECTORY_NAME",
                message="project name is not a valid Windows directory name",
                details={"project_name": project_name},
            )
        return value

    def _validate_reservation(
        self, root: Path, reservation: WorkspaceReservation
    ) -> None:
        expected_temporary = root / f".creating-{reservation.project_id}"
        expected_final = root / reservation.project_directory_name
        if (
            reservation.temporary_path != expected_temporary
            or reservation.final_path != expected_final
        ):
            raise ApplicationError(
                code="UNSAFE_WORKSPACE",
                message="workspace reservation does not belong to this manager",
            )
