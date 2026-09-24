from __future__ import annotations

import os
import time
from datetime import datetime
from threading import Event
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from pig.application import (
    CreateProjectRequest,
    ProcessProjectRequest,
    RegisterSourceRequest,
)
from pig.bootstrap import create_local_application
from pig.domain.enums import NodeFormat, NodeProcessingStatus, SourceKind
from pig.ui.main_window import MainWindow


class RecordingOpener:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def open(self, path: Path) -> None:
        self.paths.append(path)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_window_presents_tree_search_details_and_controlled_open(
    qt_app, tmp_path: Path
) -> None:
    opener = RecordingOpener()
    application = create_local_application(
        (tmp_path / "workspace").absolute(), file_opener=opener
    )
    project = application.create_project(
        CreateProjectRequest(name="Desktop M9", actor="tester")
    )
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF-1.7")
    application.register_source(
        RegisterSourceRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            source_path=source.absolute(),
            source_kind=SourceKind.FILE,
            actor="tester",
        )
    )
    application.process_project(
        ProcessProjectRequest(
            project_id=project.project_id,
            database_path=project.database_path,
            actor="tester",
        )
    )
    window = MainWindow(application, actor="tester")

    window._activate_project(project.project_id, project.database_path)

    assert window.tree.topLevelItemCount() == 1
    item = window.tree.topLevelItem(0)
    item.setSelected(True)
    qt_app.processEvents()
    assert "Logical Path:" in window.details.toPlainText()
    assert "EXTERNAL_SOURCE" in window.details.toPlainText()

    window.search_text.setText("report")
    window.format_filter.set_selected_values((NodeFormat.PDF, NodeFormat.TXT))
    window.status_filter.setCurrentIndex(
        window.status_filter.findData(NodeProcessingStatus.SUCCESS.value)
    )
    window._search()
    assert window.search_results.rowCount() == 1
    assert window.format_filter.text() == "格式：已选 2 项"

    window._search_double_clicked(window.search_results.item(0, 0), 0)
    deadline = time.monotonic() + 10
    while window._worker_thread is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    qt_app.processEvents()
    assert opener.paths == [source.absolute()]
    assert window.events.item(0, 2).text() == "FILE_OPENED"
    datetime.strptime(window.events.item(0, 0).text(), "%Y-%m-%d %H:%M:%S")
    assert "UTC:" in window.events.item(0, 0).toolTip()
    window.close()


def test_manifest_success_uses_a_visible_confirmation(qt_app, tmp_path: Path, monkeypatch) -> None:
    application = create_local_application((tmp_path / "workspace").absolute())
    window = MainWindow(application, actor="tester")
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(
            lambda _parent, title, message: messages.append((title, message))
        ),
    )

    window._manifest_exported(
        SimpleNamespace(
            manifest_path=tmp_path / "manifest.json",
            size=1234,
            sha256="a" * 64,
            included_event_count=42,
        )
    )

    assert messages[0][0] == "Manifest 导出成功"
    assert "1,234 bytes" in messages[0][1]
    assert "包含事件：42" in messages[0][1]
    window.close()


def test_long_action_runs_off_gui_thread_and_disables_mutations(
    qt_app, tmp_path: Path
) -> None:
    application = create_local_application((tmp_path / "workspace").absolute())
    window = MainWindow(application, actor="tester")
    started = Event()
    release = Event()
    results: list[str] = []

    def action() -> str:
        started.set()
        assert release.wait(timeout=5)
        return "done"

    window._run_background("测试长操作", action, results.append)
    deadline = time.monotonic() + 5
    while not started.is_set() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)

    assert started.is_set()
    assert not window.new_project_action.isEnabled()
    window.search_text.setText("UI remains responsive")
    qt_app.processEvents()
    assert window.search_text.text() == "UI remains responsive"

    release.set()
    deadline = time.monotonic() + 5
    while window._worker_thread is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    qt_app.processEvents()
    assert results == ["done"]
    assert window.new_project_action.isEnabled()
    window.close()


def test_new_project_prompts_for_storage_and_displays_final_path(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    default_root = (tmp_path / "default-workspace").absolute()
    selected_root = (tmp_path / "selected-workspace").absolute()
    selected_root.mkdir()
    application = create_local_application(default_root)
    window = MainWindow(application, actor="tester")
    messages: list[tuple[str, str]] = []

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        staticmethod(lambda *_args, **_kwargs: ("用户选择位置", True)),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: str(selected_root)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(
            lambda _parent, title, message: messages.append((title, message))
        ),
    )

    window._new_project()
    deadline = time.monotonic() + 10
    while window._worker_thread is not None and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    qt_app.processEvents()

    assert window._database_path is not None
    assert window._database_path.parent.parent == selected_root / "projects"
    assert window._database_path.is_file()
    assert str(window._database_path.parent) in window.project_location.text()
    assert messages == [
        (
            "项目已创建",
            f"项目已保存到：\n{window._database_path.parent}\n\n"
            f"项目数据库：\n{window._database_path}\n\n"
            f"目录名 {window._project_id} 是项目的内部唯一 ID。",
        )
    ]
    assert not default_root.exists()
    window.close()
