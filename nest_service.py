import io, os, json, time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pdfminer.high_level import extract_text

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

print("[Mythos Nest] Stage 4 — OCR fallback enabled")

app = FastAPI(title="Mythos Nest", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
INDEX: List[Dict[str, Any]] = []
INDEXED_AT: Optional[float] = None

# Tunables (can also be overridden via env)
TTL_SECS = int(os.getenv("NEST_TTL_SECS", 3600))
MAX_FILES = int(os.getenv("NEST_MAX_FILES", 10))
OCR_PAGE_LIMIT = int(os.getenv("NEST_OCR_PAGE_LIMIT", 10))  # safety on free tier

# ----------------------------- Google Drive auth -----------------------------
def _build_drive():
    cs = os.getenv("NEST_CLIENT_SECRET_JSON")
    tk = os.getenv("NEST_TOKEN_JSON")
    if not (cs and tk):
        raise RuntimeError("Missing Google Drive auth JSON env vars.")
    creds = Credentials.from_authorized_user_info(json.loads(tk), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)

# --------------------------------- Models -----------------------------------
class SearchHit(BaseModel):
    id: str
    title: str
    score: float
    snippet: str

class SearchResponse(BaseModel):
    hits: List[SearchHit]
    total_docs: int
    indexed_at: float

# -------------------------------- Helpers -----------------------------------
def _now() -> float: return time.time()

def _needs_refresh() -> bool:
    return INDEXED_AT is None or (_now() - INDEXED_AT) > TTL_SECS

def _score(text: str, q: str) -> float:
    if not text: return 0.0
    t, ql = text.lower(), q.lower()
    hits = t.count(ql)
    return 0.0 if hits == 0 else hits / max(1, len(t) / 1000.0)

def _snippet(text: str, q: str, width: int = 200) -> str:
    if not text: return ""
    tl, ql = text.lower(), q.lower()
    pos = tl.find(ql)
    if pos == -1:
        return text[:width] + ("…" if len(text) > width else "")
    start, end = max(0, pos - width // 2), min(len(text), pos + len(ql) + width // 2)
    window = text[start:end]
    return window.replace(q, f"**{q}**")

# ---- OCR fallback (only used if pdfminer finds no text) ---------------------
def _ocr_bytes(pdf_bytes: bytes, page_limit: int = OCR_PAGE_LIMIT) -> str:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=None)
        # limit pages on free tier to avoid timeouts
        images = images[:page_limit] if page_limit and page_limit > 0 else images
        ocr_chunks = []
        for i, img in enumerate(images, 1):
            text = pytesseract.image_to_string(img)
            ocr_chunks.append(text)
            if i % 5 == 0:
                print(f"[Nest OCR] processed {i} pages…")
        combined = "\n".join(ocr_chunks).strip()
        return combined
    except Exception as e:
        print(f"[Nest OCR] fallback failed: {e}")
        return ""

# -------------------------------- Indexing ----------------------------------
def _index_drive_folder() -> int:
    global INDEX, INDEXED_AT
    folder = os.getenv("NEST_DRIVE_FOLDER_ID")
    if not folder:
        raise RuntimeError("NEST_DRIVE_FOLDER_ID not set")

    service = _build_drive()
    q = f"'{folder}' in parents and mimeType='application/pdf' and trashed=false"
    files = service.files().list(q=q, fields="files(id,name,size)").execute().get("files", [])
    files = sorted(files, key=lambda f: f.get("id"), reverse=True)[:MAX_FILES]

    new_index: List[Dict[str, Any]] = []
    for f in files:
        fid, name = f["id"], f.get("name", f["id"])
        try:
            req = service.files().get_media(fileId=fid)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            raw = buf.getvalue()

            # 1) try native text extraction
            buf.seek(0)
            text = (extract_text(buf) or "").strip().replace("\x00", "")

            # 2) if empty, OCR it
            if not text:
                print(f"[Nest] No text via pdfminer for: {name} — falling back to OCR")
                text = _ocr_bytes(raw)
                if text:
                    print(f"[Nest] OCR extracted text from: {name}")
                else:
                    print(f"[Nest] OCR yielded no text for: {name}")

            new_index.append({"id": fid, "title": name, "text": text})
        except Exception as e:
            print(f"[Nest] Failed to index {name}: {e}")

    INDEX = new_index
    INDEXED_AT = _now()
    print(f"[Nest] Indexed {len(INDEX)} documents (MAX_FILES={MAX_FILES}, TTL={TTL_SECS}s)")
    return len(INDEX)

def ensure_index():
    if _needs_refresh():
        _index_drive_folder()

# --------------------------------- Routes -----------------------------------
@app.get("/ping")
def ping():
    return {"message": "pong from OCR-enabled Nest"}

@app.get("/health")
def health():
    return {"status": "nest-ok", "docs_indexed": len(INDEX), "indexed_at": INDEXED_AT}

@app.post("/index")
@app.get("/index")
def reindex():
    n = _index_drive_folder()
    return {"status": "reindexed", "docs_indexed": n, "indexed_at": INDEXED_AT}

@app.get("/search", response_model=SearchResponse)
def search(q: str = Query(..., min_length=2), top_k: int = 5):
    ensure_index()
    if not INDEX:
        return SearchResponse(hits=[], total_docs=0, indexed_at=INDEXED_AT or 0.0)

    scored = []
    for doc in INDEX:
        s = _score(doc["text"], q)
        if s > 0:
            scored.append({
                "id": doc["id"],
                "title": doc["title"],
                "score": s,
                "snippet": _snippet(doc["text"], q)
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    hits = [SearchHit(**h) for h in scored[: top_k]]
    return SearchResponse(hits=hits, total_docs=len(INDEX), indexed_at=INDEXED_AT or 0.0)

@app.get("/debug_env")
def debug_env():
    return {
        "has_client_secret": bool(os.getenv("NEST_CLIENT_SECRET_JSON")),
        "has_token": bool(os.getenv("NEST_TOKEN_JSON")),
        "has_folder_id": bool(os.getenv("NEST_DRIVE_FOLDER_ID")),
        "ocr_page_limit": OCR_PAGE_LIMIT,
        "max_files": MAX_FILES,
        "ttl_secs": TTL_SECS,
    }

@app.get("/")
def root():
    return {"service":"Mythos Nest","version":"4.0.0",
            "routes":["/ping","/health","/index","/search?q=..."]}
