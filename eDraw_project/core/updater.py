"""Auto-update checker and downloader for eDraw.

Flow:
  1. ``UpdateChecker`` runs in a QThread, calling the GitHub Releases API.
  2. If a newer release exists → emits ``update_available(ReleaseInfo)``.
  3. ``MainWindow`` receives the signal → shows an update badge.
  4. User clicks avatar → ``UpdateDialog`` appears.
  5. If the user confirms → ``UpdateDownloader`` downloads the archive and
     creates a replacement script to swap files and restart the app.
"""

from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from core.i18n import t

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_REPO = "eDrawEDU/edrawedu.github.io"
_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
_SKIP_FILE = Path.home() / ".edraw" / "update_skip.json"
_LOG_FILE = Path.home() / ".edraw" / "update.log"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(
            getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        )
    return Path(__file__).resolve().parent.parent


_VERSION_FILE = _resource_root() / "config" / "version.txt"


def _log(message: str) -> None:
    text = f"[updater] {message}"
    print(text)
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


def _version_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    roots = [_resource_root()]
    for root in roots:
        candidates.append(root / "config" / "version.txt")
        candidates.append(root / "version.txt")
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        app = Path(sys.executable).resolve().parent.parent
        candidates.append(app / "Contents" / "Resources" / "config" / "version.txt")
    return candidates


def _bundle_info_version() -> str:
    """Try to read the version from the macOS app bundle Info.plist."""
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return ""
    try:
        app = Path(sys.executable).resolve().parent.parent
        plist_path = app / "Contents" / "Info.plist"
        if plist_path.is_file():
            with open(plist_path, "rb") as f:
                data = plistlib.load(f)
            ver = data.get("CFBundleShortVersionString", "")
            if ver:
                return str(ver).strip()
    except Exception:
        pass
    return ""


def current_version() -> str:
    """Return the current version string from the version file or bundle."""
    for path in _version_file_candidates():
        if path.is_file():
            try:
                version = path.read_text(encoding="utf-8").strip()
                if version:
                    return version
            except OSError as exc:
                _log(f"khong doc duoc version file {path}: {exc}")
                continue
    bundle_ver = _bundle_info_version()
    if bundle_ver:
        return bundle_ver
    return ""


def _version_tuple(v: str) -> tuple[int, ...]:
    """Convert a version string like ``'1.2.3'`` to ``(1, 2, 3)``."""
    if not v:
        return (0,)
    text = v.strip()
    if text.lower().startswith("v"):
        text = text[1:]
    match = re.match(r"(\d+(?:\.\d+)*)", text)
    if not match:
        return (0,)
    return tuple(int(x) for x in match.group(1).split("."))


def _clean_version(tag_or_version: str) -> str | None:
    """Strip a ``v`` prefix and trailing labels, returning ``'1.2.3'`` or *None*."""
    if not tag_or_version:
        return None
    text = tag_or_version.strip()
    if text.lower().startswith("v"):
        text = text[1:]
    match = re.match(r"(\d+(?:\.\d+)*)", text)
    if match:
        return match.group(1)
    return None


def _asset_name() -> str | None:
    """Return the expected GitHub release asset filename for this platform."""
    s = platform.system().lower()
    m = platform.machine().lower()
    if s == "windows":
        return "edraw-windows-x64.zip"
    if s == "darwin":
        if m in ("arm64", "aarch64"):
            return "edraw-macos-arm64.tar.gz"
        return "edraw-macos-x64.tar.gz"
    return None


