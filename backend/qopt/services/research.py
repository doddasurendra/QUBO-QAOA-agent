"""Research library: text extraction and lexical (BM25) search over uploaded documents.

A vector database is deliberately not used: BM25 is adequate for a per-tenant library of
papers and avoids an extra service (see ARCHITECTURE.md). PDF extraction uses `pypdf` when
installed; otherwise PDFs are rejected with an explicit message.
"""
from __future__ import annotations

import io
import math
import re
from collections import Counter
from typing import List

from sqlalchemy import select

from ..db import ResearchDocument, SessionLocal

ALLOWED = {".txt": "text", ".md": "text", ".tex": "text", ".pdf": "pdf"}
_TOK = re.compile(r"[a-zA-Z0-9]+")


def extract_text(filename: str, data: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise ValueError(f"unsupported file type {ext!r}; allowed: {sorted(ALLOWED)}")
    if ALLOWED[ext] == "pdf":
        if not data.startswith(b"%PDF"):
            raise ValueError("file does not look like a PDF")
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF support requires the 'pypdf' package on the server; upload .txt/.md instead") from exc
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text files must be UTF-8") from exc


def tokens(s: str) -> List[str]:
    return [t.lower() for t in _TOK.findall(s)]


def search(query: str, limit: int = 5, owner_id=None) -> List[dict]:
    q = tokens(query)
    if not q:
        return []
    with SessionLocal() as db:
        stmt = select(ResearchDocument)
        if owner_id is not None:
            stmt = stmt.where(ResearchDocument.owner_id == owner_id)
        docs = db.scalars(stmt).all()
    if not docs:
        return []
    # chunk documents into ~120-word passages, BM25 over passages
    passages = []
    for d in docs:
        words = d.content.split()
        for k in range(0, max(len(words), 1), 120):
            passages.append((d, " ".join(words[k:k + 160])))
    toks = [tokens(p) for _, p in passages]
    N = len(passages)
    avg = sum(map(len, toks)) / N or 1
    df = Counter(t for ts in toks for t in set(ts))
    k1, b = 1.5, 0.75
    scored = []
    for (d, p), ts in zip(passages, toks):
        tf = Counter(ts)
        s = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(ts) / avg))
        if s > 0:
            scored.append((s, d, p))
    scored.sort(key=lambda r: -r[0])
    out, seen = [], set()
    for s, d, p in scored:
        if (d.id, p[:40]) in seen:
            continue
        seen.add((d.id, p[:40]))
        out.append({"document_id": d.id, "title": d.title, "score": round(s, 3), "passage": p[:1200]})
        if len(out) >= limit:
            break
    return out
