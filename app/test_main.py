"""
Tests for the QApp Notes API.
Covers user registration, login, per-user CRUD, and note isolation between users.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Provide a fresh TestClient for each test."""
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clean_tables():
    """Truncate notes and users before and after each test for isolation."""
    from app.main import get_db, init_db

    init_db()

    def _clean():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM notes")
        cur.execute("DELETE FROM users")
        conn.commit()
        cur.close()
        conn.close()

    _clean()
    yield
    _clean()


def _register(client, username="alice", password="secret123"):
    """Helper: register a user and return the response."""
    return client.post(
        "/register", json={"username": username, "password": password}
    )


def _login(client, username="alice", password="secret123"):
    """Helper: log in and return an Authorization header dict."""
    res = client.post(
        "/token", data={"username": username, "password": password}
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _auth(client, username="alice", password="secret123"):
    """Helper: register + login, return auth headers."""
    _register(client, username, password)
    return _login(client, username, password)


# --------------- Auth Tests ---------------

def test_register(client):
    res = _register(client)
    assert res.status_code == 201
    assert res.json()["detail"] == "User created"


def test_register_duplicate(client):
    _register(client)
    res = _register(client)
    assert res.status_code == 409


def test_login(client):
    _register(client)
    res = client.post("/token", data={"username": "alice", "password": "secret123"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_wrong_password(client):
    _register(client)
    res = client.post("/token", data={"username": "alice", "password": "wrong"})
    assert res.status_code == 401


def test_login_nonexistent_user(client):
    res = client.post("/token", data={"username": "ghost", "password": "nope"})
    assert res.status_code == 401


# --------------- Notes Require Auth ---------------

def test_notes_without_token(client):
    res = client.get("/notes")
    assert res.status_code == 401


def test_create_note_without_token(client):
    res = client.post("/notes", json={"title": "x"})
    assert res.status_code == 401


# --------------- CRUD Tests ---------------

def test_list_notes_empty(client):
    headers = _auth(client)
    res = client.get("/notes", headers=headers)
    assert res.status_code == 200
    assert res.json() == []


def test_create_note(client):
    headers = _auth(client)
    res = client.post("/notes", json={"title": "Hello", "body": "World"}, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Hello"
    assert data["body"] == "World"
    assert "id" in data


def test_create_note_without_body(client):
    headers = _auth(client)
    res = client.post("/notes", json={"title": "No body"}, headers=headers)
    assert res.status_code == 201
    assert res.json()["body"] == ""


def test_list_notes_after_create(client):
    headers = _auth(client)
    client.post("/notes", json={"title": "First"}, headers=headers)
    client.post("/notes", json={"title": "Second"}, headers=headers)
    res = client.get("/notes", headers=headers)
    titles = [n["title"] for n in res.json()]
    assert titles == ["Second", "First"]


def test_delete_note(client):
    headers = _auth(client)
    create_res = client.post("/notes", json={"title": "To delete"}, headers=headers)
    note_id = create_res.json()["id"]

    del_res = client.delete(f"/notes/{note_id}", headers=headers)
    assert del_res.status_code == 204

    notes = client.get("/notes", headers=headers).json()
    assert all(n["id"] != note_id for n in notes)


def test_delete_nonexistent_note(client):
    headers = _auth(client)
    res = client.delete("/notes/99999", headers=headers)
    assert res.status_code == 404


# --------------- User Isolation ---------------

def test_notes_isolated_between_users(client):
    """User A's notes are invisible to User B."""
    headers_a = _auth(client, "alice", "pass1")
    headers_b = _auth(client, "bob", "pass2")

    client.post("/notes", json={"title": "Alice note"}, headers=headers_a)
    client.post("/notes", json={"title": "Bob note"}, headers=headers_b)

    alice_notes = client.get("/notes", headers=headers_a).json()
    bob_notes = client.get("/notes", headers=headers_b).json()

    assert len(alice_notes) == 1
    assert alice_notes[0]["title"] == "Alice note"
    assert len(bob_notes) == 1
    assert bob_notes[0]["title"] == "Bob note"


def test_cannot_delete_other_users_note(client):
    """User B cannot delete User A's note."""
    headers_a = _auth(client, "alice", "pass1")
    headers_b = _auth(client, "bob", "pass2")

    res = client.post("/notes", json={"title": "Alice only"}, headers=headers_a)
    note_id = res.json()["id"]

    del_res = client.delete(f"/notes/{note_id}", headers=headers_b)
    assert del_res.status_code == 404

    alice_notes = client.get("/notes", headers=headers_a).json()
    assert len(alice_notes) == 1


# --------------- Frontend ---------------

def test_index_returns_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "QApp Notes" in res.text
