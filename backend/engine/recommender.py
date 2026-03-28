"""
engine/recommender.py
The core recommendation engine.

Three entry points:
  1. recommend_from_query(query_text)   → NL input like "I want an underdog who works hard"
  2. recommend_from_anime(anime_id)     → "More like Hajime no Ippo"
  3. recommend_for_user(user_id)        → Personalized, based on rating history

All three return a list of RecommendationResult objects with explanations.
"""

import os
import re
import json
import time
import asyncio
import logging
import anthropic
import cohere
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.schema import Anime, AnimeNarrative, AnimeEmbedding, UserRating
from pipeline.enricher import generate_embedding, get_cohere_client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

client       = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
haiku_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

HAIKU_MODEL  = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-20250514"


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class RecommendationResult:
    anime: Anime
    narrative: AnimeNarrative
    similarity_score: float
    explanation: str                # Human-readable "why this matches"
    match_reasons: list[str]        # Bullet-point reasons
    match_confidence: float = 1.0   # 0.0–1.0, how well this actually fits the query

CONFIDENCE_THRESHOLD = 0.5


# ─── Step 1: Parse natural language query into structured intent ──────────────

QUERY_PARSE_SYSTEM = """
You are an anime recommendation assistant. Parse a user's natural language request
into a structured JSON intent object that can be used to search for anime.

Extract as much signal as possible from the query. Return ONLY valid JSON.
"""

async def parse_nl_query(query_text: str) -> dict:
    """
    Convert free-form user text into a structured search intent.

    Example:
      Input:  "anime where the MC starts weak and gradually gets stronger through hard work"
      Output: {"growth_type": "slow_burn", "power_origin": "earned",
               "themes": ["perseverance", "hard_work"],
               "protagonist_archetype": "underdog",
               "narrative_keywords": "gradual growth through effort and discipline"}
    """
    prompt = f"""Parse this anime recommendation request into structured search intent:

User request: "{query_text}"

Return this JSON structure:
{{
  "protagonist_archetype": <"underdog"|"prodigy"|"reluctant_hero"|"anti_hero"|"ensemble"|"everyman"|null>,
  "power_origin": <"earned"|"gifted"|"stolen"|"inherited"|"tactical"|"none"|null>,
  "growth_type": <"slow_burn"|"rapid_ascension"|"plateau_breakthrough"|"regression"|"static"|null>,
  "conflict_type": <"martial"|"interpersonal"|"societal"|"existential"|"investigative"|"survival"|null>,
  "tone": <"dark"|"comedic"|"bittersweet"|"hopeful"|"philosophical"|"action_focused"|null>,
  "themes": [<list of relevant theme strings>],
  "relationship_types": [<relevant: "mentor_student"|"rival_rival"|"romantic"|"found_family">],
  "power_system": <"hard_magic"|"soft_magic"|"physical_realism"|"tech_based"|"none"|null>,
  "stakes_level": <"personal"|"community"|"national"|"global"|"cosmic"|null>,
  "narrative_keywords": <2-3 sentence description of the ideal anime in plain English>,
  "referenced_titles": [<list of anime titles the user is explicitly referencing, e.g. "anime like steins gate and death note" → ["Steins;Gate", "Death Note"]. Use the canonical/official English or romaji title. Return [] if the user is not referencing any specific anime>]
}}"""

    try:
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=QUERY_PARSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        # Fallback: return minimal intent with just the raw text
        return {"narrative_keywords": query_text}


# ─── Step 2: Build embedding for search ──────────────────────────────────────

def intent_to_embedding_text(intent: dict, original_query: str) -> str:
    """Convert structured intent back into rich text for embedding."""
    parts = [original_query]

    if intent.get("narrative_keywords"):
        parts.append(intent["narrative_keywords"])
    if intent.get("protagonist_archetype"):
        parts.append(f"Protagonist type: {intent['protagonist_archetype']}.")
    if intent.get("growth_type"):
        parts.append(f"Character growth: {intent['growth_type']}.")
    if intent.get("power_origin"):
        parts.append(f"Power origin: {intent['power_origin']}.")
    if intent.get("tone"):
        parts.append(f"Tone: {intent['tone']}.")
    if intent.get("themes"):
        parts.append(f"Themes: {', '.join(intent['themes'])}.")
    if intent.get("conflict_type"):
        parts.append(f"Conflict: {intent['conflict_type']}.")

    return " ".join(parts)


