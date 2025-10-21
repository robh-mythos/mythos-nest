import io
import json
import time
from typing import List, Dict, Any, Optional
import sys
import os
from types import SimpleNamespace

print("[Mythos Nest] Running from file:", __file__)
print("[Mythos Nest] Python argv:", sys.argv)
print("[Mythos Nest] Routes loading...")

# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
try:
    from config import settings  # use config.py if present
except Exception as e:
    print(f"[Mythos Nest] Using internal settings stub (no config.py): {e}")
    settings = SimpleNamespace(
        NEST_CLIENT_SECRET_JSON=os.getenv("NEST_CLIENT_SECRET_JSON"),
        NEST_TOKEN_JSON=os.getenv("NEST_TOKEN_JSON"),
        NEST_DRIVE_FOLDER_ID=os.getenv("NEST_DRIVE_FOLDER_ID"),
        NEST_MAX_FILES=int(os.getenv("NEST_MAX_FILES", 5)),
        NEST_TTL_SECS=int(os.getenv("NEST_TTL_SECS", 3600)),
    )

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pdfminer.high_level import extract_text
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------
app = FastAPI(title="Mythos Nest", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

INDEX: List[Dict[str, Any]] = []
INDEXED_AT: Optional[float] = None

# -----------------------------------------------------------------------------
# Google Drive connection
# -----------------------------------------------------------------------------
def _build_drive() -> Any:
    if not settings.NEST_CLIENT_SECRET_JSON or not settings.NEST_TOKEN_JSON:
        raise RuntimeError("Google OAuth JSON is missing (NEST_CLIENT_SECRET_JSON / NEST_TOKEN_JSON)")

    token_info = json.loads(settings.NEST_TOKEN_JSON)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("drive", "v3", credentials=creds, cache_discovery=False)

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class SearchHit(BaseModel):
    id: str
    title: str
    score: float
    snippet: str

class SearchResponse(BaseModel):
    hits: List[SearchHit]
    total_docs: int
    indexed_at: float

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _now() -> float:
    return time.time()

def _needs_refresh() -> bool:
    if INDEXED_AT is None:
        return True
    return (_now() - INDEXED_AT) > settings.NEST_TTL_SECS

def _snippet(text: str, query: str, width: int = 200) -> str:
    q = query.lower()
    t = text.lower()
    pos = t.find(q)
    if pos == -1:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 2)
    end = min(len(text), pos + len(q) + width // 2)
    snippet = text[start:end]
    return snippet.replace(query, f"**{query}**")

def _score(text: str, query: str) -> float:
    if not text:
        return 0.0
    lc = text.lower()
    q = query.lower()
    hits = lc.count(q)
    if hits == 0:
        return 0.0
    return hits / max(1, len(lc) / 1000.0)

# -----------------------------------------------------------------------------
# Indexing
# -----------------------------------------------------------------------------
def _index_drive_folder() -> int:
    global INDEX, INDEXED_AT

    folder_id = settings.NEST_DRIVE_FOLDER_ID
    if not folder_id:
        raise RuntimeError("NEST_DRIVE_FOLDER_ID is not set.")

    service = _build_drive()
    q = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    files = service.files().list(q=q, fields="files(id, name, mimeType, size)").execute().get("files", [])
    files = sorted(files, key=lambda f: f.get("id"), reverse=True)[: settings.NEST_MAX_FILES]

    new_index: List[Dict[str, Any]] = []
    for f in files:
        try:
            file_id = f["id"]
            title = f.get("name", file_id)
            req = service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            buf.seek(0)
            text = extract_text(buf) or ""
            text = text.strip().replace("\x00", "")
            new_index.append({"id": file_id, "title": title, "text": text})
        except Exception as e:
            print(f"[Nest] Failed to parse {f.get('name')}: {e}")

    INDEX = new_index
    INDEXED_AT = _now()
    return len(INDEX)

def ensure_index():
    if _needs_refresh():
        _index_drive_folder()

# -----------------------------------------------------------------------------
# Routes
# -------------------
