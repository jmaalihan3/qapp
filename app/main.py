"""
Minimal full-stack notetaking app built with FastAPI and PostgreSQL.
Serves a single-page HTML frontend and exposes a JSON API for CRUD operations.
Supports per-user notes via OAuth2 password flow with JWT tokens.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def get_db():
    """Return a connection to the PostgreSQL database."""
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db() -> None:
    """Create the users and notes tables if they don't already exist."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
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

class UserCreate(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class NoteCreate(BaseModel):
    title: str
    body: str = ""


class NoteOut(BaseModel):
    id: int
    title: str
    body: str


# --------------- Auth Helpers ---------------

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Decode the JWT and return the user row, or raise 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, username FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user is None:
        raise credentials_exception
    return user


# --------------- Auth Routes ---------------

@app.post("/register", status_code=201)
def register(user: UserCreate):
    """Create a new user account."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username = %s", (user.username,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="Username already taken")
    hashed = hash_password(user.password)
    cur.execute(
        "INSERT INTO users (username, hashed_password) VALUES (%s, %s)",
        (user.username, hashed),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"detail": "User created"}


@app.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate and return a JWT access token."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE username = %s", (form_data.username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer"}


# --------------- Note Routes ---------------

@app.get("/notes", response_model=list[NoteOut])
def list_notes(user: dict = Depends(get_current_user)):
    """Return every note belonging to the authenticated user."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, title, body FROM notes WHERE user_id = %s ORDER BY id DESC",
        (user["id"],),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(note: NoteCreate, user: dict = Depends(get_current_user)):
    """Insert a new note for the authenticated user."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notes (title, body, user_id) VALUES (%s, %s, %s) RETURNING id",
        (note.title, note.body, user["id"]),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": new_id, "title": note.title, "body": note.body}


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, user: dict = Depends(get_current_user)):
    """Delete a note by id, only if it belongs to the authenticated user."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notes WHERE id = %s AND user_id = %s",
        (note_id, user["id"]),
    )
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
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem;
  }

  h1 {
    margin-bottom: 1.5rem;
    font-size: 1.8rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }

  /* --- Auth Panel --- */
  #auth-panel {
    max-width: 380px;
    width: 100%;
    background: #fff;
    border-radius: 12px;
    padding: 2rem 1.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
  }

  #auth-panel h2 {
    font-size: 1.25rem;
    font-weight: 600;
    margin-bottom: 1rem;
    text-align: center;
  }

  #auth-panel form {
    display: flex;
    flex-direction: column;
    gap: .75rem;
  }

  #auth-panel input {
    width: 100%;
    padding: .6rem .75rem;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: .95rem;
    font-family: inherit;
    transition: border-color .15s;
  }

  #auth-panel input:focus {
    outline: none;
    border-color: #6366f1;
    box-shadow: 0 0 0 3px rgba(99,102,241,.15);
  }

  #auth-panel button {
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

  #auth-panel button:hover { background: #4f46e5; }

  #auth-toggle {
    margin-top: .75rem;
    text-align: center;
    font-size: .85rem;
    color: #6b7280;
  }

  #auth-toggle a {
    color: #6366f1;
    cursor: pointer;
    font-weight: 600;
    text-decoration: none;
  }

  #auth-toggle a:hover { text-decoration: underline; }

  #auth-error {
    color: #ef4444;
    font-size: .85rem;
    text-align: center;
    min-height: 1.2em;
  }

  /* --- Top Bar --- */
  #top-bar {
    max-width: 960px;
    width: 100%;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  #top-bar span {
    font-size: .9rem;
    color: #6b7280;
  }

  #top-bar button {
    background: none;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: .35rem .9rem;
    font-size: .85rem;
    font-weight: 600;
    color: #374151;
    cursor: pointer;
    transition: background .15s;
  }

  #top-bar button:hover { background: #f3f4f6; }

  /* --- Form --- */
  #note-form {
    max-width: 520px;
    width: 100%;
    background: #fff;
    border-radius: 12px;
    padding: 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
    display: flex;
    flex-direction: column;
    gap: .75rem;
    margin-bottom: 2rem;
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
    width: 100%;
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

  .note-card h3 { font-size: 1.05rem; font-weight: 600; }

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

  .hidden { display: none !important; }
</style>
</head>
<body>

<h1>QApp Notes</h1>

