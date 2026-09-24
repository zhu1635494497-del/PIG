from __future__ import annotations

import os
import platform
import stat
import subprocess
from pathlib import Path

from pig.application.errors import ApplicationError


class SystemFileOpener:
    """Hand a verified local file to the host association without a shell."""

    def open(self, path: Path) -> None:
        target = Path(path)
        if not target.is_absolute():
            raise ApplicationError(
                code="OS_OPEN_FAILED",
                message="open target must be absolute",
            )
        try:
            target_stat = target.lstat()
        except OSError as exc:
            raise ApplicationError(
                code="OS_OPEN_FAILED",
                message="open target is no longer available",
            ) from exc
        if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
            raise ApplicationError(
                code="OS_OPEN_FAILED",
                message="open target must be a non-symbolic-link regular file",
            )

        system = platform.system()
        try:
            if system == "Windows":
                startfile = getattr(os, "startfile", None)
                if startfile is None:
                    raise OSError("os.startfile is unavailable")
                startfile(str(target))
                return
            command = (
                ["open", str(target)]
                if system == "Darwin"
                else ["xdg-open", str(target)]
                if system == "Linux"
                else None
            )
            if command is None:
                raise OSError("unsupported host operating system")
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
            )
        except OSError as exc:
            raise ApplicationError(
                code="OS_OPEN_FAILED",
                message="host file association could not be started",
            ) from exc
