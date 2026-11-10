from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_REQUIRED_MODULES = ("fastapi", "httpx", "dotenv", "langgraph", "requests")
_MISSING_MODULES = [name for name in _REQUIRED_MODULES if importlib.util.find_spec(name) is None]

if not _MISSING_MODULES:
    from fastapi.testclient import TestClient

    from app import main as app_module


@unittest.skipIf(_MISSING_MODULES, f"application dependencies unavailable: {_MISSING_MODULES}")
class FrontendServingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dist = Path(self.temp_dir.name) / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<!doctype html><title>SentinelP2P test</title>", encoding="utf-8")
        (self.dist / "assets").mkdir()
        (self.dist / "assets" / "app.js").write_text("window.testApp = true;", encoding="utf-8")
        self.dist_patch = patch.object(app_module, "FRONTEND_DIST", self.dist)
        self.index_patch = patch.object(app_module, "FRONTEND_INDEX", self.dist / "index.html")
        self.dist_patch.start()
        self.index_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.index_patch.stop()
        self.dist_patch.stop()
        self.temp_dir.cleanup()

    def test_api_health_remains_available(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_root_serves_built_react_entry(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SentinelP2P test", response.text)

    def test_client_side_route_returns_react_entry(self) -> None:
        response = self.client.get("/vendor-intelligence/vendors/VEN001")
        self.assertEqual(response.status_code, 200)
        self.assertIn("SentinelP2P test", response.text)

    def test_built_asset_is_served_from_dist(self) -> None:
        response = self.client.get("/assets/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "window.testApp = true;")

    def test_unknown_api_path_remains_json_404(self) -> None:
        response = self.client.get("/api/not-a-route")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "API route not found")

    def test_missing_frontend_build_returns_actionable_error(self) -> None:
        missing = self.dist / "missing"
        with patch.object(app_module, "FRONTEND_DIST", missing), patch.object(
            app_module, "FRONTEND_INDEX", missing / "index.html"
        ):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("npm run build", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
