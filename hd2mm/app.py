"""프로그램 시작점: 서버를 띄우고 Edge 앱 창(없으면 기본 브라우저)으로 화면을 연다."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME, LEGACY_APP_NAME, __version__, gameinfo
from .core import Library, write_json
from .server import AppServer

PREFERRED_PORT = 47815
log = logging.getLogger("hd2mm")
_mutex_handles = []


def acquire_instance_mutex(data_dir: Path) -> bool:
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    normalized = os.path.normpath(str(data_dir.resolve())).lower()
    name = f"Local\\{APP_NAME}-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    handle = kernel32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handles.append(handle)  # 프로세스가 끝날 때까지 핸들을 유지한다.
    return True


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "hd2mm" / "web"


def default_data_dir() -> Path:
    """exe 옆에 ModocracyData 폴더가 있으면 그곳(휴대용), 아니면 %LOCALAPPDATA%\\Modocracy."""
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if exe_dir and (exe_dir / "ModocracyData").is_dir():
        return exe_dir / "ModocracyData"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def migrate_legacy_data(data_dir: Path) -> bool:
    """이름을 바꾸기 전 보관 폴더(%LOCALAPPDATA%\\HD2ModManager)가 있으면 새 위치로 옮긴다.

    옮길 필요가 없거나 옮겼으면 True, 옛 폴더가 사용 중이라 옮기지 못했으면 False.
    """
    legacy = data_dir.parent / LEGACY_APP_NAME
    if data_dir.exists() or not (legacy / "settings.json").is_file():
        return True
    try:
        settings = json.loads((legacy / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(settings, dict) or "mods" not in settings or "gamePath" not in settings:
        return True  # 이름이 같은 다른 프로그램의 폴더일 수 있으니 건드리지 않는다
    try:
        os.replace(legacy, data_dir)
    except OSError:
        return False
    return True


def setup_logging(data_dir: Path, verbose: bool) -> None:
    handler = RotatingFileHandler(data_dir / "log.txt", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def open_window(url: str) -> None:
    edge = gameinfo.find_edge()
    if edge:
        try:
            subprocess.Popen(
                [edge, f"--app={url}", "--no-first-run", "--no-default-browser-check"],
                creationflags=gameinfo.CREATE_NO_WINDOW,
            )
            return
        except OSError:
            log.exception("Edge 실행 실패, 기본 브라우저로 엽니다.")
    webbrowser.open(url)


def running_instance(data_dir: Path) -> str | None:
    """이미 실행 중인 매니저가 있으면 그 주소를 돌려준다."""
    try:
        info = json.loads((data_dir / "instance.json").read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(info['port'])}/"
        with urllib.request.urlopen(url + "api/ping", timeout=1.5) as res:
            ping = json.loads(res.read().decode("utf-8"))
        if ping.get("app") == "hd2mm" and ping.get("dataDir") == str(data_dir):
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def create_server(library: Library, port: int, auto_exit: bool) -> AppServer:
    for candidate in (port, 0) if port else (0,):
        try:
            return AppServer(("127.0.0.1", candidate), library, web_dir(), auto_exit=auto_exit)
        except OSError:
            continue
    raise OSError("사용할 수 있는 포트가 없어요.")


def show_error(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - Helldivers 2 모드 매니저")
    parser.add_argument("--data-dir", help=f"모드 보관 폴더 (기본: %%LOCALAPPDATA%%\\{APP_NAME})")
    parser.add_argument("--port", type=int, default=PREFERRED_PORT)
    parser.add_argument("--no-window", action="store_true", help="창을 열지 않고 서버만 실행 (개발용)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    custom_dir = args.data_dir or os.environ.get("HD2MM_DATA_DIR")
    data_dir = Path(custom_dir or default_data_dir()).resolve()
    try:
        acquired = acquire_instance_mutex(data_dir)
    except OSError as exc:
        show_error(f"실행 중인 모드 매니저를 확인하지 못했어요.\n\n{exc}")
        return 1
    if not acquired:
        if args.no_window:
            log.error("같은 보관함의 모드 매니저가 이미 실행 중이에요.")
            return 1
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            existing = running_instance(data_dir)
            if existing:
                open_window(existing + "?app=1")
                return 0
            time.sleep(0.2)
        show_error("실행 중인 모드 매니저가 응답하지 않아요. 잠시 후 다시 실행해 주세요.")
        return 1
    if not custom_dir and not migrate_legacy_data(data_dir):
        show_error("이전 버전(HD2ModManager)이 실행 중이라 설정을 옮기지 못했어요.\n이전 버전 창을 닫고 다시 실행해 주세요.")
        return 1
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        setup_logging(data_dir, args.verbose)
    except OSError as exc:
        show_error(f"모드 보관 폴더를 만들 수 없어요:\n{data_dir}\n\n{exc}")
        return 1

    existing = running_instance(data_dir)
    if existing:
        if args.no_window:
            log.error("같은 보관함의 모드 매니저가 이미 실행 중이에요.")
            return 1
        open_window(existing + "?app=1")
        return 0

    try:
        library = Library(data_dir)
        if not library.game_path:
            library.set_game_path(gameinfo.detect_game_path())
        server = create_server(library, args.port, auto_exit=not args.no_window)
    except Exception as exc:  # noqa: BLE001 - 창 없이 실행되므로 메시지 상자로 알림
        log.exception("시작 실패")
        show_error(f"모드 매니저를 시작하지 못했어요.\n\n{exc}")
        return 1

    url = f"http://127.0.0.1:{server.port}/"
    instance_file = data_dir / "instance.json"
    write_json(instance_file, {"port": server.port, "pid": os.getpid()})
    log.info("%s %s 시작: %s (보관 폴더 %s)", APP_NAME, __version__, url, data_dir)
    if not args.no_window:
        open_window(url + "?app=1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        instance_file.unlink(missing_ok=True)
    return 0