# ─── Step 3: Vector similarity search ────────────────────────────────────────

def vector_search(
    db: Session,
    query_vector: list[float],
    exclude_ids: list[int] = None,
    limit: int = 20
) -> list[tuple[Anime, AnimeNarrative, float]]:
    """
    Find the most semantically similar anime using pgvector cosine similarity.
    Returns list of (Anime, AnimeNarrative, similarity_score) tuples.
    """
    exclude_ids = exclude_ids or []
    exclude_clause = f"AND a.id NOT IN ({','.join(str(i) for i in exclude_ids)})" if exclude_ids else ""

    # pgvector cosine distance: 1 - (u <=> v) = cosine similarity
    sql = text(f"""
        SELECT
            a.id,
            1 - (ae.embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM anime_embedding ae
        JOIN anime a ON a.id = ae.anime_id
        JOIN anime_narrative an ON an.anime_id = a.id
        WHERE ae.embedding IS NOT NULL
        {exclude_clause}
        ORDER BY ae.embedding <=> CAST(:query_vec AS vector)
        LIMIT :limit
    """)

    # Ensure vector is a plain Python list (not numpy array) for clean str() formatting
    if hasattr(query_vector, 'tolist'):
        query_vector = query_vector.tolist()

    rows = db.execute(sql, {
        "query_vec": str(list(query_vector)),
        "limit": limit
    }).fetchall()

    results = []
    for row in rows:
        anime     = db.query(Anime).filter(Anime.id == row.id).first()
        narrative = db.query(AnimeNarrative).filter(AnimeNarrative.anime_id == row.id).first()
        if anime and narrative:
            results.append((anime, narrative, float(row.similarity)))

    return results


def deduplicate_by_series(
    results: list[tuple[Anime, AnimeNarrative, float]],
    db: Session = None,
) -> list[tuple[Anime, AnimeNarrative, float]]:
    """
    Deduplicate by series_root_id. Always returns the series ROOT anime
    (where id == series_root_id), but uses the highest similarity score
    from any season in the series for ranking.

    Example: If Fire Force S2 scores 0.71 and S1 scores 0.65,
    returns S1 (the root) ranked with score 0.71.
    """
    # best_per_root: root_id → (best_score, anime, narrative)
    best_per_root: dict[int, tuple[float, Anime, AnimeNarrative]] = {}

    for anime, narrative, score in results:
        root = anime.series_root_id or anime.id
        if root not in best_per_root or score > best_per_root[root][0]:
            best_per_root[root] = (score, anime, narrative)

    # Now resolve each entry to the actual root anime
    deduped = []
    for root_id, (best_score, best_anime, best_narrative) in best_per_root.items():
        # If this entry IS the root, use it directly
        if best_anime.id == root_id:
            deduped.append((best_anime, best_narrative, best_score))
        elif db is not None:
            # Fetch the actual root anime and its narrative
            root_anime = db.query(Anime).filter(Anime.id == root_id).first()
            root_narrative = db.query(AnimeNarrative).filter(
                AnimeNarrative.anime_id == root_id
            ).first()
            if root_anime and root_narrative:
                deduped.append((root_anime, root_narrative, best_score))
            else:
                # Root not enriched — fall back to the best-scoring season
                deduped.append((best_anime, best_narrative, best_score))
        else:
            # No db session — fall back to the best-scoring season
            deduped.append((best_anime, best_narrative, best_score))

    # Re-sort by score descending (dict iteration order may not be sorted)
    deduped.sort(key=lambda x: x[2], reverse=True)
    return deduped


# ─── Content filtering ────────────────────────────────────────────────────

EXPLICIT_SIGNALS = re.compile(
    r'\b(ecchi|fan\s*service|harem|sexy|adult|nsfw|lewd|fanservice)\b',
    re.IGNORECASE
)
FILTERED_LEVELS = {"ecchi", "explicit"}


