"""
db/schema.py
Core database schema for AnimeAI.

Tables:
  - anime           : Base metadata from AniList
  - anime_narrative : Enriched narrative schema (filled by AI pipeline)
  - anime_embedding : pgvector embedding for similarity search
  - users           : User accounts
  - user_ratings    : User ratings/likes per anime
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float, Boolean,
    DateTime, JSON, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()

# ─── Embedding dimensions ────────────────────────────────────────────────────
# sentence-transformers/all-mpnet-base-v2 outputs 768 dims.
# If you switch models, update this constant + re-embed everything.
EMBEDDING_DIM = 768


class Anime(Base):
    """
    Raw anime metadata ingested from AniList.
    This is the source-of-truth record for every title.
    """
    __tablename__ = "anime"

    id             = Column(Integer, primary_key=True)          # AniList ID
    title_romaji   = Column(String(512), nullable=False)
    title_english  = Column(String(512), nullable=True)
    title_native   = Column(String(512), nullable=True)         # Japanese title
    description    = Column(Text, nullable=True)                # HTML-stripped synopsis
    episodes       = Column(Integer, nullable=True)
    status         = Column(String(64), nullable=True)          # FINISHED | RELEASING | etc.
    season         = Column(String(32), nullable=True)          # WINTER | SPRING | SUMMER | FALL
    season_year    = Column(Integer, nullable=True)
    format         = Column(String(32), nullable=True)          # TV | MOVIE | OVA | ONA | SPECIAL
    genres         = Column(JSON, nullable=True)                # ["Action", "Adventure", ...]
    tags           = Column(JSON, nullable=True)                # AniList community tags with weights
    average_score  = Column(Float, nullable=True)               # 0–100
    popularity     = Column(Integer, nullable=True)             # AniList popularity count
    cover_image    = Column(String(1024), nullable=True)
    banner_image   = Column(String(1024), nullable=True)
    studios        = Column(JSON, nullable=True)                # ["MAPPA", "Bones", ...]
    source         = Column(String(64), nullable=True)          # MANGA | ORIGINAL | LIGHT_NOVEL | etc.
    series_root_id = Column(Integer, nullable=True)              # AniList ID of first season in series
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    narrative      = relationship("AnimeNarrative", back_populates="anime", uselist=False)
    embedding      = relationship("AnimeEmbedding", back_populates="anime", uselist=False)

    def __repr__(self):
        return f"<Anime id={self.id} title='{self.title_romaji}'>"


class AnimeNarrative(Base):
    """
    AI-enriched narrative schema.
    This is the secret sauce — the structured representation that powers
    semantic similarity beyond genre tags.

    Populated by pipeline/enricher.py using Claude.
    """
    __tablename__ = "anime_narrative"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    anime_id              = Column(Integer, ForeignKey("anime.id"), unique=True, nullable=False)

    # ── Protagonist Dimensions ─────────────────────────────────────────────
    protagonist_archetype = Column(String(128), nullable=True)
    # e.g. underdog | prodigy | reluctant_hero | anti_hero | ensemble

    power_origin          = Column(String(128), nullable=True)
    # e.g. earned | gifted | stolen | inherited | tactical | none

    growth_type           = Column(String(128), nullable=True)
    # e.g. slow_burn | rapid_ascension | plateau_breakthrough | regression | static

    protagonist_motivation = Column(String(256), nullable=True)
    # e.g. revenge | protect_loved_ones | personal_glory | survival | belonging

    # ── Narrative Structure ────────────────────────────────────────────────
    conflict_type         = Column(String(128), nullable=True)
    # e.g. martial | interpersonal | societal | existential | investigative

    pacing                = Column(String(64), nullable=True)
    # e.g. slow_build | fast_start | episodic | arc_driven

    power_system          = Column(String(128), nullable=True)
    # e.g. hard_magic | soft_magic | physical_realism | tech_based | none

    stakes_level          = Column(String(64), nullable=True)
    # e.g. personal | community | national | global | cosmic

    tone                  = Column(String(128), nullable=True)
    # e.g. dark | comedic | bittersweet | hopeful | philosophical

    # ── Themes (array of strings) ──────────────────────────────────────────
    themes                = Column(JSON, nullable=True)
    # e.g. ["perseverance", "rivalry", "friendship", "sacrifice", "identity"]

    # ── Relational Dynamics ────────────────────────────────────────────────
    relationship_types    = Column(JSON, nullable=True)
    # e.g. ["mentor_student", "rival_rival", "found_family"]

    team_dynamics         = Column(String(64), nullable=True)
    # e.g. solo | small_squad | large_ensemble | faction_based

    antagonist_design     = Column(String(128), nullable=True)
    # e.g. personal_nemesis | systemic_oppressor | complex_villain | force_of_nature

    # ── Content Classification ───────────────────────────────────────────
    content_level         = Column(String(32), nullable=True)
    # "clean" | "suggestive" | "ecchi" | "explicit"

    # ── Free-text Narrative Summary ────────────────────────────────────────
    # Written by Claude; used as the source text for embedding generation.
    narrative_summary     = Column(Text, nullable=True)

    # ── Quality Signals ────────────────────────────────────────────────────
    enrichment_confidence = Column(Float, nullable=True)   # 0.0–1.0
    enriched_at           = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    anime                 = relationship("Anime", back_populates="narrative")

    def __repr__(self):
        return f"<AnimeNarrative anime_id={self.anime_id} archetype='{self.protagonist_archetype}'>"


class AnimeEmbedding(Base):
    """
    pgvector embedding for semantic similarity search.
    Generated from AnimeNarrative.narrative_summary using the Anthropic
    embedding API (or OpenAI text-embedding-3-large as fallback).
    """
    __tablename__ = "anime_embedding"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    anime_id   = Column(Integer, ForeignKey("anime.id"), unique=True, nullable=False)
    embedding  = Column(Vector(EMBEDDING_DIM), nullable=False)
    model_used = Column(String(128), nullable=True)             # track which model generated it
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    anime      = relationship("Anime", back_populates="embedding")


class User(Base):
    """User accounts."""
    __tablename__ = "users"

    id         = Column(String(64), primary_key=True)           # UUID from Supabase auth
    email      = Column(String(256), unique=True, nullable=False)
    username   = Column(String(128), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    ratings    = relationship("UserRating", back_populates="user")


class UserRating(Base):
    """
    User ratings and feedback on anime.
    This is the behavioral signal that powers personalized recommendations.

    rating_type:
      LIKED       → thumbs up / added to favorites
      DISLIKED    → not for me
      COMPLETED   → watched and finished (neutral)
      DROPPED     → started but stopped
      PLAN_TO_WATCH → on watchlist
    """
    __tablename__ = "user_ratings"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(String(64), ForeignKey("users.id"), nullable=False)
    anime_id    = Column(Integer, ForeignKey("anime.id"), nullable=False)
    rating_type = Column(String(32), nullable=False)
    score       = Column(Float, nullable=True)                  # optional 1–10
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user        = relationship("User", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("user_id", "anime_id", name="uq_user_anime_rating"),
    )


# ─── Indexes ─────────────────────────────────────────────────────────────────
# These are created via Alembic migration, but defined here for reference.
#
# CREATE INDEX ON anime_embedding USING ivfflat (embedding vector_cosine_ops)
#   WITH (lists = 100);
#
# This enables fast approximate nearest-neighbor search.
# Run AFTER bulk-inserting at least 1000+ rows for best results.
