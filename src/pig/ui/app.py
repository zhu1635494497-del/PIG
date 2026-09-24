from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from pig.bootstrap import create_local_application
from pig.diagnostics.packaged_flow import run_packaged_flow
from pig.ui.main_window import MainWindow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PIG V1 desktop application")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        help="absolute root for newly created Project workspaces",
    )
    parser.add_argument(
        "--seven-zip",
        type=Path,
        help="absolute path to the approved 7-Zip executable used for RAR",
    )
    parser.add_argument(
        "--runtime-smoke-test",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--acceptance-smoke-test",
        type=Path,
        help=argparse.SUPPRESS,
    )
    return parser


def _configure_logging(application_data: Path) -> Path:
    log_directory = application_data / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "pig.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    return log_path


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.runtime_smoke_test or args.acceptance_smoke_test is not None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt = QApplication(sys.argv[:1])
    qt.setApplicationName("PIG")
    qt.setOrganizationName("PIG")

    application_data = (
        Path(tempfile.gettempdir()) / "PIG-runtime-smoke"
        if args.runtime_smoke_test or args.acceptance_smoke_test is not None
        else Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )
        )
    )
    _configure_logging(application_data)
    if args.acceptance_smoke_test is not None:
        run_packaged_flow(args.acceptance_smoke_test)
        return 0
    if args.runtime_smoke_test:
        with tempfile.TemporaryDirectory(prefix="pig-runtime-smoke-") as directory:
            run_packaged_flow(Path(directory).absolute())
        return 0
    workspace_root = (
        args.workspace_root.absolute()
        if args.workspace_root is not None
        else (application_data / "workspace").absolute()
    )
    seven_zip = (
        args.seven_zip.absolute() if args.seven_zip is not None else None
    )
    window = MainWindow(
        create_local_application(
            workspace_root,
            seven_zip_executable=seven_zip,
        ),
        actor=getpass.getuser() or "desktop-user",
    )
    window.show()
    logging.getLogger(__name__).info(
        "desktop window startup: qt_platform=%s visible=%s",
        qt.platformName(),
        window.isVisible(),
    )
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