def _get(url: str) -> dict | list | None:
    """GET JSON from *url*, returning *None* on any error."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "eDraw-Updater/1.0",
                "Accept": "application/vnd.github+json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as exc:
        _log(f"GET {url} loi: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


class ReleaseInfo(NamedTuple):
    """Metadata for a single GitHub release."""

    version: str
    download_url: str
    body: str
    published_at: str


def fetch_latest_release() -> ReleaseInfo | None:
    """Fetch the newest release from GitHub.

    Tries in order:
      1. Releases list API — picks the highest version number.
      2. Latest release API — fallback.
      3. Tags API — fallback.
    Returns *None* if nothing is found.
    """

    def _from_release(data: dict) -> ReleaseInfo | None:
        tag = data.get("tag_name", "")
        ver = _clean_version(tag)
        if not ver:
            return None
        url = data.get("html_url", "")
        body = data.get("body", "") or ""
        published = data.get("published_at", "") or ""
        return ReleaseInfo(
            version=ver, download_url=url, body=body, published_at=published
        )

    # 1. Try the releases list
    releases = _get(_RELEASES_URL)
    if isinstance(releases, list) and releases:
        best: ReleaseInfo | None = None
        best_tuple = (0,)
        for item in releases:
            info = _from_release(item)
            if info:
                tv = _version_tuple(info.version)
                if tv > best_tuple:
                    best_tuple = tv
                    best = info
        if best:
            return best

    # 2. Try latest release
    data = _get(_API_URL)
    if isinstance(data, dict):
        info = _from_release(data)
        if info:
            return info

    # 3. Fallback: tags
    tags_url = f"https://api.github.com/repos/{GITHUB_REPO}/tags?per_page=10"
    tags = _get(tags_url)
    if isinstance(tags, list) and tags:
        for tag_data in tags:
            tag_name = tag_data.get("name", "")
            ver = _clean_version(tag_name)
            if ver:
                return ReleaseInfo(
                    version=ver,
                    download_url="",
                    body="",
                    published_at="",
                )

    return None


def is_newer(latest: ReleaseInfo | None) -> bool:
    """Return *True* if *latest* is newer than the running version."""
    cur = current_version()
    if not latest:
        return False
    if not cur:
        return bool(getattr(sys, "frozen", False))
    return _version_tuple(latest.version) > _version_tuple(cur)


def is_skipped(latest_version: str) -> bool:
    """Return *True* if the user chose 'Don't remind again' for this version
    **and** the current version hasn't changed since then."""
    try:
        data = json.loads(_SKIP_FILE.read_text(encoding="utf-8"))
        if data.get("skipped_version") == latest_version:
            return data.get("from_version") == current_version()
    except Exception:
        pass
    return False


