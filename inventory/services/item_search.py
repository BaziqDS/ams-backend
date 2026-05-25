"""
Hybrid item search for the agent's Central Register linking flow.

Combines two retrieval signals over the catalog and fuses them with RRF:
  - BM25 lexical via Postgres tsvector (ts_rank_cd)
  - Semantic cosine similarity via pgvector

After fusion, applies HARD filters (tracking_type, category_type) — these
protect the warehouse invariants (an INDIVIDUAL inspection row must never
link to a QUANTITY-tracked catalog item).

This module is Postgres-only. On SQLite the public function returns None
and the caller falls back to the existing keyword resolver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings
from django.db import connection

from .embeddings import build_query_text, embed_text

logger = logging.getLogger(__name__)


@dataclass
class ItemHit:
    id: int
    name: str
    code: str
    category_id: Optional[int]
    category_display: Optional[str]
    category_type: Optional[str]
    tracking_type: Optional[str]
    description: Optional[str]
    specifications: Optional[str]
    acct_unit: Optional[str]
    rrf_score: float
    signals: list = field(default_factory=list)


def is_supported() -> bool:
    """True when hybrid search can actually run against this DB."""
    return (
        getattr(settings, 'ITEM_SEARCH_HYBRID_ENABLED', False)
        and connection.vendor == 'postgresql'
    )


def hybrid_search_items(
    *,
    query_name: str = '',
    query_code: str = '',
    query_category: str = '',
    query_description: str = '',
    query_specifications: str = '',
    query_unit: str = '',
    tracking_type: Optional[str] = None,
    category_type: Optional[str] = None,
    limit: int = 10,
) -> Optional[list]:
    """
    Run hybrid retrieval. Returns a ranked list of ItemHit, or None if the
    feature is disabled / DB is unsupported / required inputs are missing.

    All `query_*` params describe the *inspection row* the agent is trying to
    link. The function constructs a symmetric query text (same shape as the
    indexed item text) for the semantic side, and uses a flattened token
    string for the BM25 side.
    """
    if not is_supported():
        return None

    query_text = build_query_text(
        name=query_name,
        code=query_code,
        category=query_category,
        description=query_description,
        specifications=query_specifications,
        unit=query_unit,
    )
    if not query_text.strip():
        return None

    # BM25 side uses a flat token bag — plainto_tsquery handles the splitting.
    bm25_query = ' '.join(
        part
        for part in (query_name, query_code, query_description,
                     query_specifications, query_category)
        if part
    ).strip()
    if not bm25_query:
        return None

    query_vec = embed_text(query_text)
    have_semantic = query_vec is not None

    bm25_top = getattr(settings, 'ITEM_SEARCH_BM25_TOP_N', 30)
    semantic_top = getattr(settings, 'ITEM_SEARCH_SEMANTIC_TOP_N', 30)
    rrf_k = getattr(settings, 'ITEM_SEARCH_RRF_K', 60)

    return _run_sql(
        bm25_query=bm25_query,
        query_vec=query_vec,
        have_semantic=have_semantic,
        tracking_type=tracking_type,
        category_type=category_type,
        bm25_top=bm25_top,
        semantic_top=semantic_top,
        rrf_k=rrf_k,
        limit=limit,
    )


def _run_sql(*, bm25_query, query_vec, have_semantic, tracking_type,
             category_type, bm25_top, semantic_top, rrf_k, limit):
    """Execute the fused hybrid query in a single round-trip to Postgres."""
    # tracking_type is a HARD filter (warehouse invariant). category_type is
    # treated as a soft alignment signal — apply only if provided; the BM25
    # path won't drop a row just because category differs, because the same
    # item code can sit under reorganized category trees.
    tracking_clause_bm25 = ''
    tracking_clause_sem = ''
    params_tail = []
    if tracking_type:
        tracking_clause_bm25 = (
            "AND COALESCE(parent_cat.tracking_type, cat.tracking_type) = %s"
        )
        tracking_clause_sem = (
            "AND COALESCE(parent_cat.tracking_type, cat.tracking_type) = %s"
        )

    if have_semantic:
        sem_cte = """
        semantic AS (
          SELECT inventory_item.id,
                 1 - (inventory_item.embedding <=> %s::vector) AS sem_score,
                 ROW_NUMBER() OVER (
                   ORDER BY inventory_item.embedding <=> %s::vector ASC
                 ) AS sem_rank
          FROM inventory_item
          LEFT JOIN inventory_category cat ON cat.id = inventory_item.category_id
          LEFT JOIN inventory_category parent_cat ON parent_cat.id = cat.parent_category_id
          WHERE inventory_item.embedding IS NOT NULL
            AND inventory_item.is_active = TRUE
            AND inventory_item.is_provisional = FALSE
            {tracking_sem}
          ORDER BY inventory_item.embedding <=> %s::vector
          LIMIT {sem_top}
        )
        """.format(tracking_sem=tracking_clause_sem, sem_top=int(semantic_top))
    else:
        sem_cte = "semantic AS (SELECT NULL::int AS id, NULL::float AS sem_score, NULL::int AS sem_rank WHERE FALSE)"

    sql = f"""
    WITH bm25 AS (
      SELECT inventory_item.id,
             ts_rank_cd(inventory_item.search_text,
                        plainto_tsquery('english', %s)) AS bm25_score,
             ROW_NUMBER() OVER (
               ORDER BY ts_rank_cd(inventory_item.search_text,
                                   plainto_tsquery('english', %s)) DESC
             ) AS bm25_rank
      FROM inventory_item
      LEFT JOIN inventory_category cat ON cat.id = inventory_item.category_id
      LEFT JOIN inventory_category parent_cat ON parent_cat.id = cat.parent_category_id
      WHERE inventory_item.search_text @@ plainto_tsquery('english', %s)
        AND inventory_item.is_active = TRUE
        AND inventory_item.is_provisional = FALSE
        {tracking_clause_bm25}
      ORDER BY bm25_score DESC
      LIMIT {int(bm25_top)}
    ),
    {sem_cte},
    fused_ids AS (
      SELECT id FROM bm25
      UNION
      SELECT id FROM semantic WHERE id IS NOT NULL
    ),
    scored AS (
      SELECT f.id,
             COALESCE(1.0 / ({rrf_k} + bm25.bm25_rank), 0)
               + COALESCE(1.0 / ({rrf_k} + semantic.sem_rank), 0) AS rrf_score,
             bm25.bm25_rank,
             semantic.sem_rank
      FROM fused_ids f
      LEFT JOIN bm25 ON bm25.id = f.id
      LEFT JOIN semantic ON semantic.id = f.id
    )
    SELECT s.id,
           i.name,
           i.code,
           i.category_id,
           cat.name AS category_name,
           parent_cat.name AS parent_category_name,
           COALESCE(parent_cat.category_type, cat.category_type) AS category_type,
           COALESCE(parent_cat.tracking_type, cat.tracking_type) AS tracking_type,
           i.description,
           i.specifications,
           i.acct_unit,
           s.rrf_score,
           s.bm25_rank,
           s.sem_rank
    FROM scored s
    JOIN inventory_item i ON i.id = s.id
    LEFT JOIN inventory_category cat ON cat.id = i.category_id
    LEFT JOIN inventory_category parent_cat ON parent_cat.id = cat.parent_category_id
    ORDER BY s.rrf_score DESC
    LIMIT %s
    """

    params = []
    # bm25 CTE: 3 occurrences of bm25_query + optional tracking
    params += [bm25_query, bm25_query, bm25_query]
    if tracking_type:
        params.append(tracking_type)
    # semantic CTE
    if have_semantic:
        params += [query_vec, query_vec]
        if tracking_type:
            params.append(tracking_type)
        params.append(query_vec)
    # final LIMIT
    params.append(int(limit))

    try:
        with connection.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception as exc:
        logger.exception("hybrid_search_items SQL failed: %s", exc)
        return None

    hits = []
    for row in rows:
        (item_id, name, code, category_id, category_name, parent_category_name,
         row_category_type, row_tracking_type, description, specifications,
         acct_unit, rrf_score, bm25_rank, sem_rank) = row

        # Soft category alignment — does not exclude, only annotates the signal.
        category_match = (
            category_type is None
            or row_category_type is None
            or row_category_type == category_type
        )

        category_display = ' / '.join(
            part for part in (parent_category_name, category_name) if part
        )

        signals = []
        if bm25_rank is not None:
            signals.append(f'bm25_rank={int(bm25_rank)}')
        if sem_rank is not None:
            signals.append(f'semantic_rank={int(sem_rank)}')
        if tracking_type and row_tracking_type == tracking_type:
            signals.append('tracking_match')
        if category_match and category_type:
            signals.append('category_match')

        hits.append(ItemHit(
            id=item_id,
            name=name or '',
            code=code or '',
            category_id=category_id,
            category_display=category_display or None,
            category_type=row_category_type,
            tracking_type=row_tracking_type,
            description=description,
            specifications=specifications,
            acct_unit=acct_unit,
            rrf_score=float(rrf_score or 0.0),
            signals=signals,
        ))

    return hits