def _query_wants_explicit(query_text: str) -> bool:
    """Check if the user's query explicitly asks for mature content."""
    return bool(EXPLICIT_SIGNALS.search(query_text))


def _filter_by_content(
    results: list[tuple[Anime, AnimeNarrative, float]],
    allow_explicit: bool = False,
) -> list[tuple[Anime, AnimeNarrative, float]]:
    """Remove ecchi/explicit anime unless the user asked for them."""
    if allow_explicit:
        return results
    return [
        (a, n, s) for a, n, s in results
        if (n.content_level or "clean") not in FILTERED_LEVELS
    ]


# ─── Referenced title exclusion ───────────────────────────────────────────────

def _resolve_referenced_ids(
    db: Session,
    referenced_titles: list[str],
) -> list[int]:
    """
    Fuzzy-match LLM-extracted referenced titles against anime title_romaji
    and title_english.  Returns a list of anime IDs to exclude.
    """
    if not referenced_titles:
        return []

    ids: set[int] = set()
    for title in referenced_titles:
        pattern = f"%{title}%"
        rows = db.execute(
            text(
                "SELECT id FROM anime "
                "WHERE LOWER(title_romaji)  LIKE LOWER(:pat) "
                "   OR LOWER(title_english) LIKE LOWER(:pat)"
            ),
            {"pat": pattern},
        ).fetchall()
        ids.update(row.id for row in rows)
    return list(ids)


# ─── Step 4: Generate explanations (batched single Claude call) ──────────────

EXPLANATION_SYSTEM = """You are an anime recommendation assistant. Given a user's query and a list of matched anime with their narrative profiles, explain concisely and specifically why each anime is a great match.

Be specific — reference actual narrative elements, not generic praise.
Respond ONLY with valid JSON — no markdown fences, no preamble, no trailing text."""


def _build_anime_block(idx: int, anime: Anime, narrative: AnimeNarrative) -> str:
    """Format one anime's data for explanation prompts — trimmed to 5 key fields."""
    themes_str = ", ".join((narrative.themes or [])[:4])
    title_line = anime.title_romaji
    if anime.title_english:
        title_line += f" ({anime.title_english})"
    summary = (narrative.narrative_summary or "")[:250]  # cap summary length
    return f"""Anime #{idx} (id={anime.id}): {title_line}
- Archetype/Growth: {narrative.protagonist_archetype}, {narrative.growth_type}
- Tone: {narrative.tone} | Conflict: {narrative.conflict_type}
- Themes: {themes_str}
- Summary: {summary}"""


async def _generate_explanations_batch(
    query_label: str,
    candidates: list[tuple[Anime, AnimeNarrative, float]],
    limit: int,
) -> list[RecommendationResult]:
    """
    Generate explanations for all candidates in a single Haiku call.
    Capped at 6 results to keep the prompt tight and fast.
    Falls back to per-result structural explanations on failure.
    """
    pool = candidates[:min(limit, 6)]  # cap at 6 — Haiku is fast but keep prompt small
    if not pool:
        return []

    anime_blocks = "\n\n".join(
        _build_anime_block(i + 1, anime, narrative)
        for i, (anime, narrative, _) in enumerate(pool)
    )

    prompt = f"""Request: "{query_label}"

{anime_blocks}

Return JSON array (one object per anime):
[{{"anime_id": <id>, "explanation": <1-2 sentences>, "reasons": [<3 bullets, max 12 words each>], "match_confidence": <0.0-1.0>}}]"""

    try:
        t0 = time.time()
        message = await haiku_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200 * len(pool),
            system=EXPLANATION_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        logger.info("TIMING | explanation_gen: %.2fs", time.time() - t0)
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        explanations_list = json.loads(raw.strip())

        by_id = {int(e["anime_id"]): e for e in explanations_list}

        results = []
        for anime, narrative, score in pool:
            entry = by_id.get(anime.id)
            if not entry:
                continue
            confidence = float(entry.get("match_confidence", 0.7))
            if confidence < CONFIDENCE_THRESHOLD:
                continue
            results.append(RecommendationResult(
                anime=anime,
                narrative=narrative,
                similarity_score=score,
                explanation=entry.get("explanation", ""),
                match_reasons=entry.get("reasons", []),
                match_confidence=confidence,
            ))
            if len(results) >= limit:
                break

        return results

    except Exception as exc:
        logger.warning("Batch explanation failed, using structural fallback: %s", exc)
        results = []
        for anime, narrative, score in pool:
            results.append(RecommendationResult(
                anime=anime,
                narrative=narrative,
                similarity_score=score,
                explanation=f"Matches your request with {score:.0%} narrative similarity.",
                match_reasons=[
                    f"Protagonist archetype: {narrative.protagonist_archetype}",
                    f"Growth type: {narrative.growth_type}",
                    f"Tone: {narrative.tone}",
                ],
                match_confidence=0.7,
            ))
            if len(results) >= limit:
                break
        return results


