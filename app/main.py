"""
Minimal full-stack notetaking app built with FastAPI and PostgreSQL.
Serves a single-page HTML frontend and exposes a JSON API for CRUD operations.
"""

import os
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_db():
    """Return a connection to the PostgreSQL database."""
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db() -> None:
    """Create the notes table if it doesn't already exist."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    cur.close()
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


class NoteOut(BaseModel):
    id: int
    title: str
    body: str


# --------------- API Routes ---------------

@app.get("/notes", response_model=list[NoteOut])
def list_notes():
    """Return every note in the database."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, title, body FROM notes ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(note: NoteCreate):
    """Insert a new note and return it with its generated id."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notes (title, body) VALUES (%s, %s) RETURNING id",
        (note.title, note.body),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": new_id, "title": note.title, "body": note.body}


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int):
    """Delete a note by id. Returns 404 if the note doesn't exist."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM notes WHERE id = %s", (note_id,))
    if cur.rowcount == 0:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Note not found")
    conn.commit()
    cur.close()
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

  .note-card button {
    align-self: flex-end;
    background: none;
    border: none;
    color: #ef4444;
    font-size: .85rem;
    font-weight: 600;
    cursor: pointer;
    padding: .25rem .5rem;
    border-radius: 6px;
    transition: background .15s;
  }

  .note-card button:hover { background: #fef2f2; }
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
    notes.forEach(n => {
      const card = document.createElement('div');
      card.className = 'note-card';
      card.innerHTML =
        '<h3>' + esc(n.title) + '</h3>' +
        '<p>'  + esc(n.body)  + '</p>' +
        '<button data-id="' + n.id + '">Delete</button>';
      card.querySelector('button').addEventListener('click', () => deleteNote(n.id));
      notesEl.appendChild(card);
    });
  }

  async function deleteNote(id) {
    await fetch('/notes/' + id, { method: 'DELETE' });
    loadNotes();
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