def set_skipped_version(latest_version: str) -> None:
    """Persist the (current_version, skipped_version) pair."""
    try:
        _SKIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SKIP_FILE.write_text(
            json.dumps(
                {
                    "skipped_version": latest_version,
                    "from_version": current_version(),
                }
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Qt workers
# ---------------------------------------------------------------------------


class UpdateChecker(QObject):
    """Runs in a QThread; emits when a newer release is found."""

    update_available = pyqtSignal(object)
    check_done = pyqtSignal()

    def run(self) -> None:
        release = fetch_latest_release()
        if release and is_newer(release) and not is_skipped(release.version):
            self.update_available.emit(release)
        self.check_done.emit()


class UpdateDownloader(QObject):
    """Chạy trong QThread, tải archive và lên lịch thay thế file."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self._release = release
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            self._do_update()
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _do_update(self) -> None:
        if not getattr(sys, "frozen", False):
            self.finished.emit(False, t("Không thể tự cập nhật khi chạy từ mã nguồn."))
            return

        if not self._release.download_url:
            self.finished.emit(
                False,
                t(
                    "Không tìm thấy file cài đặt cho nền tảng này ({asset}).\nVui lòng tải thủ công tại github.com/eDrawEDU/source/releases.",
                    asset=_asset_name(),
                ),
            )
            return

        tmp = tempfile.mkdtemp(prefix="edraw_upd_")
        name = _asset_name()
        archive = os.path.join(tmp, name)

        req = urllib.request.Request(
            self._release.download_url,
            headers={"User-Agent": "eDraw-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=180.0) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            with open(archive, "wb") as f:
                while True:
                    if self._cancelled:
                        self.finished.emit(False, t("Đã hủy cập nhật."))
                        return
                    buf = resp.read(65536)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    self.progress.emit(done, total)

        ext_dir = os.path.join(tmp, "x")
        os.makedirs(ext_dir, exist_ok=True)
        self._extract_archive(archive, ext_dir)

        system = platform.system().lower()
        src = self._find_extracted_app(ext_dir, system)
        if not src:
            for nested_archive in self._nested_archives(ext_dir):
                nested_dir = os.path.join(tmp, f"nested_{nested_archive.stem}")
                os.makedirs(nested_dir, exist_ok=True)
                self._extract_archive(str(nested_archive), nested_dir)
                src = self._find_extracted_app(nested_dir, system)
                if src:
                    break

        if not src:
            expected = "eDraw.app" if system == "darwin" else "eDraw"
            raise RuntimeError(
                t("Không tìm thấy '{expected}' trong gói cập nhật.", expected=expected)
            )

        packaged_version = self._read_extracted_version(src, system)
        if system == "linux" and not packaged_version:
            self._write_extracted_version(src, self._release.version)
            packaged_version = self._read_extracted_version(src, system)
            if packaged_version:
                _log(f"goi cap nhat Linux thieu version.txt; da bo sung v{self._release.version} vao staging")
            else:
                _log("goi cap nhat Linux thieu version.txt; tiep tuc cai dat")

        if packaged_version and _clean_version(packaged_version) != self._release.version:
            raise RuntimeError(
                t(
                    "Gói cập nhật không khớp phiên bản: release v{release_version}, trong gói là v{package_version}.",
                    release_version=self._release.version,
                    package_version=packaged_version,
                )
            )

        exe_path = Path(sys.executable).resolve()
        exe = str(exe_path)
        if system == "darwin":
            app_bundle = exe_path.parent.parent.parent
            dest_parent = str(app_bundle.parent)
            dest_name = app_bundle.name
        elif system == "linux":
            app_dir = exe_path.parent
            outer_dir = app_dir.parent
            if app_dir.name == outer_dir.name and (outer_dir / "_internal").is_dir():
                dest_parent = str(outer_dir.parent)
                dest_name = outer_dir.name
            else:
                dest_parent = str(app_dir.parent)
                dest_name = app_dir.name
        else:
            dest_parent = str(exe_path.parent)
            dest_name = ""

        self._schedule(src, dest_parent, dest_name, exe, tmp, system)
        self.finished.emit(True, "")

    def _extract_archive(self, archive: str, dest: str) -> None:
        if archive.endswith(".zip"):
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(dest)
        else:
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(dest)

    def _find_extracted_app(self, root: str, system: str) -> str | None:
        root_path = Path(root)
        if system == "darwin":
            for path in root_path.rglob("eDraw.app"):
                if path.is_dir():
                    return str(path)
            return None

        if system == "windows":
            for path in root_path.rglob("eDraw.exe"):
                if path.is_file():
                    return str(path.parent)
            return None

        exe_name = "eDraw"
        for path in root_path.rglob(exe_name):
            if path.is_file():
                return str(path.parent)
        return None

    def _read_extracted_version(self, app_root: str, system: str) -> str:
        root = Path(app_root)
        candidates = [
            root / "_internal" / "config" / "version.txt",
            root / "config" / "version.txt",
        ]
        if system == "darwin":
            candidates.insert(
                0,
                root / "Contents" / "Resources" / "config" / "version.txt",
            )
            candidates.insert(
                1,
                root / "Contents" / "MacOS" / "config" / "version.txt",
            )
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except OSError:
                pass
        return ""

    def _write_extracted_version(self, app_root: str, version: str) -> None:
        root = Path(app_root)
        candidates = [
            root / "_internal" / "config" / "version.txt",
            root / "config" / "version.txt",
        ]
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(version.strip() + "\n", encoding="utf-8")
                return
            except OSError:
                pass

    def _nested_archives(self, root: str) -> list[Path]:
        root_path = Path(root)
        archives = []
        archives.extend(root_path.rglob("*.zip"))
        archives.extend(root_path.rglob("*.tar.gz"))
        return archives

    def _schedule(
        self,
        src: str,
        dest_parent: str,
        dest_name: str,
        exe: str,
        tmp: str,
        system: str,
    ) -> None:
        """Tạo script chờ app thoát, thay thế file, rồi khởi động lại."""
        current_pid = os.getpid()
        exe_name = Path(exe).name

        def sh_quote(value: str) -> str:
            return "'" + value.replace("'", "'\"'\"'") + "'"

        if system == "windows":
            dest = os.path.join(dest_parent, dest_name) if dest_name else dest_parent
            log = str(Path.home() / ".edraw" / "update-install.log")
            script = os.path.join(tmp, "upd.ps1")

            def ps_quote(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            ps1 = (
                f"$ErrorActionPreference = 'Stop'\n$Source = {ps_quote(src)}"
                f"\n$Destination = {ps_quote(dest)}"
                f"\n$Exe = {ps_quote(exe)}"
                f"\n$Log = {ps_quote(log)}"
                f"\n$OldPid = {current_pid}"
                "\n\nNew-Item -ItemType Directory -Force -Path (Split-Path -Parent $Log) | Out-Null\n"
                "function Write-InstallLog([string]$Message) {\n"
                "    Add-Content -Path $Log -Encoding UTF8 -Value (\"[install] \" + $Message)\n"
                "}\n\n"
                "try {\n"
                "    Write-InstallLog \"waiting for old process $OldPid\"\n"
                "    $oldProcess = Get-Process -Id $OldPid -ErrorAction SilentlyContinue\n"
                "    if ($oldProcess) {\n"
                "        $oldProcess.WaitForExit(120000)\n"
                "    }\n"
                "    $oldProcess = Get-Process -Id $OldPid -ErrorAction SilentlyContinue\n"
                "    if ($oldProcess) {\n"
                "        Write-InstallLog \"old process still running, stopping it\"\n"
                "        Stop-Process -Id $OldPid -Force -ErrorAction SilentlyContinue\n"
                "        Start-Sleep -Seconds 2\n"
                "    }\n\n"
                "    Write-InstallLog \"copying from $Source to $Destination\"\n"
                "    & robocopy $Source $Destination /E /R:20 /W:1 /NFL /NDL /NP /NJH /NJS | Out-File -FilePath $Log -Append -Encoding UTF8\n"
                "    $rc = $LASTEXITCODE\n"
                "    Write-InstallLog \"robocopy exit code $rc\"\n"
                "    if ($rc -ge 8) {\n"
                "        throw \"robocopy failed with exit code $rc\"\n"
                "    }\n\n"
                "    Write-InstallLog \"starting app\"\n"
                "    Start-Process -FilePath $Exe -WorkingDirectory (Split-Path -Parent $Exe) -WindowStyle Normal\n"
                "} catch {\n"
                "    Write-InstallLog (\"error: \" + $_.Exception.Message)\n"
                "} finally {\n"
                "    Start-Sleep -Seconds 1\n"
                "    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
                "}\n"
            )
            with open(script, "w", encoding="utf-8-sig") as f:
                f.write(ps1)

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    script,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=startupinfo,
                close_fds=True,
            )
            return

        if system == "darwin":
            dest = os.path.join(dest_parent, dest_name)
            sh = (
                f"#!/bin/bash\n"
                f"while kill -0 {current_pid} 2>/dev/null; do sleep 1; done\n"
                f"rm -rf {sh_quote(dest)}\n"
                f"cp -R {sh_quote(src)} {sh_quote(dest_parent + '/')}\n"
                f"open {sh_quote(dest)}\n"
                f"rm -- \"$0\"\n"
            )
            script = os.path.join(tmp, "upd.sh")
            with open(script, "w") as f:
                f.write(sh)
            os.chmod(script, 493)
            subprocess.Popen(["bash", script])
            return

        # Linux
        dest = os.path.join(dest_parent, dest_name) if dest_name else dest_parent
        log = str(Path.home() / ".edraw" / "update-install.log")
        sh = (
            f"#!/bin/bash\nset -euo pipefail\n\n"
            f"Source={sh_quote(src)}\n"
            f"Destination={sh_quote(dest)}\n"
            f"ExeName={sh_quote(exe_name)}\n"
            f"Log={sh_quote(log)}\n"
            f"OldPid={current_pid}\n"
            "DesktopName='edraw.desktop'\n"
            "Stage=\"${Destination}.new.$$\"\n"
            "Backup=\"${Destination}.old.$$\"\n\n"
            "mkdir -p \"$(dirname \"$Log\")\"\n"
            "cd \"$(dirname \"$Destination\")\"\n"
            "write_log() {\n"
            "    printf '[install] %s\n' \"$1\" >> \"$Log\"\n"
            "}\n"
            "desktop_quote() {\n"
            "    printf '%s' \"$1\" | sed 's/\\\\/\\\\\\\\/g; s/\"/\\\"/g; s/`/\\`/g; s/\\$/\\$/g'\n"
            "}\n"
            "install_desktop_entry() {\n"
            "    app_dir=\"$1\"\n"
            "    exe_path=\"$app_dir/$ExeName\"\n"
            "    icon_path=\"$app_dir/_internal/assets/iconEDraw.png\"\n"
            "    [ -f \"$icon_path\" ] || icon_path=\"$app_dir/assets/iconEDraw.png\"\n"
            "    if [ ! -x \"$exe_path\" ] || [ ! -f \"$icon_path\" ]; then\n"
            "        write_log \"desktop entry skipped: missing exe or icon\"\n"
            "        return 0\n"
            "    fi\n"
            "    data_home=\"${XDG_DATA_HOME:-$HOME/.local/share}\"\n"
            "    app_dir_target=\"$data_home/applications\"\n"
            "    mkdir -p \"$app_dir_target\"\n"
            "    desktop_target=\"$app_dir_target/$DesktopName\"\n"
            "    desktop_local=\"$app_dir/eDraw.desktop\"\n"
            "    exec_escaped=\"$(desktop_quote \"$exe_path\")\"\n"
            "    icon_escaped=\"$(desktop_quote \"$icon_path\")\"\n"
            "    for desktop_file in \"$desktop_target\" \"$desktop_local\"; do\n"
            "        cat > \"$desktop_file\" <<EOF\n"
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=eDraw\n"
            "Comment=eDraw desktop whiteboard\n"
            "Exec=\"$exec_escaped\"\n"
            "Icon=$icon_escaped\n"
            "Terminal=false\n"
            "Categories=Education;Graphics;\n"
            "StartupNotify=true\n"
            "StartupWMClass=eDraw\n"
            "EOF\n"
            "        chmod 755 \"$desktop_file\" || true\n"
            "    done\n"
            "    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database \"$app_dir_target\" >/dev/null 2>&1 || true\n"
            "    write_log \"desktop entry updated: $desktop_target\"\n"
            "}\n"
            "restore_on_error() {\n"
            "    rc=$?\n"
            "    if [ \"$rc\" -ne 0 ]; then\n"
            "        write_log \"error: installer exited with code $rc\"\n"
            "        if [ -d \"$Backup\" ] && [ ! -d \"$Destination\" ]; then\n"
            "            mv \"$Backup\" \"$Destination\" || true\n"
            "            write_log \"restored backup\"\n"
            "        fi\n"
            "    fi\n"
            "    rm -rf \"$Stage\"\n"
            "    rm -- \"$0\" 2>/dev/null || true\n"
            "}\n"
            "trap restore_on_error EXIT\n\n"
            "write_log \"waiting for old process $OldPid\"\n"
            "for _ in $(seq 1 120); do\n"
            "    if kill -0 \"$OldPid\" 2>/dev/null; then\n"
            "        sleep 1\n"
            "    else\n"
            "        break\n"
            "    fi\n"
            "done\n"
            "if kill -0 \"$OldPid\" 2>/dev/null; then\n"
            "    write_log \"old process still running, terminating it\"\n"
            "    kill \"$OldPid\" 2>/dev/null || true\n"
            "    sleep 2\n"
            "fi\n\n"
            "if [ ! -f \"$Source/$ExeName\" ]; then\n"
            "    write_log \"missing executable: $Source/$ExeName\"\n"
            "    exit 1\n"
            "fi\n"
            "chmod +x \"$Source/$ExeName\" || true\n"
            "if [ ! -x \"$Source/$ExeName\" ]; then\n"
            "    write_log \"executable is not runnable: $Source/$ExeName\"\n"
            "    exit 1\n"
            "fi\n\n"
            "rm -rf \"$Stage\" \"$Backup\"\n"
            "mkdir -p \"$Stage\"\n"
            "write_log \"copying new app from $Source to $Stage\"\n"
            "cp -a \"$Source/.\" \"$Stage/\"\n"
            "chmod +x \"$Stage/$ExeName\"\n"
            "if [ ! -f \"$Stage/$ExeName\" ]; then\n"
            "    write_log \"invalid staged app: $Stage/$ExeName is not a file\"\n"
            "    exit 1\n"
            "fi\n"
            "if [ -f \"$Stage/_internal/config/version.txt\" ]; then\n"
            "    write_log \"new version $(cat \"$Stage/_internal/config/version.txt\")\"\n"
            "fi\n\n"
            "if [ -d \"$Destination\" ]; then\n"
            "    write_log \"moving current app to backup $Backup\"\n"
            "    mv \"$Destination\" \"$Backup\"\n"
            "fi\n"
            "write_log \"activating $Stage -> $Destination\"\n"
            "mv \"$Stage\" \"$Destination\"\n"
            "rm -rf \"$Backup\"\n"
            "install_desktop_entry \"$Destination\" || write_log \"desktop entry update failed\"\n\n"
            "write_log \"starting $Destination/$ExeName\"\n"
            "nohup \"$Destination/$ExeName\" >/dev/null 2>&1 &\n"
        )
        script = os.path.join(tmp, "upd.sh")
        with open(script, "w") as f:
            f.write(sh)
        os.chmod(script, 493)
        subprocess.Popen(["bash", script])