# ─── Embedding with retry + error propagation ────────────────────────────────

def _embed_with_retry(text: str, input_type: str = "search_query") -> list[float]:
    """
    Generate embedding via Cohere with one retry on failure.
    Raises HTTPException 503 on persistent failure so the user sees a real error.
    """
    last_error = None
    for attempt in range(2):
        try:
            client = get_cohere_client()
            response = client.embed(
                texts=[text],
                model="embed-english-v3.0",
                input_type=input_type,
            )
            return response.embeddings[0]
        except cohere.TooManyRequestsError as e:
            logger.error("Cohere 429 rate limit (attempt %d/2): %s", attempt + 1, e)
            last_error = e
            if attempt == 0:
                time.sleep(2)
        except Exception as e:
            logger.error("Cohere embedding error (attempt %d/2): %s", attempt + 1, e)
            last_error = e
            if attempt == 0:
                time.sleep(2)

    # Both attempts failed
    if isinstance(last_error, cohere.TooManyRequestsError):
        raise HTTPException(
            status_code=503,
            detail={"error": "rate_limit", "message": "Search is temporarily unavailable. Please try again in a minute."},
        )
    raise HTTPException(
        status_code=503,
        detail={"error": "embedding_failed", "message": "Search is temporarily unavailable. Please try again."},
    )


# ─── Public API ───────────────────────────────────────────────────────────────

async def recommend_from_query(
    db: Session,
    query_text: str,
    limit: int = 8
) -> list[RecommendationResult]:
    """
    Main recommendation function for natural language queries.
    "I want an anime where the MC works hard and gradually gets stronger..."
    """
    t_total = time.time()

    t0 = time.time()
    intent = await parse_nl_query(query_text)
    logger.info("TIMING | intent_parse: %.2fs", time.time() - t0)

    referenced_titles = intent.get("referenced_titles") or []
    exclude_ids = _resolve_referenced_ids(db, referenced_titles) if referenced_titles else []

    t0 = time.time()
    embedding_text = intent_to_embedding_text(intent, query_text)
    query_vector = _embed_with_retry(embedding_text)
    logger.info("TIMING | embedding: %.2fs", time.time() - t0)

    t0 = time.time()
    allow_explicit = _query_wants_explicit(query_text)
    candidates = vector_search(db, query_vector, exclude_ids=exclude_ids, limit=limit * 3)
    logger.info("TIMING | vector_search: %.2fs", time.time() - t0)

    t0 = time.time()
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)
    logger.info("TIMING | dedup_filter: %.2fs", time.time() - t0)

    results = await _generate_explanations_batch(query_text, candidates, limit)
    logger.info("TIMING | total: %.2fs", time.time() - t_total)
    return results


