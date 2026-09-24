from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pig.application import (
    AddWorkspaceInputsRequest,
    CreateProjectRequest,
    CreateWorkspaceFolderRequest,
    ExportWorkspaceItemsRequest,
    GetWorkspaceTreeRequest,
    InspectProjectRecoveryRequest,
    LoadProjectRequest,
    MoveWorkspaceItemRequest,
    OpenWorkspaceItemRequest,
    PreviewImportUndoRequest,
    PigApplication,
    RefreshWorkingArtifactRequest,
    RecoverWorkbenchProjectRequest,
    RollbackWorkingArtifactRequest,
    RestoreWorkingArtifactRequest,
    RestoreWorkspaceItemRequest,
    SearchWorkspaceItemsRequest,
    SoftDeleteWorkspaceItemRequest,
    UndoImportedItemRequest,
    WorkspaceItemView,
)
from pig.application.errors import ApplicationError
from pig.domain.enums import (
    NodeFormat,
    WorkingContentStatus,
    WorkingRefreshReason,
    WorkspaceItemKind,
    WorkspaceExportKind,
)
from pig.domain.paths import safe_filesystem_segment
T = TypeVar("T")
ITEM_ID_ROLE = int(Qt.ItemDataRole.UserRole)
ITEM_KIND_ROLE = ITEM_ID_ROLE + 1


class EnumMultiSelect(QToolButton):
    def __init__(self, values: Iterable, empty_text: str, parent=None) -> None:
        super().__init__(parent)
        self._empty_text = empty_text
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu = QMenu(self)
        self._actions = {}
        for value in values:
            action = self._menu.addAction(value.value)
            action.setCheckable(True)
            action.toggled.connect(self._update_text)
            self._actions[value] = action
        self.setMenu(self._menu)
        self._update_text()

    def selected_values(self) -> tuple:
        return tuple(
            value for value, action in self._actions.items() if action.isChecked()
        )

    def set_selected_values(self, values: tuple) -> None:
        selected = set(values)
        for value, action in self._actions.items():
            action.setChecked(value in selected)
        self._update_text()

    def clear_selection(self) -> None:
        self.set_selected_values(())

    def _update_text(self, _checked: bool = False) -> None:
        selected = self.selected_values()
        if not selected:
            self.setText(self._empty_text)
        elif len(selected) == 1:
            self.setText(selected[0].value)
        else:
            self.setText(f"已选 {len(selected)} 项")


class FormatMultiSelect(EnumMultiSelect):
    def __init__(self, parent=None) -> None:
        super().__init__(NodeFormat, "全部格式", parent)


class WorkspaceTree(QTreeWidget):
    external_paths_dropped = Signal(object, object)
    move_requested = Signal(str, object, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["名称", "类型", "格式", "工作状态"])
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        target = self.itemAt(event.position().toPoint())
        if event.mimeData().hasUrls():
            paths = tuple(
                Path(url.toLocalFile()).absolute()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            )
            if paths:
                if target is None:
                    target_id = None
                elif self.dropIndicatorPosition() == (
                    QAbstractItemView.DropIndicatorPosition.OnItem
                ):
                    target_id = target.data(0, ITEM_ID_ROLE)
                else:
                    parent = target.parent()
                    target_id = (
                        None if parent is None else parent.data(0, ITEM_ID_ROLE)
                    )
                self.external_paths_dropped.emit(paths, target_id)
                event.acceptProposedAction()
            else:
                event.ignore()
            return
        source = self.currentItem()
        if event.source() is not self or source is None or len(self.selectedItems()) != 1:
            event.ignore()
            return
        source_id = source.data(0, ITEM_ID_ROLE)
        if target is None:
            parent_id = None
            ordinal = self.topLevelItemCount()
        elif self.dropIndicatorPosition() == (
            QAbstractItemView.DropIndicatorPosition.OnItem
        ) and target.data(0, ITEM_KIND_ROLE) in {
            WorkspaceItemKind.FOLDER.value,
            WorkspaceItemKind.CONTAINER_VIEW.value,
        }:
            parent_id = target.data(0, ITEM_ID_ROLE)
            ordinal = target.childCount()
        else:
            parent = target.parent()
            parent_id = None if parent is None else parent.data(0, ITEM_ID_ROLE)
            base_ordinal = (
                self.indexOfTopLevelItem(target)
                if parent is None
                else parent.indexOfChild(target)
            )
            ordinal = base_ordinal + (
                1
                if self.dropIndicatorPosition()
                in {
                    QAbstractItemView.DropIndicatorPosition.BelowItem,
                    QAbstractItemView.DropIndicatorPosition.OnItem,
                }
                else 0
            )
        self.move_requested.emit(source_id, parent_id, ordinal)
        event.acceptProposedAction()


