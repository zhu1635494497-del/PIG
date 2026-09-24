from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTreeWidgetItem,
)

from pig.application import CreateProjectRequest
from pig.bootstrap import create_local_application
from pig.domain.enums import NodeFormat, WorkingContentStatus
from pig.ui.main_window import ITEM_ID_ROLE, ITEM_KIND_ROLE, MainWindow, WorkspaceTree


class RecordingOpener:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def open(self, path: Path) -> None:
        self.paths.append(path)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _wait_idle(qt_app, window: MainWindow, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    idle_since = None
    while time.monotonic() < deadline:
        qt_app.processEvents()
        idle = window._worker_thread is None and not window._reload_after_background
        if idle:
            idle_since = time.monotonic() if idle_since is None else idle_since
            if time.monotonic() - idle_since >= 0.05:
                return
        else:
            idle_since = None
        time.sleep(0.01)
    raise AssertionError(f"desktop did not become idle: {window._busy_operation}")


def test_complete_workbench_ui_flow_uses_workspace_actions(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    opener = RecordingOpener()
    app = create_local_application(tmp_path / "projects", file_opener=opener)
    project = app.create_project(CreateProjectRequest(name="W7 Desktop", actor="tester"))
    source = tmp_path / "报价.txt"
    source.write_bytes(b"original quote")
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda _parent, title, message: messages.append((title, message))),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda _parent, title, message: messages.append((title, message))),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, title, message: messages.append((title, message))),
    )
    window = MainWindow(app, actor="tester")
    window._activate_project(project.project_id, project.database_path)
    _wait_idle(qt_app, window)
    assert window.tree.topLevelItemCount() == 0

    window._add_inputs((source,), None)
    _wait_idle(qt_app, window)
    assert window.tree.topLevelItemCount() == 1
    assert window._workspace_revision == 1
    file_item = window.tree.topLevelItem(0)
    assert file_item.text(0) == "报价.txt"
    assert file_item.text(3) == "VIRTUAL"

    window.tree.setCurrentItem(file_item)
    window._tree_double_clicked(file_item, 0)
    _wait_idle(qt_app, window)
    assert len(opener.paths) == 1
    assert opener.paths[0] != source
    assert opener.paths[0].read_bytes() == b"original quote"
    assert window.tree.topLevelItem(0).text(3) == "CLEAN"

    file_item = window.tree.topLevelItem(0)
    window.tree.setCurrentItem(file_item)
    window._refresh_selected_file()
    _wait_idle(qt_app, window)
    opener.paths[0].write_bytes(b"edited quote")
    file_item = window.tree.topLevelItem(0)
    window.tree.setCurrentItem(file_item)
    window._focus_refresh_selected()
    _wait_idle(qt_app, window)
    assert window.tree.topLevelItem(0).text(3) == "MODIFIED"

    window.search_text.setText("报价")
    window.format_filter.set_selected_values((NodeFormat.TXT,))
    window.content_filter.set_selected_values((WorkingContentStatus.MODIFIED,))
    window._search()
    _wait_idle(qt_app, window)
    assert window.search_results.rowCount() == 1
    assert window.search_results.item(0, 4).text() == "MODIFIED"
    window.search_results.selectRow(0)
    window._search_double_clicked(window.search_results.item(0, 0), 0)
    _wait_idle(qt_app, window)
    assert opener.paths == [opener.paths[0], opener.paths[0]]

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        staticmethod(lambda *_args, **_kwargs: ("最终资料", True)),
    )
    window.left_tabs.setCurrentWidget(window.tree)
    window.tree.clearSelection()
    window._create_folder()
    _wait_idle(qt_app, window)
    assert window._workspace_revision == 2
    roots = [window.tree.topLevelItem(index) for index in range(window.tree.topLevelItemCount())]
    folder_item = next(item for item in roots if item.text(0) == "最终资料")
    file_item = next(item for item in roots if item.text(0) == "报价.txt")
    window._move_item(
        file_item.data(0, 256),
        folder_item.data(0, 256),
        0,
    )
    _wait_idle(qt_app, window)
    assert window._workspace_revision == 3
    folder_item = next(
        window.tree.topLevelItem(index)
        for index in range(window.tree.topLevelItemCount())
        if window.tree.topLevelItem(index).text(0) == "最终资料"
    )
    assert folder_item.child(0).text(0) == "报价.txt"

    window.tree.setCurrentItem(folder_item.child(0))
    window._delete_selected()
    _wait_idle(qt_app, window)
    folder_item = next(
        window.tree.topLevelItem(index)
        for index in range(window.tree.topLevelItemCount())
        if window.tree.topLevelItem(index).text(0) == "最终资料"
    )
    assert folder_item.childCount() == 0
    assert window.deleted_items.rowCount() == 1
    window.deleted_items.selectRow(0)
    qt_app.processEvents()
    window._restore_deleted_item()
    _wait_idle(qt_app, window)
    folder_item = window.tree.topLevelItem(0)
    assert folder_item.child(0).text(0) == "报价.txt"
    assert folder_item.child(0).text(3) == "MODIFIED"
    window.tree.setCurrentItem(folder_item.child(0))
    window._restore_working_file()
    _wait_idle(qt_app, window)
    folder_item = window.tree.topLevelItem(0)
    assert folder_item.child(0).text(3) == "CLEAN"
    assert opener.paths[0].read_bytes() == b"original quote"
    assert source.read_bytes() == b"original quote"
    assert any(title == "添加完成" for title, _message in messages)
    window.close()


