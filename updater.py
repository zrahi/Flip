"""In-app updates: checks GitHub for a newer Flip.exe, downloads it and swaps it in."""

import logging
import subprocess
import sys
import threading

from paths import DATA, RES

log = logging.getLogger("flip")

REPO = "zrahi/Flip"


def current_version():
    try:
        return (RES / "version.txt").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def _parse(version):
    try:
        return tuple(int(x) for x in str(version).lstrip("v").split("."))
    except ValueError:
        return ()


class Updater:
    def __init__(self):
        self.version = current_version()
        self.status = {"state": "idle", "progress": None}
        self._latest = None

    def check(self):
        """{"available": bool, "version", "notes"} for the newest release on GitHub."""
        from engine import _get_json

        try:
            release = _get_json(f"https://api.github.com/repos/{REPO}/releases/latest")
        except Exception as e:
            log.warning("Update check failed: %s", e)
            return {"available": False, "current": self.version}
        exe = next((a for a in release.get("assets", []) if a["name"].lower() == "flip.exe"), None)
        latest = release.get("tag_name", "")
        newer = bool(_parse(latest)) and (self.version == "dev" or _parse(latest) > _parse(self.version))
        self._latest = {"version": latest.lstrip("v"), "url": exe and exe["browser_download_url"],
                        "notes": (release.get("body") or "").strip()[:600]}
        available = newer and exe is not None and getattr(sys, "frozen", False)
        return {"available": available, "current": self.version, "version": self._latest["version"],
                "notes": self._latest["notes"]}

    def install(self, quit_app):
        """Downloads the new Flip.exe in the background, then restarts into it."""
        if not self._latest or not self._latest["url"] or not getattr(sys, "frozen", False):
            return False
        threading.Thread(target=self._install, args=(quit_app,), daemon=True).start()
        return True

    def _install(self, quit_app):
        from engine import download

        folder = DATA / "update"
        folder.mkdir(exist_ok=True)
        new_exe = folder / "Flip.exe"
        try:
            self.status = {"state": "downloading", "progress": 0}
            download(self._latest["url"], new_exe,
                     lambda d, t: self.__setattr__("status", {"state": "downloading", "progress": d / t if t else None}))
            exe = sys.executable
            # A little script that waits for this Flip to close, puts the new one in its place and starts it.
            script = folder / "apply.bat"
            script.write_text(
                "@echo off\r\n"
                "set tries=0\r\n"
                ":again\r\n"
                "ping 127.0.0.1 -n 2 > nul\r\n"
                f'move /y "{new_exe}" "{exe}" > nul 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                "  set /a tries+=1\r\n"
                "  if %tries% lss 30 goto again\r\n"
                "  exit /b 1\r\n"
                ")\r\n"
                f'start "" "{exe}"\r\n',
                encoding="utf-8",
            )
            subprocess.Popen(["cmd.exe", "/c", str(script)], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            self.status = {"state": "restarting", "progress": 1}
            log.info("Updating to %s", self._latest["version"])
            quit_app()
        except Exception as e:
            log.exception("Update failed")
            self.status = {"state": "error", "progress": None, "error": str(e)}
