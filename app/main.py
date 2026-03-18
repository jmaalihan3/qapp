"""
Minimal full-stack notetaking app built with FastAPI and SQLite.
Serves a single-page HTML frontend and exposes a JSON API for CRUD operations.
"""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "notes.db"


def get_db() -> sqlite3.Connection:
    """Return a connection to the SQLite database with row-factory enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the notes table if it doesn't already exist."""
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup."""
    init_db()
    yield


app = FastAPI(title="QApp Notes", lifespan=lifespan)


# --------------- Models ---------------

class NoteCreate(BaseModel):
    title: str
    body: str = ""


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None


class NoteOut(BaseModel):
    id: int
    title: str
    body: str


# --------------- API Routes ---------------

@app.get("/notes", response_model=list[NoteOut])
def list_notes():
    """Return every note in the database."""
    conn = get_db()
    rows = conn.execute("SELECT id, title, body FROM notes ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(note: NoteCreate):
    """Insert a new note and return it with its generated id."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO notes (title, body) VALUES (?, ?)",
        (note.title, note.body),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "title": note.title, "body": note.body}


@app.put("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, updates: NoteUpdate):
    """Update a note's title and/or body. Returns 404 if the note doesn't exist."""
    if updates.title is None and updates.body is None:
        raise HTTPException(status_code=422, detail="No fields to update")
    conn = get_db()
    row = conn.execute("SELECT id, title, body FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Note not found")
    new_title = updates.title if updates.title is not None else row["title"]
    new_body = updates.body if updates.body is not None else row["body"]
    conn.execute(
        "UPDATE notes SET title = ?, body = ? WHERE id = ?",
        (new_title, new_body, note_id),
    )
    conn.commit()
    conn.close()
    return {"id": note_id, "title": new_title, "body": new_body}


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int):
    """Delete a note by id. Returns 404 if the note doesn't exist."""
    conn = get_db()
    cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Note not found")
    conn.close()


# --------------- Frontend ---------------

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QApp Notes</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #f0f2f5;
    color: #1a1a2e;
    min-height: 100vh;
    padding: 2rem;
  }

  h1 {
    text-align: center;
    margin-bottom: 1.5rem;
    font-size: 1.8rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }

  /* --- Form --- */
  #note-form {
    max-width: 520px;
    margin: 0 auto 2rem;
    background: #fff;
    border-radius: 12px;
    padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
    display: flex;
    flex-direction: column;
    gap: .75rem;
  }

  #note-form input,
  #note-form textarea {
    width: 100%;
    padding: .6rem .75rem;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: .95rem;
    font-family: inherit;
    transition: border-color .15s;
  }

  #note-form input:focus,
  #note-form textarea:focus {
    outline: none;
    border-color: #6366f1;
    box-shadow: 0 0 0 3px rgba(99,102,241,.15);
  }

  #note-form textarea { resize: vertical; min-height: 80px; }

  #note-form button {
    align-self: flex-end;
    padding: .55rem 1.4rem;
    background: #6366f1;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: .95rem;
    font-weight: 600;
    cursor: pointer;
    transition: background .15s;
  }

  #note-form button:hover { background: #4f46e5; }

  /* --- Notes Grid --- */
  #notes {
    max-width: 960px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 1rem;
  }

  .note-card {
    background: #fff;
    border-radius: 12px;
    padding: 1.1rem 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
    display: flex;
    flex-direction: column;
    gap: .5rem;
    transition: box-shadow .15s;
  }

  .note-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.1); }

  .note-card h3 {
    font-size: 1.05rem;
    font-weight: 600;
  }

  .note-card p {
    font-size: .9rem;
    color: #4b5563;
    white-space: pre-wrap;
    flex: 1;
  }

  .note-card .actions {
    display: flex;
    justify-content: flex-end;
    gap: .5rem;
  }

  .note-card .actions button {
    background: none;
    border: none;
    font-size: .85rem;
    font-weight: 600;
    cursor: pointer;
    padding: .25rem .5rem;
    border-radius: 6px;
    transition: background .15s;
  }

  .note-card .btn-edit { color: #6366f1; }
  .note-card .btn-edit:hover { background: #eef2ff; }
  .note-card .btn-delete { color: #ef4444; }
  .note-card .btn-delete:hover { background: #fef2f2; }
  .note-card .btn-save { color: #16a34a; }
  .note-card .btn-save:hover { background: #f0fdf4; }
  .note-card .btn-cancel { color: #6b7280; }
  .note-card .btn-cancel:hover { background: #f3f4f6; }

  .note-card input.edit-title,
  .note-card textarea.edit-body {
    width: 100%;
    padding: .4rem .6rem;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: inherit;
    font-family: inherit;
    transition: border-color .15s;
  }

  .note-card input.edit-title:focus,
  .note-card textarea.edit-body:focus {
    outline: none;
    border-color: #6366f1;
    box-shadow: 0 0 0 3px rgba(99,102,241,.15);
  }

  .note-card textarea.edit-body { resize: vertical; min-height: 60px; }
</style>
</head>
<body>

<h1>QApp Notes</h1>

<form id="note-form">
  <input id="title" type="text" placeholder="Title" required>
  <textarea id="body" placeholder="Body (optional)"></textarea>
  <button type="submit">Add Note</button>
</form>

<div id="notes"></div>

<script>
  const notesEl = document.getElementById('notes');
  const form    = document.getElementById('note-form');
  const titleIn = document.getElementById('title');
  const bodyIn  = document.getElementById('body');

  async function loadNotes() {
    const res   = await fetch('/notes');
    const notes = await res.json();
    notesEl.innerHTML = '';
    notes.forEach(n => renderCard(n));
  }

  function renderCard(n) {
    const card = document.createElement('div');
    card.className = 'note-card';
    card.dataset.id = n.id;
    card.innerHTML =
      '<h3>' + esc(n.title) + '</h3>' +
      '<p>'  + esc(n.body)  + '</p>' +
      '<div class="actions">' +
        '<button class="btn-edit">Edit</button>' +
        '<button class="btn-delete">Delete</button>' +
      '</div>';
    card.querySelector('.btn-delete').addEventListener('click', () => deleteNote(n.id));
    card.querySelector('.btn-edit').addEventListener('click', () => startEdit(card, n));
    notesEl.appendChild(card);
  }

  function startEdit(card, n) {
    card.innerHTML =
      '<input class="edit-title" value="' + attr(n.title) + '">' +
      '<textarea class="edit-body">' + esc(n.body) + '</textarea>' +
      '<div class="actions">' +
        '<button class="btn-cancel">Cancel</button>' +
        '<button class="btn-save">Save</button>' +
      '</div>';
    card.querySelector('.btn-cancel').addEventListener('click', () => {
      card.innerHTML = '';
      card.remove();
      renderCard(n);
    });
    card.querySelector('.btn-save').addEventListener('click', async () => {
      const title = card.querySelector('.edit-title').value;
      const body  = card.querySelector('.edit-body').value;
      const res = await fetch('/notes/' + n.id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, body })
      });
      if (res.ok) { const updated = await res.json(); card.innerHTML = ''; card.remove(); renderCard(updated); }
    });
    card.querySelector('.edit-title').focus();
  }

  async function deleteNote(id) {
    await fetch('/notes/' + id, { method: 'DELETE' });
    loadNotes();
  }

  function attr(s) {
    return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await fetch('/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: titleIn.value, body: bodyIn.value })
    });
    titleIn.value = '';
    bodyIn.value  = '';
    loadNotes();
  });

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  loadNotes();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the single-page frontend."""
    return INDEX_HTML


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
