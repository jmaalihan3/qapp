"""
Tests for the QApp Notes API using FastAPI's TestClient.
Covers create, list, and delete operations.
"""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

# Use an in-memory-style temp DB so tests don't pollute the real database.
TEST_DB = os.path.join(os.path.dirname(__file__), "test_notes.db")


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Replace the production DB path with a temporary test DB for each test."""
    from app import main

    monkeypatch.setattr(main, "DB_PATH", TEST_DB)
    main.init_db()
    yield
    # Tear down: remove test database after each test
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest.fixture()
def client():
    """Provide a fresh TestClient for each test."""
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


def test_list_notes_empty(client):
    """GET /notes on a fresh DB returns an empty list."""
    res = client.get("/notes")
    assert res.status_code == 200
    assert res.json() == []


def test_create_note(client):
    """POST /notes creates a note and returns it with an id."""
    payload = {"title": "Hello", "body": "World"}
    res = client.post("/notes", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Hello"
    assert data["body"] == "World"
    assert "id" in data


def test_create_note_without_body(client):
    """POST /notes with only a title defaults body to empty string."""
    res = client.post("/notes", json={"title": "No body"})
    assert res.status_code == 201
    assert res.json()["body"] == ""


def test_list_notes_after_create(client):
    """GET /notes returns all created notes, newest first."""
    client.post("/notes", json={"title": "First"})
    client.post("/notes", json={"title": "Second"})
    res = client.get("/notes")
    titles = [n["title"] for n in res.json()]
    assert titles == ["Second", "First"]


def test_delete_note(client):
    """DELETE /notes/{id} removes the note from the database."""
    create_res = client.post("/notes", json={"title": "To delete"})
    note_id = create_res.json()["id"]

    del_res = client.delete(f"/notes/{note_id}")
    assert del_res.status_code == 204

    # Verify it's gone
    notes = client.get("/notes").json()
    assert all(n["id"] != note_id for n in notes)


def test_delete_nonexistent_note(client):
    """DELETE /notes/{id} returns 404 when the note doesn't exist."""
    res = client.delete("/notes/99999")
    assert res.status_code == 404


def test_index_returns_html(client):
    """GET / serves the HTML frontend."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "QApp Notes" in res.text
