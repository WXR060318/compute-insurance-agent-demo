from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    path = tmp_path / "demo.sqlite3"
    monkeypatch.setenv("DEMO_DB_PATH", str(path))
    return path


@pytest.fixture
def client(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("AI_MODE", "offline")
    with TestClient(app) as test_client:
        yield test_client
