from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_app_database(monkeypatch, tmp_path):
    monkeypatch.setenv("FVD_DB_PATH", str(tmp_path / "app.sqlite3"))
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-auth-secret-with-at-least-32-bytes")
    yield
