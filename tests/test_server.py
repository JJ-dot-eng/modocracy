"""로컬 서버(화면과 로직 연결) 테스트. 가짜 게임 폴더만 사용한다."""
from __future__ import annotations

import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hd2mm import gameinfo
from hd2mm.app import web_dir
from hd2mm.core import Library
from hd2mm.server import AppServer

ROOT = Path(__file__).resolve().parent.parent
LOADER_ZIP = ROOT / "Bingus-Shared-Loader-v17.zip"


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hd2mm-srv-"))
        self.game = self.tmp / "game"
        (self.game / "data").mkdir(parents=True)
        self.lib = Library(self.tmp / "data")
        self.lib.set_game_path(str(self.game))
        self.server = AppServer(("127.0.0.1", 0), self.lib, web_dir(), auto_exit=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.port}"
        patcher = mock.patch.object(gameinfo, "is_game_running", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, path, body=None, data=None, token=True, headers=None):
        hdrs = dict(headers or {})
        if token:
            hdrs["X-HD2MM-Token"] = self.server.token
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=hdrs, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}")

    def test_index_contains_token(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as res:
            html = res.read().decode()
        self.assertIn(self.server.token, html)
        self.assertNotIn("__HD2MM_TOKEN__", html)

    def test_post_requires_token_and_host(self):
        status, _ = self.request("/api/order", body={"ids": []}, token=False)
        self.assertEqual(status, 403)
        status, _ = self.request("/api/state", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)

    def test_state_without_mods(self):
        status, state = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["status"]["state"], "empty")
        self.assertIsNone(state["game"]["problem"])

    @unittest.skipUnless(LOADER_ZIP.exists(), "예시 모드 zip이 없음")
    def test_import_and_deploy_over_http(self):
        status, result = self.request(f"/api/import?name={LOADER_ZIP.name}", data=LOADER_ZIP.read_bytes())
        self.assertEqual(status, 200, result)
        mod_id = result["id"]

        status, state = self.request("/api/state")
        mod = state["mods"][0]
        self.assertEqual(mod["name"], "Bingus Shared Loader - v17")
        self.assertEqual(mod["files"][0]["target"], "9ba626afa44a3aa3.patch_0")
        self.assertEqual(state["status"]["state"], "pending")
        with urllib.request.urlopen(self.base + mod["icon"], timeout=5) as res:
            self.assertEqual(res.headers["Content-Type"], "image/png")

        (self.game / "data" / "9ba626afa44a3aa3.patch_5").write_bytes(b"other")
        status, result = self.request("/api/deploy", body={"unmanaged": "ask"})
        self.assertEqual(status, 409)
        self.assertEqual(result["needsConfirm"], "unmanaged")
        status, result = self.request("/api/deploy", body={"unmanaged": "move"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["modCount"], 1)
        _, state = self.request("/api/state")
        self.assertEqual(state["status"]["state"], "ok")

        status, _ = self.request(f"/api/mods/{mod_id}", body={"enabled": False})
        self.assertEqual(status, 200)
        _, state = self.request("/api/state")
        self.assertEqual(state["status"]["state"], "dirty")

    def test_mod_file_cannot_escape_mod_folder(self):
        status, _ = self.request("/api/mods/unknown/file?path=../settings.json")
        self.assertEqual(status, 400)

    def test_bad_game_path_is_rejected(self):
        not_game = self.tmp / "not-a-game"
        not_game.mkdir()
        status, result = self.request("/api/settings", body={"gamePath": str(not_game)})
        self.assertEqual(status, 400)
        self.assertIn("data 폴더", result["error"])
        status, _ = self.request("/api/settings", body={"gamePath": str(self.game / "data")})
        self.assertEqual(status, 200)
        self.assertEqual(self.lib.game_path, str(self.game))


if __name__ == "__main__":
    unittest.main()


class LifecycleTests(unittest.TestCase):
    def test_server_stops_after_last_window_closes(self):
        tmp = Path(tempfile.mkdtemp(prefix="hd2mm-life-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        server = AppServer(("127.0.0.1", 0), Library(tmp / "data"), web_dir(), auto_exit=True)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        # 창 하나가 열려 있는 상황: 이벤트 연결 유지
        sock = socket.create_connection(("127.0.0.1", server.port))
        sock.sendall(f"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n\r\n".encode())
        self.assertIn(b"text/event-stream", sock.recv(4096))
        time.sleep(7)
        self.assertTrue(thread.is_alive(), "창이 열려 있는 동안에는 꺼지면 안 됨")

        sock.close()  # 창 닫힘
        thread.join(timeout=20)
        self.assertFalse(thread.is_alive(), "창이 닫히면 스스로 종료해야 함")
