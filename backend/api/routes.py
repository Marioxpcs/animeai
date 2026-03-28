"""
api/routes.py
FastAPI REST API — all endpoints the frontend calls.

Endpoints:
  GET  /api/anime/search          → NL query recommendations
  GET  /api/anime/search/stream   → SSE streaming search
  GET  /api/anime/{id}/similar    → Similarity-based recommendations
  GET  /api/anime/{id}            → Single anime detail
  GET  /api/anime/search/instant  → Fast search by title (autocomplete)
  POST /api/ratings               → Submit a user rating
  GET  /api/users/{id}/feed       → Personalized home feed
"""

import json
import time
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from db.database import get_db
from db.schema import Anime, AnimeNarrative, UserRating, User
from engine.recommender import (
    recommend_from_query,
    recommend_from_anime,
    recommend_for_user,
    search_candidates,
    generate_explanations_stream,
    RecommendationResult,
    CONFIDENCE_THRESHOLD,
)
from engine import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ─── Response Models ──────────────────────────────────────────────────────────

class NarrativeSchema(BaseModel):
    protagonist_archetype:  Optional[str]
    power_origin:           Optional[str]
    growth_type:            Optional[str]
    protagonist_motivation: Optional[str]
    conflict_type:          Optional[str]
    pacing:                 Optional[str]
    tone:                   Optional[str]
    themes:                 Optional[list[str]]
    relationship_types:     Optional[list[str]]
    team_dynamics:          Optional[str]
    stakes_level:           Optional[str]


class AnimeCard(BaseModel):
    id:             int
    title:          str
    title_english:  Optional[str]
    cover_image:    Optional[str]
    average_score:  Optional[float]
    episodes:       Optional[int]
    season_year:    Optional[int]
    genres:         Optional[list[str]]
    narrative:      Optional[NarrativeSchema]


class RecommendationCard(BaseModel):
    anime:            AnimeCard
    similarity_score: float
    explanation:      str
    match_reasons:    list[str]
    match_confidence: float = 1.0


class RatingRequest(BaseModel):
    user_id:     str
    anime_id:    int
    rating_type: str    # LIKED | DISLIKED | COMPLETED | DROPPED | PLAN_TO_WATCH
    score:       Optional[float] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def anime_to_card(anime: Anime, narrative: Optional[AnimeNarrative] = None) -> AnimeCard:
    return AnimeCard(
        id=anime.id,
        title=anime.title_romaji,
        title_english=anime.title_english,
        cover_image=anime.cover_image,
        average_score=anime.average_score,
        episodes=anime.episodes,
        season_year=anime.season_year,
        genres=anime.genres or [],
        narrative=NarrativeSchema(
            protagonist_archetype  = narrative.protagonist_archetype,
            power_origin           = narrative.power_origin,
            growth_type            = narrative.growth_type,
            protagonist_motivation = narrative.protagonist_motivation,
            conflict_type          = narrative.conflict_type,
            pacing                 = narrative.pacing,
            tone                   = narrative.tone,
            themes                 = narrative.themes,
            relationship_types     = narrative.relationship_types,
            team_dynamics          = narrative.team_dynamics,
            stakes_level           = narrative.stakes_level,
        ) if narrative else None
    )