<!-- Auth Panel -->
<div id="auth-panel">
  <h2 id="auth-title">Log In</h2>
  <form id="auth-form">
    <input id="auth-user" type="text" placeholder="Username" required>
    <input id="auth-pass" type="password" placeholder="Password" required>
    <button type="submit" id="auth-btn">Log In</button>
  </form>
  <p id="auth-error"></p>
  <p id="auth-toggle">Don't have an account? <a id="toggle-link">Sign up</a></p>
</div>

<!-- App Panel (hidden until logged in) -->
<div id="app-panel" class="hidden" style="width:100%;display:flex;flex-direction:column;align-items:center;">
  <div id="top-bar">
    <span id="greeting"></span>
    <button id="logout-btn">Log Out</button>
  </div>

  <form id="note-form">
    <input id="title" type="text" placeholder="Title" required>
    <textarea id="body" placeholder="Body (optional)"></textarea>
    <button type="submit">Add Note</button>
  </form>

  <div id="notes"></div>
</div>

<script>
  const authPanel  = document.getElementById('auth-panel');
  const appPanel   = document.getElementById('app-panel');
  const authForm   = document.getElementById('auth-form');
  const authTitle  = document.getElementById('auth-title');
  const authBtn    = document.getElementById('auth-btn');
  const authError  = document.getElementById('auth-error');
  const toggleLink = document.getElementById('toggle-link');
  const authUser   = document.getElementById('auth-user');
  const authPass   = document.getElementById('auth-pass');
  const greeting   = document.getElementById('greeting');
  const logoutBtn  = document.getElementById('logout-btn');
  const notesEl    = document.getElementById('notes');
  const noteForm   = document.getElementById('note-form');
  const titleIn    = document.getElementById('title');
  const bodyIn     = document.getElementById('body');

  let isLogin = true;
  let token   = localStorage.getItem('token');
  let username = localStorage.getItem('username');

  function authHeaders() {
    return { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' };
  }

  function showApp() {
    authPanel.classList.add('hidden');
    appPanel.classList.remove('hidden');
    greeting.textContent = 'Logged in as ' + username;
    loadNotes();
  }

  function showAuth() {
    appPanel.classList.add('hidden');
    authPanel.classList.remove('hidden');
    authError.textContent = '';
  }

  toggleLink.addEventListener('click', () => {
    isLogin = !isLogin;
    authTitle.textContent = isLogin ? 'Log In' : 'Sign Up';
    authBtn.textContent   = isLogin ? 'Log In' : 'Sign Up';
    toggleLink.textContent = isLogin ? 'Sign up' : 'Log in';
    document.getElementById('auth-toggle').firstChild.textContent =
      isLogin ? "Don't have an account? " : "Already have an account? ";
    authError.textContent = '';
  });

  authForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    authError.textContent = '';
    const u = authUser.value.trim();
    const p = authPass.value;

    if (isLogin) {
      const res = await fetch('/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'username=' + encodeURIComponent(u) + '&password=' + encodeURIComponent(p)
      });
      if (!res.ok) {
        const err = await res.json();
        authError.textContent = err.detail || 'Login failed';
        return;
      }
      const data = await res.json();
      token = data.access_token;
      username = u;
      localStorage.setItem('token', token);
      localStorage.setItem('username', username);
      showApp();
    } else {
      const res = await fetch('/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p })
      });
      if (!res.ok) {
        const err = await res.json();
        authError.textContent = err.detail || 'Registration failed';
        return;
      }
      // Auto-login after successful registration
      const loginRes = await fetch('/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'username=' + encodeURIComponent(u) + '&password=' + encodeURIComponent(p)
      });
      const data = await loginRes.json();
      token = data.access_token;
      username = u;
      localStorage.setItem('token', token);
      localStorage.setItem('username', username);
      showApp();
    }
  });

  logoutBtn.addEventListener('click', () => {
    token = null;
    username = null;
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    authUser.value = '';
    authPass.value = '';
    showAuth();
  });

  async function loadNotes() {
    const res = await fetch('/notes', { headers: authHeaders() });
    if (res.status === 401) { logoutBtn.click(); return; }
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
    await fetch('/notes/' + id, { method: 'DELETE', headers: authHeaders() });
    loadNotes();
  }

  noteForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await fetch('/notes', {
      method: 'POST',
      headers: authHeaders(),
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

  // On page load: if we have a saved token, try to use it
  if (token) {
    fetch('/notes', { headers: authHeaders() }).then(r => {
      if (r.ok) { showApp(); }
      else { localStorage.removeItem('token'); localStorage.removeItem('username'); showAuth(); }
    });
  } else {
    showAuth();
  }
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
