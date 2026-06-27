"""
Pytest-Fixtures: startet den Mock-ZAW und die ECHTE Vercel-Function (api/index.py)
als lokale HTTP-Server, damit Tests gegen die Produktionslogik laufen – ohne die
echte ZAW-API zu treffen und ohne nach Vercel zu deployen.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from http.server import ThreadingHTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# tests/ und Repo-Root auf den Importpfad
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_zaw  # noqa: E402


def _load_app_handler():
    """Lädt die echte Handler-Klasse aus api/index.py (ohne Namenskollision)."""
    path = os.path.join(ROOT, "api", "index.py")
    spec = importlib.util.spec_from_file_location("app_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def mock_zaw_server():
    """Startet den Mock-ZAW und verdrahtet ZAW_API_BASE."""
    server, base_url, counter = mock_zaw.start_mock()
    os.environ["ZAW_API_BASE"] = base_url
    yield {"base_url": base_url, "counter": counter}
    server.shutdown()
    os.environ.pop("ZAW_API_BASE", None)


@pytest.fixture(scope="session")
def app_server(mock_zaw_server):
    """Startet die echte Vercel-Function als lokalen HTTP-Server.

    Gibt die Basis-URL (z.B. http://127.0.0.1:PORT) zurück.
    """
    app = _load_app_handler()

    class QuietHandler(app.handler):
        def log_message(self, *args):  # keine Konsolen-Logs
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture()
def reset_counter(mock_zaw_server):
    """Setzt den Upstream-Request-Zähler vor dem Test zurück."""
    mock_zaw_server["counter"].reset()
    return mock_zaw_server["counter"]


# ---- Playwright: headless, kein --base-url nötig ---------------------------- #
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    # Klemmt das Standardviewport fest; deterministischer.
    return {**browser_context_args, "viewport": {"width": 1000, "height": 1400}}
