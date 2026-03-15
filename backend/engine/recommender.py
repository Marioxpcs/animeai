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
import anthropic
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.schema import Anime, AnimeNarrative, AnimeEmbedding, UserRating
from pipeline.enricher import generate_embedding
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


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

def parse_nl_query(query_text: str) -> dict:
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
  "narrative_keywords": <2-3 sentence description of the ideal anime in plain English>
}}"""

    try:
        message = client.messages.create(
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


# ─── Step 4: Generate explanation ────────────────────────────────────────────

EXPLANATION_SYSTEM = """
You are an anime recommendation assistant. Given a user's query or a source anime,
explain concisely and specifically why the recommended anime is a great match.

Be specific — reference actual narrative elements, not generic praise.
Return a JSON object only.
"""

def generate_explanation(
    query_or_source: str,
    recommended: Anime,
    narrative: AnimeNarrative,
    similarity_score: float
) -> tuple[str, list[str], float]:
    """
    Generate a human-readable explanation for why this anime was recommended.
    Returns (explanation_paragraph, [bullet_point_reasons], match_confidence)
    """
    themes_str = ", ".join(narrative.themes or [])
    rel_str    = ", ".join(narrative.relationship_types or [])

    prompt = f"""Given this request: "{query_or_source}"

The recommended anime is: {recommended.title_romaji}
{f'({recommended.title_english})' if recommended.title_english else ''}

Its narrative profile:
- Protagonist: {narrative.protagonist_archetype}, {narrative.power_origin} power, {narrative.growth_type} growth
- Conflict: {narrative.conflict_type}, Stakes: {narrative.stakes_level}
- Tone: {narrative.tone}, Pacing: {narrative.pacing}
- Themes: {themes_str}
- Relationships: {rel_str}
- Summary: {narrative.narrative_summary}

Return JSON:
{{
  "explanation": <1-2 sentence explanation of why this matches the request>,
  "reasons": [<3-4 specific bullet-point reasons, each under 15 words>],
  "match_confidence": <float 0.0-1.0, how well this anime actually fits the request. Use 0.0-0.4 for poor matches, 0.5-0.7 for decent, 0.8-1.0 for strong>
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=EXPLANATION_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        return (
            data.get("explanation", ""),
            data.get("reasons", []),
            float(data.get("match_confidence", 0.7)),
        )
    except Exception:
        # Fallback explanation from structured data
        explanation = f"Matches your request with {similarity_score:.0%} narrative similarity."
        reasons     = [
            f"Protagonist archetype: {narrative.protagonist_archetype}",
            f"Growth type: {narrative.growth_type}",
            f"Tone: {narrative.tone}",
        ]
        return explanation, reasons, 0.7


# ─── Public API ───────────────────────────────────────────────────────────────

def recommend_from_query(
    db: Session,
    query_text: str,
    limit: int = 8
) -> list[RecommendationResult]:
    """
    Main recommendation function for natural language queries.
    "I want an anime where the MC works hard and gradually gets stronger..."
    """
    # Parse intent
    intent = parse_nl_query(query_text)

    # Generate query embedding
    embedding_text = intent_to_embedding_text(intent, query_text)
    query_vector   = generate_embedding(embedding_text)

    # Vector search + dedup by series + content filter
    allow_explicit = _query_wants_explicit(query_text)
    candidates = vector_search(db, query_vector, limit=limit * 5)
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)

    # Generate explanations and filter by confidence
    results = []
    for anime, narrative, score in candidates:
        if len(results) >= limit:
            break
        explanation, reasons, confidence = generate_explanation(query_text, anime, narrative, score)
        if confidence < CONFIDENCE_THRESHOLD:
            continue
        results.append(RecommendationResult(
            anime=anime,
            narrative=narrative,
            similarity_score=score,
            explanation=explanation,
            match_reasons=reasons,
            match_confidence=confidence,
        ))

    return results


def recommend_from_anime(
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
    candidates = vector_search(db, source_emb.embedding, exclude_ids=excluded, limit=limit * 5)
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)

    results = []
    query_label = f"anime similar to {source_anime.title_romaji}"
    for anime, narrative, score in candidates:
        if len(results) >= limit:
            break
        explanation, reasons, confidence = generate_explanation(query_label, anime, narrative, score)
        if confidence < CONFIDENCE_THRESHOLD:
            continue
        results.append(RecommendationResult(
            anime=anime,
            narrative=narrative,
            similarity_score=score,
            explanation=explanation,
            match_reasons=reasons,
            match_confidence=confidence,
        ))

    return results


def recommend_for_user(
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
    candidates = vector_search(db, avg_vector, exclude_ids=watched_ids, limit=limit * 5)
    candidates = deduplicate_by_series(candidates, db=db)
    candidates = _filter_by_content(candidates, allow_explicit=allow_explicit)

    results = []
    for anime, narrative, score in candidates:
        if len(results) >= limit:
            break
        explanation, reasons, confidence = generate_explanation(
            "anime matching your taste profile", anime, narrative, score
        )
        if confidence < CONFIDENCE_THRESHOLD:
            continue
        results.append(RecommendationResult(
            anime=anime,
            narrative=narrative,
            similarity_score=score,
            explanation=explanation,
            match_reasons=reasons,
            match_confidence=confidence,
        ))

    return results