async def search_candidates(
    db: Session,
    query_text: str,
    limit: int = 8,
) -> tuple[list[tuple[Anime, AnimeNarrative, float]], str]:
    """
    Phase 1 of streaming search: parse intent, embed, vector search, dedup, filter.
    Returns (candidates, query_text) — no explanations yet.
    Logs TIMING breakpoints at INFO level.
    """
    t_total = time.time()

    t0 = time.time()
    intent = await parse_nl_query(query_text)
    logger.info("TIMING | intent_parse: %.2fs", time.time() - t0)

    referenced_titles = intent.get("referenced_titles") or []
    t0 = time.time()
    exclude_ids = _resolve_referenced_ids(db, referenced_titles) if referenced_titles else []
    if referenced_titles:
        logger.info("TIMING | title_extraction (DB lookup): %.2fs for %d titles", time.time() - t0, len(referenced_titles))

    t0 = time.time()
    embedding_text = intent_to_embedding_text(intent, query_text)
    query_vector = _embed_with_retry(embedding_text)
    logger.info("TIMING | embedding: %.2fs", time.time() - t0)

    t0 = time.time()
    allow_explicit = _query_wants_explicit(query_text)
    candidates = vector_search(db, query_vector, exclude_ids=exclude_ids, limit=limit * 3)
    logger.info("TIMING | vector_search: %.2fs (%d raw results)", time.time() - t0, len(candidates))

    t0 = time.time()
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)
    logger.info("TIMING | dedup_filter: %.2fs (%d after dedup)", time.time() - t0, len(candidates))

    logger.info("TIMING | search_candidates total: %.2fs", time.time() - t_total)
    return candidates[:6], query_text  # cap at 6 — explanation gen is the bottleneck


async def _explain_one(
    query_label: str,
    anime: Anime,
    narrative: AnimeNarrative,
    score: float,
    queue: asyncio.Queue,
) -> None:
    """Generate explanation for a single anime with Haiku and put result in queue."""
    themes_str = ", ".join((narrative.themes or [])[:4])
    summary = (narrative.narrative_summary or "")[:250]
    title = anime.title_romaji
    if anime.title_english:
        title += f" ({anime.title_english})"

    prompt = f"""Request: "{query_label}"

Anime (id={anime.id}): {title}
- Archetype/Growth: {narrative.protagonist_archetype}, {narrative.growth_type}
- Tone: {narrative.tone} | Conflict: {narrative.conflict_type}
- Themes: {themes_str}
- Summary: {summary}

Return JSON: {{"anime_id": {anime.id}, "explanation": <1-2 sentences>, "reasons": [<3 bullets max 12 words>], "match_confidence": <0.0-1.0>}}"""

    try:
        message = await haiku_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            system=EXPLANATION_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        await queue.put({
            "anime_id": anime.id,
            "explanation": data.get("explanation", ""),
            "match_reasons": data.get("reasons", []),
            "match_confidence": float(data.get("match_confidence", 0.7)),
        })
    except Exception as exc:
        logger.warning("Haiku explanation failed for %s: %s", anime.title_romaji, exc)
        await queue.put({
            "anime_id": anime.id,
            "explanation": f"Matches your request with {score:.0%} narrative similarity.",
            "match_reasons": [
                f"Protagonist: {narrative.protagonist_archetype}",
                f"Growth: {narrative.growth_type}",
                f"Tone: {narrative.tone}",
            ],
            "match_confidence": 0.7,
        })


async def generate_explanations_stream(
    query_label: str,
    candidates: list[tuple[Anime, AnimeNarrative, float]],
) -> asyncio.Queue:
    """
    Fire parallel Haiku calls for each anime. Returns a queue that receives
    explanation dicts as each one completes. Caller drains queue by len(candidates).
    """
    queue: asyncio.Queue = asyncio.Queue()
    tasks = [
        _explain_one(query_label, anime, narrative, score, queue)
        for anime, narrative, score in candidates
    ]
    asyncio.gather(*tasks)  # fire and forget — results go to queue
    return queue