class WorkbenchDropSurface(QWidget):
    external_paths_dropped = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("external_drag_active", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("external_drag_active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("external_drag_active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = tuple(
            Path(url.toLocalFile()).absolute()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        )
        if paths:
            self.external_paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class MainWindow(QMainWindow):
    """One-screen Workbench UI backed only by typed Application contracts."""

    def __init__(self, application: PigApplication, *, actor: str) -> None:
        super().__init__()
        self._application = application
        self._actor = actor
        self._project_id: str | None = None
        self._database_path: Path | None = None
        self._workspace_revision = 0
        self._views: dict[str, WorkspaceItemView] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pig-ui")
        self._worker_thread: Future | None = None
        self._background_success: Callable[[object], None] | None = None
        self._background_operation: str | None = None
        self._background_timer = QTimer(self)
        self._background_timer.setInterval(20)
        self._background_timer.timeout.connect(self._poll_background)
        self._busy_operation: str | None = None
        self._focus_refresh_pending = False
        self._reload_after_background = False
        self._closed = False
        self._opened_names: dict[str, str] = {}
        self._project_name = "PIG-Workspace"
        self._recovery_required = False
        self._recovery_inspection_token: str | None = None
        self._logger = logging.getLogger(__name__)

        self.setWindowTitle("PIG — Project Ingestion Gateway")
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_ui()
        self._set_project_actions_enabled(False)

    def _build_actions(self) -> None:
        self.new_project_action = QAction("新建项目", self)
        self.open_project_action = QAction("打开项目", self)
        self.recovery_action = QAction("恢复项目", self)
        self.add_files_action = QAction("添加文件", self)
        self.add_folder_action = QAction("添加文件夹", self)
        self.create_folder_action = QAction("新建工作区文件夹", self)
        self.delete_action = QAction("软删除", self)
        self.refresh_action = QAction("刷新工作区", self)
        self.export_action = QAction("导出所选", self)
        self.new_project_action.triggered.connect(self._new_project)
        self.open_project_action.triggered.connect(self._choose_project)
        self.recovery_action.triggered.connect(self._inspect_active_project_recovery)
        self.add_files_action.triggered.connect(self._choose_files)
        self.add_folder_action.triggered.connect(self._choose_folder)
        self.create_folder_action.triggered.connect(self._create_folder)
        self.delete_action.triggered.connect(self._delete_selected)
        self.refresh_action.triggered.connect(self._reload_workspace)
        self.export_action.triggered.connect(self._export_selected)
        toolbar = self.addToolBar("Workbench")
        toolbar.setMovable(False)
        for action in (
            self.new_project_action,
            self.open_project_action,
            self.recovery_action,
            self.add_files_action,
            self.add_folder_action,
            self.create_folder_action,
            self.delete_action,
            self.refresh_action,
            self.export_action,
        ):
            toolbar.addAction(action)

    def _build_ui(self) -> None:
        root = WorkbenchDropSurface(self)
        self.drop_surface = root
        root.external_paths_dropped.connect(lambda paths: self._add_inputs(paths, None))
        root.setStyleSheet(
            "WorkbenchDropSurface[external_drag_active='true'] {"
            " border: 2px dashed #3b82f6; background: #eff6ff; }"
        )
        layout = QVBoxLayout(root)
        self.project_location = QLabel("项目：未打开")
        self.project_location.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.project_location)
        self.recovery_banner = QLabel()
        self.recovery_banner.setStyleSheet(
            "padding: 8px; color: #7c2d12; background: #ffedd5; "
            "border: 1px solid #fdba74;"
        )
        self.recovery_banner.setWordWrap(True)
        self.recovery_banner.hide()
        layout.addWidget(self.recovery_banner)

        search_row = QHBoxLayout()
        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("搜索工作区名称、路径或原始名称")
        self.format_filter = FormatMultiSelect()
        self.content_filter = EnumMultiSelect(WorkingContentStatus, "全部工作状态")
        self.search_button = QPushButton("搜索")
        self.clear_search_button = QPushButton("清除")
        self.search_button.clicked.connect(self._search)
        self.clear_search_button.clicked.connect(self._clear_search)
        self.search_text.returnPressed.connect(self._search)
        search_row.addWidget(QLabel("Workspace Search"))
        search_row.addWidget(self.search_text, 1)
        search_row.addWidget(self.format_filter)
        search_row.addWidget(self.content_filter)
        search_row.addWidget(self.search_button)
        search_row.addWidget(self.clear_search_button)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_tabs = QTabWidget()
        self.tree = WorkspaceTree()
        self.tree.itemSelectionChanged.connect(self._tree_selection_changed)
        self.tree.itemDoubleClicked.connect(self._tree_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.tree.external_paths_dropped.connect(self._add_inputs)
        self.tree.move_requested.connect(self._move_item)
        self.search_results = QTableWidget(0, 5)
        self.search_results.setHorizontalHeaderLabels(
            ["名称", "Workspace Path", "类型", "格式", "工作状态"]
        )
        self.search_results.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.search_results.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.search_results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.search_results.itemSelectionChanged.connect(self._search_selection_changed)
        self.search_results.itemDoubleClicked.connect(self._search_double_clicked)
        self.search_results.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.search_results.customContextMenuRequested.connect(
            self._show_search_context_menu
        )
        self.deleted_items = QTableWidget(0, 4)
        self.deleted_items.setHorizontalHeaderLabels(
            ["名称", "原 Workspace Path", "类型", "删除时间"]
        )
        self.deleted_items.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.deleted_items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.deleted_items.itemSelectionChanged.connect(self._deleted_selection_changed)
        self.deleted_items.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.deleted_items.customContextMenuRequested.connect(
            self._show_deleted_context_menu
        )
        self.left_tabs.addTab(self.tree, "Workspace")
        self.left_tabs.addTab(self.search_results, "Search Results")
        self.left_tabs.addTab(self.deleted_items, "已删除项目")

        right_tabs = QTabWidget()
        details_page = QWidget()
        details_layout = QVBoxLayout(details_page)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAcceptDrops(False)
        version_row = QHBoxLayout()
        self.versions = QTableWidget(0, 4)
        self.versions.setHorizontalHeaderLabels(
            ["版本", "文件修改时间", "PIG 检测时间", "SHA-256"]
        )
        self.versions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.versions.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.versions.setMaximumHeight(120)
        self.rollback_button = QPushButton("回滚到上一版本")
        self.rollback_button.clicked.connect(self._rollback_working_file)
        self.rollback_button.setEnabled(False)
        version_row.addWidget(self.versions, 1)
        version_row.addWidget(self.rollback_button)
        button_row = QHBoxLayout()
        self.open_selected_button = QPushButton("打开")
        self.refresh_file_button = QPushButton("刷新文件状态")
        self.restore_working_button = QPushButton("从原始备份恢复")
        self.restore_deleted_button = QPushButton("恢复已删除项目")
        self.open_selected_button.clicked.connect(self._open_selected)
        self.refresh_file_button.clicked.connect(
            lambda: self._refresh_selected_file()
        )
        self.restore_working_button.clicked.connect(self._restore_working_file)
        self.restore_deleted_button.clicked.connect(self._restore_deleted_item)
        for button in (
            self.open_selected_button,
            self.refresh_file_button,
            self.restore_working_button,
            self.restore_deleted_button,
        ):
            button.setEnabled(False)
            button_row.addWidget(button)
        details_layout.addWidget(self.details, 1)
        details_layout.addLayout(version_row)
        details_layout.addLayout(button_row)
        right_tabs.addTab(details_page, "Item Details / Origin")
        self.events = QTableWidget(0, 5)
        self.events.setHorizontalHeaderLabels(
            ["本地时间", "级别", "事件", "Workspace Item", "错误码"]
        )
        self.events.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        right_tabs.addTab(self.events, "Activity")
        splitter.addWidget(self.left_tabs)
        splitter.addWidget(right_tabs)
        splitter.setSizes([760, 520])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        for widget in (
            self.search_text,
            self.search_results,
            self.deleted_items,
            self.events,
        ):
            widget.setAcceptDrops(False)
            viewport = getattr(widget, "viewport", None)
            if callable(viewport):
                viewport().setAcceptDrops(False)

        self.busy_indicator = QProgressBar()
        self.busy_indicator.setRange(0, 0)
        self.busy_indicator.setMaximumWidth(150)
        self.busy_indicator.hide()
        self.statusBar().addPermanentWidget(self.busy_indicator)
        self.statusBar().showMessage("请新建或打开一个 Workbench Project")

    def _new_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建项目", "项目名称")
        if not accepted or not name.strip():
            return
        root = QFileDialog.getExistingDirectory(self, "选择项目存储根目录")
        if not root:
            return
        self._run_background(
            "创建项目",
            lambda: self._application.create_project(
                CreateProjectRequest(
                    name=name, actor=self._actor, workspace_root=Path(root).absolute()
                )
            ),
            self._project_created,
        )

    def _project_created(self, result) -> None:
        self._activate_project(result.project_id, result.database_path)
        QMessageBox.information(
            self,
            "项目已创建",
            f"项目已保存到：\n{result.workspace_path}\n\n"
            f"项目数据库：\n{result.database_path}\n\n"
            f"内部项目 ID：{result.project_id}",
        )

    def _choose_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "打开 PIG Project", "", "PIG Project (project.sqlite)"
        )
        if filename:
            path = Path(filename).absolute()
            self._run_background(
                "打开项目",
                lambda: self._application.load_project(
                    LoadProjectRequest(database_path=path)
                ),
                lambda result: self._project_loaded(result.project.id, path),
            )

    def _project_loaded(self, project_id: str, database_path: Path) -> None:
        self._project_id = project_id
        self._database_path = Path(database_path)
        self._recovery_required = True
        self._set_project_actions_enabled(False)
        self._inspect_active_project_recovery()

    def _inspect_active_project_recovery(self) -> None:
        if not self._has_project():
            return
        self._run_background(
            "检查项目恢复状态",
            lambda: self._application.inspect_project_recovery(
                InspectProjectRecoveryRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                )
            ),
            self._recovery_inspected,
        )

    def _recovery_inspected(self, result) -> None:
        self._recovery_required = result.recovery_required
        self._recovery_inspection_token = result.inspection_token
        if not result.recovery_required:
            self.recovery_banner.hide()
            self._set_project_actions_enabled(True)
            self._reload_workspace()
            return
        self.recovery_banner.setText(
            f"检测到 {len(result.candidates)} 个中断操作或未登记对象。"
            "项目当前为只读状态；确认恢复前不会移动或删除任何数据。"
        )
        self.recovery_banner.show()
        self._set_project_actions_enabled(False)
        preview = "\n".join(
            f"• {value.action.value} · {value.storage_key}"
            for value in result.candidates[:8]
        )
        if len(result.candidates) > 8:
            preview += f"\n• 另有 {len(result.candidates) - 8} 项"
        answer = QMessageBox.question(
            self,
            "项目需要恢复",
            "PIG 发现上次未完整结束的文件操作：\n\n"
            f"{preview}\n\n"
            "是否现在执行已规划的恢复？未知对象只会被可逆隔离，"
            "已登记的 Working 文件不会被自动覆盖。",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_background(
                "恢复项目",
                lambda: self._application.recover_workbench_project(
                    RecoverWorkbenchProjectRequest(
                        project_id=self._project_id,
                        database_path=self._database_path,
                        actor=self._actor,
                        inspection_token=result.inspection_token,
                        confirmed=True,
                    )
                ),
                self._recovery_completed,
            )
        else:
            self._reload_workspace()

    def _recovery_completed(self, result) -> None:
        if result.remaining_candidate_count:
            QMessageBox.warning(
                self,
                "恢复未完全结束",
                f"仍有 {result.remaining_candidate_count} 个项目需要处理。",
            )
            self._inspect_active_project_recovery()
            return
        self._recovery_required = False
        self._recovery_inspection_token = None
        self.recovery_banner.hide()
        QMessageBox.information(
            self,
            "恢复完成",
            f"已处理 {result.recovery_run.recovered_count} 项，"
            f"失败 {result.recovery_run.failed_count} 项。",
        )
        self._reload_workspace()

    def _activate_project(self, project_id: str, database_path: Path) -> None:
        self._project_id = project_id
        self._database_path = Path(database_path)
        self._recovery_required = False
        self._recovery_inspection_token = None
        self.recovery_banner.hide()
        self._set_project_actions_enabled(self._worker_thread is None)
        self._reload_workspace()

    def _choose_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(self, "添加多个文件")
        if filenames:
            paths = tuple(Path(value).absolute() for value in filenames)
            self._add_inputs(paths, self._selected_folder_id())

    def _choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "添加文件夹")
        if directory:
            self._add_inputs((Path(directory).absolute(),), self._selected_folder_id())

    def _add_inputs(self, paths, target_id) -> None:
        if not self._has_project() or not paths:
            return
        self._run_background(
            "添加项目资料",
            lambda: self._application.add_workspace_inputs(
                AddWorkspaceInputsRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    input_paths=tuple(paths),
                    actor=self._actor,
                    expected_workspace_revision=self._workspace_revision,
                    target_workspace_parent_id=target_id,
                )
            ),
            self._inputs_added,
        )

    def _inputs_added(self, result) -> None:
        imported = result.import_result
        QMessageBox.information(
            self,
            "添加完成",
            f"请求：{imported.requested_item_count}\n"
            f"接受：{imported.accepted_item_count}\n"
            f"失败：{imported.failed_item_count}",
        )
        self._reload_workspace()

    def _create_folder(self) -> None:
        if not self._has_project():
            return
        name, accepted = QInputDialog.getText(self, "新建工作区文件夹", "文件夹名称")
        if not accepted:
            return
        self._run_background(
            "创建文件夹",
            lambda: self._application.create_workspace_folder(
                CreateWorkspaceFolderRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    display_name=name,
                    actor=self._actor,
                    expected_workspace_revision=self._workspace_revision,
                    parent_workspace_item_id=self._selected_folder_id(),
                )
            ),
            lambda _result: self._reload_workspace(),
        )

    def _move_item(self, item_id: str, parent_id, ordinal: int) -> None:
        if not self._has_project():
            return
        self._run_background(
            "移动工作区项目",
            lambda: self._application.move_workspace_item(
                MoveWorkspaceItemRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                    expected_workspace_revision=self._workspace_revision,
                    new_parent_workspace_item_id=parent_id,
                    new_ordinal=ordinal,
                )
            ),
            lambda _result: self._reload_workspace(),
        )

    def _delete_selected(self) -> None:
        item_id = self._selected_active_id()
        self._soft_delete_item(item_id)

    def _soft_delete_item(self, item_id) -> None:
        if item_id is None or not self._has_project() or item_id not in self._views:
            return
        view = self._views[item_id]
        answer = QMessageBox.question(
            self,
            "确认软删除",
            f"从正常工作区隐藏“{view.item.display_name}”？\n\n"
            "Original、Source 和 Working File 不会被删除。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_background(
            "软删除",
            lambda: self._application.soft_delete_workspace_item(
                SoftDeleteWorkspaceItemRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                    expected_workspace_revision=self._workspace_revision,
                    confirmed=True,
                )
            ),
            lambda _result: self._reload_workspace(),
        )

    def _undo_import_item(self, item_id) -> None:
        if item_id is None or not self._has_project():
            return
        self._run_background(
            "检查误导入撤销范围",
            lambda: self._application.preview_import_undo(
                PreviewImportUndoRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                )
            ),
            self._confirm_import_undo,
        )

    def _confirm_import_undo(self, impact) -> None:
        answer = QMessageBox.question(
            self,
            "确认撤销误导入",
            f"将从本项目彻底移除顶层导入项“{impact.display_name}”及其来源树。\n\n"
            f"Workspace 项目：{impact.workspace_item_count}\n"
            f"Working File：{impact.working_file_count}\n"
            f"其中已修改：{impact.modified_working_file_count}\n"
            f"项目内待移除数据：{self._format_bytes(impact.original_byte_count + impact.working_byte_count)}\n\n"
            "外部原始文件不会被删除；该操作在 PIG 项目内不可恢复。是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_background(
            "撤销误导入",
            lambda: self._application.undo_imported_item(
                UndoImportedItemRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=impact.workspace_item_id,
                    actor=self._actor,
                    expected_workspace_revision=self._workspace_revision,
                    confirmed=True,
                )
            ),
            self._import_undo_completed,
        )

    def _import_undo_completed(self, result) -> None:
        QMessageBox.information(
            self,
            "已撤销误导入",
            f"已从项目移除 {result.purged_workspace_item_count} 个 Workspace 项目，"
            f"清理 {self._format_bytes(result.removed_byte_count)}。\n\n"
            "外部原始文件未被修改。",
        )
        self._reload_workspace()

    def _restore_deleted_item(self) -> None:
        item_id = self.restore_deleted_button.property("workspace_item_id")
        self._restore_item(item_id)

    def _restore_item(self, item_id) -> None:
        if item_id is None or not self._has_project():
            return
        self._run_background(
            "恢复已删除项目",
            lambda: self._application.restore_workspace_item(
                RestoreWorkspaceItemRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                    expected_workspace_revision=self._workspace_revision,
                )
            ),
            lambda result: self._deleted_restored(result),
        )

    def _deleted_restored(self, result) -> None:
        if result.restore_fallback:
            QMessageBox.information(self, "恢复完成", "原位置不可用，项目已恢复到根目录。")
        self._reload_workspace()

    def _open_selected(self) -> None:
        self._open_item(self.open_selected_button.property("workspace_item_id"))

    def _open_item(self, item_id) -> None:
        if item_id is None or not self._has_project():
            return
        view = self._views.get(item_id)
        if view is None:
            return
        effective_name = (
            Path(view.working_artifact.storage_key).name
            if view.working_artifact is not None
            else view.item.display_name
        ).casefold()
        other = self._opened_names.get(effective_name)
        if other is not None and other != item_id:
            answer = QMessageBox.question(
                self,
                "可能存在 Host Application 同名冲突",
                "本次会话中已向 Host Application 交接过一个同名文件。\n\n"
                "Excel 等程序可能拒绝同时打开不同目录中的同名文件。"
                "请确认另一个文件已经关闭，或取消本次打开。\n\n是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._run_background(
            "打开文件",
            lambda: self._application.open_workspace_item(
                OpenWorkspaceItemRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                )
            ),
            self._file_opened,
        )

    def _file_opened(self, result) -> None:
        self._opened_names[result.path.name.casefold()] = result.workspace_item_id
        self.statusBar().showMessage(f"已交给系统打开：{result.path.name}")
        self._reload_workspace()

    def _refresh_selected_file(self, reason=WorkingRefreshReason.EXPLICIT) -> None:
        item_id = self.refresh_file_button.property("workspace_item_id")
        if item_id is None or not self._has_project():
            return
        self._run_background(
            "刷新文件状态",
            lambda: self._application.refresh_working_artifact(
                RefreshWorkingArtifactRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                    reason=reason,
                )
            ),
            lambda _result: self._reload_workspace(),
        )

    def _restore_working_file(self) -> None:
        item_id = self.restore_working_button.property("workspace_item_id")
        view = self._views.get(item_id)
        if view is None or view.working_artifact is None or not self._has_project():
            return
        status = view.working_artifact.content_status
        confirmed = False
        if status in {WorkingContentStatus.MODIFIED, WorkingContentStatus.UNREADABLE}:
            confirmed = QMessageBox.question(
                self,
                "确认恢复原始内容",
                "该操作会覆盖当前 Working File。是否继续？",
            ) == QMessageBox.StandardButton.Yes
            if not confirmed:
                return
        self._run_background(
            "恢复 Working File",
            lambda: self._application.restore_working_artifact(
                RestoreWorkingArtifactRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                    confirmed_replace=confirmed,
                )
            ),
            lambda _result: self._reload_workspace(),
        )

    def _rollback_working_file(self) -> None:
        item_id = self.rollback_button.property("workspace_item_id")
        view = self._views.get(item_id)
        if view is None or view.previous_revision is None or not self._has_project():
            return
        answer = QMessageBox.question(
            self,
            "确认回滚到上一版本",
            "该操作会用上一版本覆盖当前 Working File。\n"
            "当前版本会被保留为新的上一版本，因此可以再次切换回来。\n\n是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_background(
            "回滚 Working File",
            lambda: self._application.rollback_working_artifact(
                RollbackWorkingArtifactRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_id=item_id,
                    actor=self._actor,
                    confirmed_replace=True,
                )
            ),
            lambda _result: self._reload_workspace(),
        )

    def _export_selected(self) -> None:
        if not self._has_project():
            return
        item_ids = self._selected_export_ids()
        if not item_ids:
            QMessageBox.information(self, "导出", "请先选择一个或多个项目。")
            return
        selected = tuple(self._views[item_id] for item_id in item_ids)
        if any(
            view.item.item_kind == WorkspaceItemKind.CONTAINER_VIEW
            for view in selected
        ):
            QMessageBox.warning(
                self,
                "导出",
                "Container View 不能直接导出；请选择普通工作区文件夹或 Terminal File。",
            )
            return
        single = selected[0] if len(selected) == 1 else None
        directory_export = (
            single is not None and single.item.item_kind == WorkspaceItemKind.FOLDER
        )
        if directory_export:
            parent = QFileDialog.getExistingDirectory(self, "选择导出文件夹的上级目录")
            if not parent:
                return
            destination = (
                Path(parent).absolute()
                / safe_filesystem_segment(single.item.display_name)
            )
            if destination.exists() or destination.is_symlink():
                QMessageBox.warning(
                    self,
                    "导出文件夹",
                    f"目标文件夹已存在：\n{destination}\n\n"
                    "为避免合并或覆盖，请选择其他上级目录。",
                )
                return
            confirmed = False
        elif single is not None:
            default_name = single.item.display_name
            filename, _ = QFileDialog.getSaveFileName(self, "导出文件", default_name)
            if not filename:
                return
            destination = Path(filename).absolute()
            confirmed = False
            if destination.exists() or destination.is_symlink():
                confirmed = QMessageBox.question(
                    self,
                    "确认覆盖导出文件",
                    f"目标已存在：\n{destination}\n\n是否覆盖？",
                ) == QMessageBox.StandardButton.Yes
                if not confirmed:
                    return
        else:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "将所选项目导出为 ZIP",
                f"{self._project_name}-导出.zip",
                "ZIP Archive (*.zip)",
            )
            if not filename:
                return
            destination = Path(filename).absolute()
            confirmed = False
            if destination.exists() or destination.is_symlink():
                confirmed = QMessageBox.question(
                    self,
                    "确认覆盖导出文件",
                    f"目标已存在：\n{destination}\n\n是否覆盖？",
                ) == QMessageBox.StandardButton.Yes
                if not confirmed:
                    return
        self._run_background(
            "导出 Workspace 文件",
            lambda: self._application.export_workspace_items(
                ExportWorkspaceItemsRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    workspace_item_ids=item_ids,
                    destination_path=destination,
                    actor=self._actor,
                    confirmed_replace=confirmed,
                )
            ),
            self._export_completed,
        )

    def _export_completed(self, result) -> None:
        kind = {
            WorkspaceExportKind.FILE: "文件",
            WorkspaceExportKind.DIRECTORY: "文件夹",
            WorkspaceExportKind.ZIP: "ZIP 包",
        }[result.export_kind]
        QMessageBox.information(
            self,
            "导出成功",
            f"已导出{kind}（{result.entry_count} 个文件）：\n{result.destination_path}",
        )
        self._reload_workspace()

    def _search(self) -> None:
        if not self._has_project():
            return
        self._run_background(
            "搜索工作区",
            lambda: self._application.search_workspace_items(
                SearchWorkspaceItemsRequest(
                    project_id=self._project_id,
                    database_path=self._database_path,
                    query=self.search_text.text(),
                    formats=self.format_filter.selected_values(),
                    content_statuses=self.content_filter.selected_values(),
                )
            ),
            self._show_search_results,
        )

    def _show_search_results(self, result) -> None:
        self.search_results.setRowCount(0)
        for view in result.items:
            row = self.search_results.rowCount()
            self.search_results.insertRow(row)
            values = (
                view.item.display_name,
                view.workspace_path,
                view.item.item_kind.value,
                "" if view.source_node is None else view.source_node.format.value,
                self._working_status(view),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(ITEM_ID_ROLE, view.item.id)
                self.search_results.setItem(row, column, cell)
        self.left_tabs.setCurrentWidget(self.search_results)
        suffix = "（仅显示前 200 条）" if result.has_more else ""
        self.statusBar().showMessage(f"找到 {result.total} 个 Workspace Item{suffix}")

    def _clear_search(self) -> None:
        self.search_text.clear()
        self.format_filter.clear_selection()
        self.content_filter.clear_selection()
        self.search_results.setRowCount(0)
        self.left_tabs.setCurrentWidget(self.tree)

    def _reload_workspace(self) -> None:
        if not self._has_project():
            return
        if self._worker_thread is not None:
            self._reload_after_background = True
            return
        self._run_background(
            "加载工作区",
            lambda: (
                self._application.get_workspace_tree(
                    GetWorkspaceTreeRequest(
                        project_id=self._project_id,
                        database_path=self._database_path,
                    )
                ),
                self._application.load_project(
                    LoadProjectRequest(database_path=self._database_path)
                ),
            ),
            lambda result: self._apply_workspace(result[0], result[1].events),
        )

    def _apply_workspace(self, result, events) -> None:
        selected_id = self.open_selected_button.property("workspace_item_id")
        self._workspace_revision = result.workspace_revision
        self._views = {
            view.item.id: view for view in (*result.items, *result.deleted_items)
        }
        self.setWindowTitle(f"PIG — {result.project.name}")
        self._project_name = result.project.name
        self.project_location.setText(
            f"项目：{result.project.name} · Revision {result.workspace_revision} · "
            f"存储位置：{self._database_path.parent}"
        )
        self.project_location.setToolTip(str(self._database_path))
        self.tree.clear()
        widgets = {}
        pending = list(result.items)
        while pending:
            progressed = False
            for view in tuple(pending):
                parent_id = view.placement.parent_workspace_item_id
                if parent_id is not None and parent_id not in widgets:
                    continue
                widget = QTreeWidgetItem(
                    [
                        view.item.display_name,
                        view.item.item_kind.value,
                        "" if view.source_node is None else view.source_node.format.value,
                        self._working_status(view),
                    ]
                )
                widget.setData(0, ITEM_ID_ROLE, view.item.id)
                widget.setData(0, ITEM_KIND_ROLE, view.item.item_kind.value)
                parent = widgets.get(parent_id)
                if parent is None:
                    self.tree.addTopLevelItem(widget)
                else:
                    parent.addChild(widget)
                widgets[view.item.id] = widget
                pending.remove(view)
                progressed = True
            if not progressed:
                raise RuntimeError("Workspace projection contains an unresolved parent")
        self.tree.expandToDepth(1)
        self.deleted_items.setRowCount(0)
        for view in result.deleted_items:
            row = self.deleted_items.rowCount()
            self.deleted_items.insertRow(row)
            values = (
                view.item.display_name,
                view.workspace_path,
                view.item.item_kind.value,
                "" if view.item.deleted_at is None else self._local_event_time(view.item.deleted_at),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(ITEM_ID_ROLE, view.item.id)
                self.deleted_items.setItem(row, column, cell)
        self._populate_events(events)
        selected_widget = widgets.get(selected_id)
        if selected_widget is not None:
            self.tree.setCurrentItem(selected_widget)
            self._show_view(selected_id)
        else:
            self._show_view(None)
        self.statusBar().showMessage(
            f"{len(result.items)} 个活动项目 · {len(result.deleted_items)} 个已删除项目"
        )

    def _tree_selection_changed(self) -> None:
        selected = self.tree.selectedItems()
        self._show_view(
            selected[0].data(0, ITEM_ID_ROLE) if len(selected) == 1 else None
        )

    def _search_selection_changed(self) -> None:
        rows = self.search_results.selectionModel().selectedRows()
        self._show_view(
            self._selected_table_id(self.search_results, rows[0].row())
            if len(rows) == 1
            else None
        )

    def _deleted_selection_changed(self) -> None:
        item_id = self._selected_table_id(self.deleted_items)
        self.restore_deleted_button.setProperty("workspace_item_id", item_id)
        self.restore_deleted_button.setEnabled(
            item_id is not None and self._worker_thread is None
        )
        self._show_view(item_id)

    def _tree_double_clicked(self, item, _column) -> None:
        item_id = item.data(0, ITEM_ID_ROLE)
        view = self._views.get(item_id)
        if view is not None and view.item.item_kind == WorkspaceItemKind.FILE:
            self._open_item(item_id)
        else:
            item.setExpanded(not item.isExpanded())

    def _search_double_clicked(self, item, _column) -> None:
        item_id = self._selected_table_id(self.search_results, item.row())
        view = self._views.get(item_id)
        if view is not None and view.item.item_kind == WorkspaceItemKind.FILE:
            self._open_item(item_id)

    def _show_tree_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.tree.clearSelection()
            self.tree.setCurrentItem(item)
            item.setSelected(True)
        self._show_active_context_menu(
            self.tree.viewport().mapToGlobal(position),
            item.data(0, ITEM_ID_ROLE),
        )

    def _show_search_context_menu(self, position) -> None:
        item = self.search_results.itemAt(position)
        if item is None:
            return
        row = item.row()
        if not self.search_results.selectionModel().isRowSelected(
            row, self.search_results.rootIndex()
        ):
            self.search_results.clearSelection()
            self.search_results.selectRow(row)
        self._show_active_context_menu(
            self.search_results.viewport().mapToGlobal(position),
            self._selected_table_id(self.search_results, row),
        )

    def _show_active_context_menu(self, global_position, item_id) -> None:
        menu = self._active_context_menu(item_id)
        if menu is not None:
            menu.exec(global_position)

    def _active_context_menu(self, item_id):
        view = self._views.get(item_id)
        if view is None or not view.effectively_active or self._worker_thread is not None:
            return None
        menu = QMenu(self)
        selected_ids = self._selected_export_ids()
        if view.item.item_kind == WorkspaceItemKind.FILE and len(selected_ids) == 1:
            menu.addAction("打开", lambda: self._open_item(item_id))
            if view.working_artifact is not None:
                menu.addAction("刷新文件状态", self._refresh_selected_file)
                if view.working_artifact.content_status != WorkingContentStatus.CLEAN:
                    menu.addAction("从原始备份恢复", self._restore_working_file)
            if view.previous_revision is not None:
                menu.addAction("回滚到上一版本", self._rollback_working_file)
            menu.addSeparator()
        menu.addAction(
            "导出所选" if len(selected_ids) > 1 else "导出",
            self._export_selected,
        )
        if len(selected_ids) == 1:
            menu.addAction("软删除", lambda: self._soft_delete_item(item_id))
            if self._is_import_root(view):
                menu.addSeparator()
                menu.addAction(
                    "撤销此次误导入（彻底移除）",
                    lambda: self._undo_import_item(item_id),
                )
        return menu

    def _show_deleted_context_menu(self, position) -> None:
        item = self.deleted_items.itemAt(position)
        if item is None or self._worker_thread is not None:
            return
        row = item.row()
        self.deleted_items.clearSelection()
        self.deleted_items.selectRow(row)
        item_id = self._selected_table_id(self.deleted_items, row)
        menu = QMenu(self)
        menu.addAction("恢复到工作区", lambda: self._restore_item(item_id))
        view = self._views.get(item_id)
        if view is not None and self._is_import_root(view):
            menu.addSeparator()
            menu.addAction(
                "撤销此次误导入（彻底移除）",
                lambda: self._undo_import_item(item_id),
            )
        menu.exec(self.deleted_items.viewport().mapToGlobal(position))

    @staticmethod
    def _is_import_root(view: WorkspaceItemView) -> bool:
        return (
            view.source is not None
            and view.source_node is not None
            and view.source.root_node_id == view.source_node.id
        )

    def _show_view(self, item_id) -> None:
        view = self._views.get(item_id)
        for button in (
            self.open_selected_button,
            self.refresh_file_button,
            self.restore_working_button,
            self.rollback_button,
        ):
            button.setProperty("workspace_item_id", item_id)
        if view is None:
            self.details.clear()
            self.versions.setRowCount(0)
            self._update_item_buttons(None)
            return
        node = view.source_node
        working = view.working_artifact
        lines = [
            f"Name: {view.item.display_name}",
            f"Workspace Path: {view.workspace_path}",
            f"Kind: {view.item.item_kind.value}",
            f"Lifecycle: {view.item.lifecycle_status.value}",
            f"Materialization: {view.item.materialization_status.value}",
            f"Working State: {self._working_status(view)}",
        ]
        if node is not None:
            lines.extend(
                (
                    "",
                    "Origin:",
                    f"- Original Name: {node.original_name}",
                    f"- Source Logical Path: {node.logical_path}",
                    f"- Format / Processing: {node.format.value} / {node.status.value}",
                    f"- Source Node ID: {node.id}",
                )
            )
        if working is not None:
            lines.extend(
                (
                    "",
                    "Working Artifact:",
                    f"- Storage Key: {working.storage_key}",
                    f"- Baseline: {working.baseline_size} bytes / {working.baseline_sha256}",
                    f"- Current: {working.current_size} bytes / {working.current_sha256}",
                )
            )
        self.details.setPlainText("\n".join(lines))
        self._show_versions(view)
        self._update_item_buttons(view)

    def _show_versions(self, view) -> None:
        self.versions.setRowCount(0)
        for label, revision in (
            ("当前", view.current_revision),
            ("上一版本", view.previous_revision),
        ):
            if revision is None:
                continue
            row = self.versions.rowCount()
            self.versions.insertRow(row)
            values = (
                label,
                self._local_event_time(revision.file_modified_at),
                self._local_event_time(revision.detected_at),
                revision.sha256,
            )
            for column, value in enumerate(values):
                self.versions.setItem(row, column, QTableWidgetItem(value))

    def _update_item_buttons(self, view) -> None:
        available = (
            view is not None
            and view.effectively_active
            and self._worker_thread is None
            and not self._recovery_required
        )
        is_file = available and view.item.item_kind == WorkspaceItemKind.FILE
        working = None if view is None else view.working_artifact
        self.open_selected_button.setEnabled(is_file)
        self.refresh_file_button.setEnabled(is_file and working is not None)
        self.restore_working_button.setEnabled(
            is_file
            and working is not None
            and working.content_status != WorkingContentStatus.CLEAN
        )
        self.rollback_button.setEnabled(
            is_file and view is not None and view.previous_revision is not None
        )
        self.export_action.setEnabled(
            bool(self._selected_export_ids())
            and self._worker_thread is None
            and not self._recovery_required
        )

    def _selected_export_ids(self) -> tuple[str, ...]:
        if self.left_tabs.currentWidget() is self.search_results:
            rows = sorted(
                index.row()
                for index in self.search_results.selectionModel().selectedRows()
            )
            values = [self._selected_table_id(self.search_results, row) for row in rows]
        elif self.left_tabs.currentWidget() is self.tree:
            values = [item.data(0, ITEM_ID_ROLE) for item in self.tree.selectedItems()]
        else:
            values = []
        return tuple(value for value in values if value in self._views)

    def _selected_folder_id(self):
        item_id = self._selected_active_id()
        view = self._views.get(item_id)
        return (
            item_id
            if view is not None and view.item.item_kind == WorkspaceItemKind.FOLDER
            else None
        )

    def _selected_active_id(self):
        selected = self.tree.selectedItems()
        return None if not selected else selected[0].data(0, ITEM_ID_ROLE)

    @staticmethod
    def _selected_table_id(table, row=None):
        if row is None:
            selected = table.selectedItems()
            if not selected:
                return None
            row = selected[0].row()
        first = table.item(row, 0)
        return None if first is None else first.data(ITEM_ID_ROLE)

    @staticmethod
    def _working_status(view: WorkspaceItemView) -> str:
        if view.working_artifact is not None:
            return view.working_artifact.content_status.value
        return view.item.materialization_status.value

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{value} B"

    def _populate_events(self, events) -> None:
        recent = list(events)[-300:]
        self.events.setRowCount(len(recent))
        for row, event in enumerate(reversed(recent)):
            values = (
                self._local_event_time(event.occurred_at),
                event.severity.value,
                event.event_type.value,
                event.workspace_item_id or "",
                "" if event.error_code is None else event.error_code.value,
            )
            for column, value in enumerate(values):
                self.events.setItem(row, column, QTableWidgetItem(value))

    def _run_background(self, operation, action, on_success) -> None:
        if self._worker_thread is not None:
            QMessageBox.information(
                self, operation, f"请等待当前操作完成：{self._busy_operation}"
            )
            return
        self._worker_thread = self._executor.submit(action)
        self._background_success = on_success
        self._background_operation = operation
        self._busy_operation = operation
        self._set_busy(True)
        self.statusBar().showMessage(f"正在{operation}…")
        self._background_timer.start()

    def _poll_background(self) -> None:
        future = self._worker_thread
        if future is None or not future.done():
            return
        self._background_timer.stop()
        success = self._background_success
        operation = self._background_operation or "操作"
        self._worker_thread = None
        self._background_success = None
        self._background_operation = None
        self._busy_operation = None
        self._set_busy(False)
        try:
            result = future.result()
        except BaseException as exc:
            self._show_failure(operation, exc)
            if isinstance(exc, ApplicationError) and exc.code == (
                "WORKSPACE_REVISION_CONFLICT"
            ):
                self._reload_workspace()
            return
        if success is not None:
            success(result)

    def _set_busy(self, busy: bool) -> None:
        self.busy_indicator.setVisible(busy)
        self.new_project_action.setEnabled(not busy)
        self.open_project_action.setEnabled(not busy)
        self._set_project_actions_enabled(self._has_project() and not busy)
        for widget in (
            self.search_text,
            self.format_filter,
            self.content_filter,
            self.search_button,
            self.clear_search_button,
            self.tree,
        ):
            widget.setEnabled(not busy)
        current = self._views.get(
            self.open_selected_button.property("workspace_item_id")
        )
        self._update_item_buttons(None if busy else current)
        self.restore_deleted_button.setEnabled(
            not busy
            and self.restore_deleted_button.property("workspace_item_id") is not None
        )

    def _set_project_actions_enabled(self, enabled: bool) -> None:
        enabled = enabled and not self._recovery_required
        for action in (
            self.add_files_action,
            self.add_folder_action,
            self.create_folder_action,
            self.delete_action,
            self.refresh_action,
            self.export_action,
        ):
            action.setEnabled(enabled)
        if enabled:
            self.export_action.setEnabled(bool(self._selected_export_ids()))
        self.recovery_action.setEnabled(
            self._has_project()
            and self._recovery_required
            and self._worker_thread is None
        )

    def _show_failure(self, operation: str, exc: BaseException) -> None:
        if isinstance(exc, ApplicationError):
            QMessageBox.warning(self, operation, f"{exc.message}\n\n错误码：{exc.code}")
        else:
            self._logger.error(
                "desktop background operation failed: %s",
                operation,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            QMessageBox.critical(self, operation, "操作失败。技术细节已写入应用日志。")

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if (
            event.type() == QEvent.Type.WindowActivate
            and hasattr(self, "refresh_file_button")
            and not self._closed
            and not self._focus_refresh_pending
        ):
            self._focus_refresh_pending = True
            QTimer.singleShot(500, self._focus_refresh_selected)
        return result

    def _focus_refresh_selected(self) -> None:
        self._focus_refresh_pending = False
        if self._closed or self._worker_thread is not None:
            return
        item_id = self.refresh_file_button.property("workspace_item_id")
        view = self._views.get(item_id)
        if view is not None and view.working_artifact is not None:
            self._refresh_selected_file(WorkingRefreshReason.FOCUS_GAINED)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker_thread is not None:
            QMessageBox.warning(
                self,
                "操作仍在执行",
                "PIG 正在执行持久化或文件操作，请等待完成后再关闭。",
            )
            event.ignore()
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = tuple(
            Path(url.toLocalFile()).absolute()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        )
        if paths and self._has_project():
            self._add_inputs(paths, None)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _has_project(self) -> bool:
        return self._project_id is not None and self._database_path is not None

    @staticmethod
    def _event_datetime(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @classmethod
    def _local_event_time(cls, value: datetime) -> str:
        return cls._event_datetime(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