def test_busy_gate_keeps_window_responsive_and_serializes_actions(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    app = create_local_application(tmp_path / "projects")
    window = MainWindow(app, actor="tester")
    started = Event()
    release = Event()
    notices = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda _parent, title, message: notices.append((title, message))),
    )

    def blocking_action():
        started.set()
        assert release.wait(5)
        return "done"

    results = []
    window._run_background("长操作", blocking_action, results.append)
    deadline = time.monotonic() + 5
    while not started.is_set() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert started.is_set()
    assert not window.new_project_action.isEnabled()
    window._run_background("冲突操作", lambda: "bad", results.append)
    assert notices and "请等待当前操作完成" in notices[0][1]
    window.search_text.setText("仍可响应")
    assert window.search_text.text() == "仍可响应"
    release.set()
    _wait_idle(qt_app, window)
    assert results == ["done"]
    window.close()


def test_new_project_uses_selected_storage_and_loads_empty_workspace(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    default_root = tmp_path / "default"
    selected_root = tmp_path / "selected"
    selected_root.mkdir()
    app = create_local_application(default_root)
    window = MainWindow(app, actor="tester")
    messages = []
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        staticmethod(lambda *_args, **_kwargs: ("用户项目", True)),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: str(selected_root)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda _parent, title, message: messages.append((title, message))),
    )
    window._new_project()
    _wait_idle(qt_app, window)
    assert window._database_path is not None
    assert window._database_path == selected_root / "用户项目" / "project.sqlite"
    assert window.tree.topLevelItemCount() == 0
    assert "用户项目" in window.project_location.text()
    assert messages[0][0] == "项目已创建"
    assert not default_root.exists()
    window.close()


def test_workspace_tree_drop_translates_external_paths_and_internal_move(
    qt_app, tmp_path: Path
) -> None:
    tree = WorkspaceTree()
    source = QTreeWidgetItem(["source"])
    source.setData(0, ITEM_ID_ROLE, "source-id")
    source.setData(0, ITEM_KIND_ROLE, "FILE")
    tree.addTopLevelItem(source)
    tree.setCurrentItem(source)
    external = []
    moves = []
    tree.external_paths_dropped.connect(
        lambda paths, target: external.append((paths, target))
    )
    tree.move_requested.connect(
        lambda item_id, parent_id, ordinal: moves.append(
            (item_id, parent_id, ordinal)
        )
    )
    first = tmp_path / "a.txt"
    second = tmp_path / "folder"

    class Mime:
        def __init__(self, urls=()):
            self._urls = urls

        def hasUrls(self):
            return bool(self._urls)

        def urls(self):
            return self._urls

    class Event:
        def __init__(self, mime, event_source=None):
            self._mime = mime
            self._source = event_source
            self.accepted = False

        def mimeData(self):
            return self._mime

        def source(self):
            return self._source

        def position(self):
            return QPointF(10000, 10000)

        def acceptProposedAction(self):
            self.accepted = True

        def ignore(self):
            self.accepted = False

    external_event = Event(
        Mime((QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))))
    )
    tree.dropEvent(external_event)
    assert external_event.accepted is True
    assert external == [((first.absolute(), second.absolute()), None)]

    internal_event = Event(Mime(), tree)
    tree.dropEvent(internal_event)
    assert internal_event.accepted is True
    assert moves == [("source-id", None, 1)]