async def generate_explanations_for_candidates(
    query_label: str,
    candidates: list[tuple[Anime, AnimeNarrative, float]],
) -> dict[int, dict]:
    """
    Batch Haiku call for all candidates at once. Returns {anime_id: explanation_dict}.
    Used by non-streaming path. On failure returns empty dict.
    """
    if not candidates:
        return {}

    anime_blocks = "\n\n".join(
        _build_anime_block(i + 1, anime, narrative)
        for i, (anime, narrative, _) in enumerate(candidates)
    )

    prompt = f"""Request: "{query_label}"

{anime_blocks}

Return JSON array: [{{"anime_id": <id>, "explanation": <1-2 sentences>, "reasons": [<3 bullets max 12 words>], "match_confidence": <0.0-1.0>}}]"""

    try:
        t0 = time.time()
        message = await haiku_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200 * len(candidates),
            system=EXPLANATION_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        logger.info("TIMING | explanation_gen (batch): %.2fs", time.time() - t0)
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        explanations_list = json.loads(raw.strip())
        return {int(e["anime_id"]): e for e in explanations_list}
    except Exception as exc:
        logger.warning("Batch explanation failed in streaming path: %s", exc)
        return {}


async def recommend_from_anime(
    db: Session,
    anime_id: int,
    exclude_ids: list[int] = None,
    limit: int = 8
) -> list[RecommendationResult]:
    """
    Similarity-based recommendations: "More like this anime."
    Used after a user rates/likes a show.
    """
    # Get source anime embedding
    source_emb = db.query(AnimeEmbedding).filter(
        AnimeEmbedding.anime_id == anime_id
    ).first()

    if not source_emb:
        return []

    source_anime = db.query(Anime).filter(Anime.id == anime_id).first()
    source_narrative = db.query(AnimeNarrative).filter(
        AnimeNarrative.anime_id == anime_id
    ).first()

    # Allow explicit results only if the source anime is itself ecchi/explicit
    allow_explicit = (
        source_narrative is not None
        and (source_narrative.content_level or "clean") in FILTERED_LEVELS
    )

    # Search (always exclude the source itself)
    excluded = list(set([anime_id] + (exclude_ids or [])))
    candidates = vector_search(db, source_emb.embedding, exclude_ids=excluded, limit=limit * 3)
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)

    # Generate explanations in parallel
    query_label = f"anime similar to {source_anime.title_romaji}"
    return await _generate_explanations_batch(query_label, candidates, limit)


async def recommend_for_user(
    db: Session,
    user_id: str,
    limit: int = 10
) -> list[RecommendationResult]:
    """
    Personalized recommendations based on user's rating history.
    Averages embeddings of liked anime to form a taste profile vector.
    """
    # Get user's liked anime
    liked_ratings = db.query(UserRating).filter(
        UserRating.user_id == user_id,
        UserRating.rating_type.in_(["LIKED"])
    ).all()

    if not liked_ratings:
        return []

    liked_ids = [r.anime_id for r in liked_ratings]
    watched_ids = [
        r.anime_id for r in
        db.query(UserRating).filter(UserRating.user_id == user_id).all()
    ]

    # Fetch embeddings for liked anime
    liked_embeddings = db.query(AnimeEmbedding).filter(
        AnimeEmbedding.anime_id.in_(liked_ids)
    ).all()

    if not liked_embeddings:
        return []

    # Average embedding → taste profile vector
    dim = len(liked_embeddings[0].embedding)
    avg_vector = [0.0] * dim
    for emb in liked_embeddings:
        for i, v in enumerate(emb.embedding):
            avg_vector[i] += v
    avg_vector = [v / len(liked_embeddings) for v in avg_vector]

    # Normalize
    magnitude = sum(v**2 for v in avg_vector) ** 0.5
    if magnitude > 0:
        avg_vector = [v / magnitude for v in avg_vector]

    # Check if user predominantly likes ecchi/explicit content
    liked_narratives = db.query(AnimeNarrative).filter(
        AnimeNarrative.anime_id.in_(liked_ids)
    ).all()
    explicit_count = sum(
        1 for n in liked_narratives
        if (n.content_level or "clean") in FILTERED_LEVELS
    )
    allow_explicit = len(liked_narratives) > 0 and explicit_count > len(liked_narratives) / 2

    # Search, excluding already-watched + dedup by series + content filter
    candidates = vector_search(db, avg_vector, exclude_ids=watched_ids, limit=limit * 3)
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)

    # Generate explanations in parallel
    return await _generate_explanations_batch("anime matching your taste profile", candidates, limit)
