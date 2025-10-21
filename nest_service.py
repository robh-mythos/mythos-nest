import time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

print("[Mythos Nest] Booting Stage 2 — minimal in-memory index")

# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------
app = FastAPI(title="Mythos Nest", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

# -----------------------------------------------------------------------------
# Fake in-memory data
# -----------------------------------------------------------------------------
INDEX: List[Dict[str, Any]] = [
    {"id": "001", "title": "The Song of Mythos", "text": "This is a placeholder document about the Mythos system."},
    {"id": "002", "title": "Nest Documentation", "text": "Documentation of the Mythos Nest. Search functions soon connect to Google Drive."},
    {"id": "003", "title": "Quantum Thread", "text": "A theoretical exploration of consciousness architecture 144."}
]
INDEXED_AT: float = time.time()


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
# Utilities
# -----------------------------------------------------------------------------
def _score(text: str, query: str) -> float:
    if not text:
        return 0.0
    q = query.lower()
    t = text.lower()
    hits = t.count(q)
    return hits / max(1, len(t) / 1000.0)


def _snippet(text: str, query: str, width: int = 200) -> str:
    q = query.lower()
    t = text.lower()
    pos = t.find(q)
    if pos == -1:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 2)
    end = min(len(text), pos + len(q) + width // 2)
    return text[start:end].replace(query, f"**{query}**")


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/ping")
def ping():
    return {"message": "pong from ultra-minimal test"}

@app.get("/health")
def health():
    return {"status": "ok", "docs_indexed": len(INDEX), "indexed_at": INDEXED_AT}

@app.post("/index")
@app.get("/index")
def reindex():
    global INDEXED_AT
    INDEXED_AT = time.time()
    return {"status": "reindexed", "docs_indexed": len(INDEX), "indexed_at": INDEXED_AT}

@app.get("/search", response_model=SearchResponse)
def search(q: str = Query(..., min_length=2), top_k: int = 5):
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
    return SearchResponse(hits=hits, total_docs=len(INDEX), indexed_at=INDEXED_AT)

@app.get("/")
def root():
    return {"service": "Mythos Nest", "version": "2.1.0", "routes": ["/ping", "/health", "/index", "/search?q=..."]}

print("[Mythos Nest] Stage 2 loaded — ready to serve routes.")
