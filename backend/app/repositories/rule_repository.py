"""Rule chunk lookup. Dict/SQL lookup by source_db is PRIMARY; Postgres FTS is
the fallback for open-ended procedural questions (A8, MASTER §3).

With only ~20 chunks, cache them all in memory at startup — get_rules_by_source
should never hit the DB twice (DEV_A §4.2).
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.domain import RuleChunk

_cache: list[RuleChunk] | None = None


def _row_to_chunk(row) -> RuleChunk:
    return RuleChunk(
        chunk_id=row["chunk_id"],
        slide_number=row["slide_number"],
        title=row["title"],
        source_db=row["source_db"],
        chunk_type=row["chunk_type"],
        text=row["text"],
    )


def load_cache(session: Session) -> list[RuleChunk]:
    global _cache
    rows = session.execute(text("SELECT * FROM rule_chunks ORDER BY slide_number, chunk_id")).mappings().all()
    _cache = [_row_to_chunk(r) for r in rows]
    return _cache


def _ensure_cache(session: Session) -> list[RuleChunk]:
    if _cache is None:
        return load_cache(session)
    return _cache


def get_rules_by_source(session: Session, source_db: str) -> list[RuleChunk]:
    chunks = _ensure_cache(session)
    return [c for c in chunks if c.source_db == source_db]


_FTS_SQL = """
    SELECT *, ts_rank(search_vec, {query_fn}) AS score
    FROM rule_chunks
    WHERE search_vec @@ {query_fn}
      AND (CAST(:source_db AS TEXT) IS NULL OR source_db = CAST(:source_db AS TEXT))
    ORDER BY score DESC LIMIT :k
"""


def _run_fts(session: Session, query_fn: str, params: dict) -> list[RuleChunk]:
    rows = session.execute(text(_FTS_SQL.format(query_fn=query_fn)), params).mappings().all()
    results = []
    for row in rows:
        chunk = _row_to_chunk(row)
        chunk.score = row["score"]
        results.append(chunk)
    return results


def search_rules(session: Session, query: str, source_db: str | None = None, top_k: int = 3) -> list[RuleChunk]:
    """Postgres FTS over ~20 chunks.

    `plainto_tsquery` ANDs every term, which misses on conversational
    questions ('why was this DCCS match excluded?'). When the strict query
    returns nothing we retry with OR semantics so chat always gets a citation
    if any term is relevant.
    """
    params = {"q": query, "source_db": source_db, "k": top_k}

    results = _run_fts(session, "plainto_tsquery('english', :q)", params)
    if results:
        return results

    terms = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 2]
    if not terms:
        return []
    params["q"] = " | ".join(terms)
    return _run_fts(session, "to_tsquery('english', :q)", params)


def get_cross_border_table(session: Session) -> RuleChunk | None:
    chunks = get_rules_by_source(session, "CROSS_BORDER")
    for c in chunks:
        if c.chunk_type == "decision_table":
            return c
    return chunks[0] if chunks else None


_FOOTER_PREFIX_RE = re.compile(r"^\[Slide \d+ — [^\]]+\]\n")


def get_footer_text(session: Session) -> str:
    """Slide-14 DPM 1420 + Personal Conflicts footer, verbatim. Never LLM-generated."""
    chunks = get_rules_by_source(session, "FOOTER")
    parts = [_FOOTER_PREFIX_RE.sub("", c.text) for c in sorted(chunks, key=lambda c: c.chunk_id)]
    return "\n\n".join(parts)
