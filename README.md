# QApp Notes

A minimal full-stack notetaking app built with Python FastAPI and SQLite.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

## Test

```bash
python -m pytest app/test_main.py -v
```

## Project Structure

```
qapp/
├── app/
│   ├── main.py          # FastAPI app, API routes, and embedded frontend
│   └── test_main.py     # Pytest test suite
├── requirements.txt
├── prompts.txt          # Agent prompts log
├── log.txt              # File change log
└── README.md
```