def result_to_card(result: RecommendationResult) -> RecommendationCard:
    return RecommendationCard(
        anime=anime_to_card(result.anime, result.narrative),
        similarity_score=result.similarity_score,
        explanation=result.explanation,
        match_reasons=result.match_reasons,
        match_confidence=result.match_confidence,
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/anime/search", response_model=list[RecommendationCard])
async def search_anime(
    q:       str  = Query(..., min_length=3, description="Natural language query"),
    limit:   int  = Query(20, ge=1, le=50),
    nocache: bool = Query(False),
    db:      Session = Depends(get_db)
):
    """
    Natural language anime discovery.
    Example: GET /api/anime/search?q=underdog+who+works+hard+to+get+stronger
    """
    # Check cache (unless bypassed)
    if not nocache:
        cached = cache.get(q)
        if cached is not None:
            return cached

    results = await recommend_from_query(db, q, limit=limit)
    cards = [result_to_card(r) for r in results]

    # Store in cache
    if not nocache:
        cache.put(q, [c.model_dump() for c in cards])

    return cards


@router.get("/anime/search/stream")
async def search_anime_stream(
    q:     str = Query(..., min_length=3, description="Natural language query"),
    limit: int = Query(20, ge=1, le=50),
    db:    Session = Depends(get_db),
):
    """
    SSE streaming search: sends anime cards immediately, then streams each
    explanation as it arrives (parallel Haiku calls, one per anime).
    """
    async def event_stream():
        t_total = time.time()
        try:
            # Phase 1: intent parse + embed + vector search (logged inside search_candidates)
            candidates, query_label = await search_candidates(db, q, limit=limit)

            # Emit results immediately — cards visible on frontend within ~2s
            results_payload = []
            for anime, narrative, score in candidates:
                card = anime_to_card(anime, narrative)
                results_payload.append({**card.model_dump(), "similarity_score": score})
            yield f"event: results\ndata: {json.dumps(results_payload)}\n\n"
            logger.info("TIMING | results_event_sent: %.2fs", time.time() - t_total)

            # Phase 2: parallel Haiku calls, one per anime — yield each as it arrives
            if candidates:
                t0 = time.time()
                queue = await generate_explanations_stream(query_label, candidates)
                for _ in range(len(candidates)):
                    payload = await queue.get()
                    yield f"event: explanation\ndata: {json.dumps(payload)}\n\n"
                logger.info("TIMING | explanation_gen (all): %.2fs", time.time() - t0)

            yield "event: done\ndata: {}\n\n"
            logger.info("TIMING | total: %.2fs", time.time() - t_total)

        except Exception as exc:
            logger.error("SSE stream error: %s", exc)
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/anime/{anime_id}/similar", response_model=list[RecommendationCard])
async def get_similar(
    anime_id:    int,
    exclude_ids: str  = Query("", description="Comma-separated anime IDs to exclude"),
    limit:       int  = Query(20, ge=1, le=50),
    db:          Session = Depends(get_db)
):
    """
    Get anime similar to a given title.
    Example: GET /api/anime/21/similar  (21 = One Piece on AniList)
    """
    excluded = [int(x) for x in exclude_ids.split(",") if x.strip().isdigit()]
    results  = await recommend_from_anime(db, anime_id, exclude_ids=excluded, limit=limit)
    return [result_to_card(r) for r in results]


@router.get("/anime/{anime_id}", response_model=AnimeCard)
def get_anime(anime_id: int, db: Session = Depends(get_db)):
    """Get full detail for a single anime."""
    anime = db.query(Anime).filter(Anime.id == anime_id).first()
    if not anime:
        raise HTTPException(status_code=404, detail="Anime not found")
    narrative = db.query(AnimeNarrative).filter(AnimeNarrative.anime_id == anime_id).first()
    return anime_to_card(anime, narrative)


@router.get("/anime", response_model=list[AnimeCard])
def list_anime(
    search: str = Query("", description="Title search"),
    limit:  int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db:     Session = Depends(get_db)
):
    """
    Title search / browse — used for autocomplete and explore page.
    """
    query = db.query(Anime)
    if search:
        query = query.filter(
            Anime.title_romaji.ilike(f"%{search}%") |
            Anime.title_english.ilike(f"%{search}%")
        )
    anime_list = query.order_by(Anime.popularity.desc()).offset(offset).limit(limit).all()
    return [anime_to_card(a) for a in anime_list]


@router.post("/ratings", status_code=201)
def submit_rating(body: RatingRequest, db: Session = Depends(get_db)):
    """
    Submit or update a user rating for an anime.
    Creates user if not exists (for MVP, we skip full auth).
    """
    valid_types = {"LIKED", "DISLIKED", "COMPLETED", "DROPPED", "PLAN_TO_WATCH"}
    if body.rating_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"rating_type must be one of {valid_types}")

    # Upsert user
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        db.add(User(id=body.user_id, email=f"{body.user_id}@temp.local"))
        db.flush()

    # Upsert rating
    existing = db.query(UserRating).filter(
        UserRating.user_id == body.user_id,
        UserRating.anime_id == body.anime_id
    ).first()

    if existing:
        existing.rating_type = body.rating_type
        existing.score       = body.score
    else:
        db.add(UserRating(
            user_id     = body.user_id,
            anime_id    = body.anime_id,
            rating_type = body.rating_type,
            score       = body.score,
        ))

    db.commit()
    return {"status": "ok"}


@router.get("/users/{user_id}/feed", response_model=list[RecommendationCard])
async def get_user_feed(
    user_id: str,
    limit:   int = Query(10, ge=1, le=30),
    db:      Session = Depends(get_db)
):
    """
    Personalized home feed based on user's liked anime.
    Falls back to popular anime if no ratings yet.
    """
    results = await recommend_for_user(db, user_id, limit=limit)

    if not results:
        # Cold-start fallback: return top-rated enriched anime
        top_anime = (
            db.query(Anime, AnimeNarrative)
            .join(AnimeNarrative, Anime.id == AnimeNarrative.anime_id)
            .order_by(Anime.average_score.desc())
            .limit(limit)
            .all()
        )
        return [
            RecommendationCard(
                anime=anime_to_card(a, n),
                similarity_score=1.0,
                explanation="Highly rated anime to get you started.",
                match_reasons=["Top-rated in our database", "Rate anime to unlock personalized picks"]
            )
            for a, n in top_anime
        ]

    return [result_to_card(r) for r in results]
