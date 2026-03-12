"""
pipeline/enricher.py
The most important script in the entire codebase.

Takes raw anime records from the database and uses Claude to extract a
structured narrative schema for each one. This is what powers semantic
recommendation beyond genre tags.

Usage:
    python -m pipeline.enricher --batch-size 20
    python -m pipeline.enricher --anime-id 21   # enrich a single title
    python -m pipeline.enricher --re-enrich     # re-run on already-enriched titles

How it works:
  1. Pull un-enriched anime records from DB (has description, no narrative row)
  2. For each: send title + description + genres + tags to Claude
  3. Claude returns structured JSON with narrative dimensions
  4. Save AnimeNarrative row + generate embedding from narrative_summary
  5. Save AnimeEmbedding row
"""

import os
import json
import asyncio
import time
import typer
import anthropic
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from sqlalchemy.orm import Session
from db.database import SessionLocal, init_db
from db.schema import Anime, AnimeNarrative, AnimeEmbedding
from dotenv import load_dotenv

load_dotenv()

console = Console()
app = typer.Typer()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─── Narrative extraction prompt ─────────────────────────────────────────────
# This prompt is the most important piece of engineering in the whole product.
# It instructs Claude to extract structured narrative dimensions from an anime's
# metadata. Critically: Claude should ONLY use what's in the provided data,
# never hallucinate details.

EXTRACTION_SYSTEM_PROMPT = """
You are an expert anime analyst tasked with extracting structured narrative metadata from anime descriptions.

Your job is to analyze an anime's title, synopsis, genres, and community tags, then return a precise JSON object describing its narrative structure.

CRITICAL RULES:
- Only use information present in the provided data. Never invent plot details.
- If a field cannot be determined from the given data, use null.
- Be consistent: use the exact enum values listed for each field.
- The narrative_summary must be a 3-5 sentence rich description that captures the story's feel, themes, and structure — written to maximize semantic similarity with other anime that feel the same way. Avoid spoilers.

Return ONLY valid JSON. No explanation, no markdown, no preamble.
"""

def build_extraction_prompt(anime: Anime) -> str:
    genres_str = ", ".join(anime.genres or [])
    tags_str   = ", ".join([t["name"] for t in (anime.tags or [])][:15])

    return f"""Analyze this anime and return a structured JSON object.

ANIME DATA:
Title: {anime.title_romaji}
{f'English Title: {anime.title_english}' if anime.title_english else ''}
Synopsis: {anime.description or 'No synopsis available.'}
Genres: {genres_str or 'None listed'}
Community Tags: {tags_str or 'None listed'}
Format: {anime.format}
Episodes: {anime.episodes}
Year: {anime.season_year}

RETURN THIS EXACT JSON STRUCTURE (use null for unknown fields):
{{
  "protagonist_archetype": <"underdog"|"prodigy"|"reluctant_hero"|"anti_hero"|"ensemble"|"everyman"|null>,
  "power_origin": <"earned"|"gifted"|"stolen"|"inherited"|"tactical"|"none"|null>,
  "growth_type": <"slow_burn"|"rapid_ascension"|"plateau_breakthrough"|"regression"|"static"|null>,
  "protagonist_motivation": <string describing the main character's core drive, max 80 chars, or null>,
  "conflict_type": <"martial"|"interpersonal"|"societal"|"existential"|"investigative"|"survival"|null>,
  "pacing": <"slow_build"|"fast_start"|"episodic"|"arc_driven"|"steady"|null>,
  "power_system": <"hard_magic"|"soft_magic"|"physical_realism"|"tech_based"|"none"|null>,
  "stakes_level": <"personal"|"community"|"national"|"global"|"cosmic"|null>,
  "tone": <"dark"|"comedic"|"bittersweet"|"hopeful"|"philosophical"|"action_focused"|null>,
  "themes": [<list of 3-6 theme strings, e.g. "perseverance", "rivalry", "identity", "sacrifice">],
  "relationship_types": [<list of relevant: "mentor_student"|"rival_rival"|"romantic"|"found_family"|"lone_wolf"|"brotherhood">],
  "team_dynamics": <"solo"|"small_squad"|"large_ensemble"|"faction_based"|null>,
  "antagonist_design": <"personal_nemesis"|"systemic_oppressor"|"complex_villain"|"force_of_nature"|"no_clear_antagonist"|null>,
  "narrative_summary": <rich 3-5 sentence description capturing story feel, themes, structure — written to match with similar anime>,
  "enrichment_confidence": <float 0.0-1.0 representing how confident you are given the available data>
}}"""


def extract_narrative(anime: Anime) -> dict | None:
    """
    Call Claude to extract narrative schema from anime metadata.
    Returns parsed JSON dict or None on failure.
    """
    prompt = build_extraction_prompt(anime)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_text = message.content[0].text.strip()

        # Strip accidental markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        return json.loads(raw_text)

    except json.JSONDecodeError as e:
        console.print(f"[red]JSON parse error for {anime.title_romaji}: {e}[/red]")
        return None
    except anthropic.APIError as e:
        console.print(f"[red]API error for {anime.title_romaji}: {e}[/red]")
        return None


# ─── Sentence-transformers model (loaded once, reused) ───────────────────────
_embedding_model = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-mpnet-base-v2")
        console.print("[dim]Loaded embedding model: all-mpnet-base-v2 (768d)[/dim]")
    return _embedding_model


def generate_embedding(text: str) -> list[float] | None:
    """
    Generate a 768-dim vector embedding using sentence-transformers/all-mpnet-base-v2.
    Runs locally — no API key needed.
    """
    try:
        model = _get_embedding_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()
    except Exception as e:
        console.print(f"[red]Embedding error: {e}[/red]")
        return None


def enrich_anime(db: Session, anime: Anime) -> bool:
    """
    Enrich one anime with narrative schema + embedding.
    Returns True on success, False on failure.
    """
    # ── Step 1: Extract narrative schema via Claude ──────────────────────────
    narrative_data = extract_narrative(anime)
    if not narrative_data:
        return False

    # ── Step 2: Save or update AnimeNarrative row ────────────────────────────
    existing_narrative = db.query(AnimeNarrative).filter(
        AnimeNarrative.anime_id == anime.id
    ).first()

    if existing_narrative:
        for key, val in narrative_data.items():
            if hasattr(existing_narrative, key):
                setattr(existing_narrative, key, val)
    else:
        narrative = AnimeNarrative(
            anime_id=anime.id,
            protagonist_archetype   = narrative_data.get("protagonist_archetype"),
            power_origin            = narrative_data.get("power_origin"),
            growth_type             = narrative_data.get("growth_type"),
            protagonist_motivation  = narrative_data.get("protagonist_motivation"),
            conflict_type           = narrative_data.get("conflict_type"),
            pacing                  = narrative_data.get("pacing"),
            power_system            = narrative_data.get("power_system"),
            stakes_level            = narrative_data.get("stakes_level"),
            tone                    = narrative_data.get("tone"),
            themes                  = narrative_data.get("themes"),
            relationship_types      = narrative_data.get("relationship_types"),
            team_dynamics           = narrative_data.get("team_dynamics"),
            antagonist_design       = narrative_data.get("antagonist_design"),
            narrative_summary       = narrative_data.get("narrative_summary"),
            enrichment_confidence   = narrative_data.get("enrichment_confidence"),
        )
        db.add(narrative)

    db.flush()

    # ── Step 3: Generate and save embedding ──────────────────────────────────
    summary = narrative_data.get("narrative_summary")
    if summary:
        # Build a richer text for embedding: summary + themes + archetype
        themes_str    = ", ".join(narrative_data.get("themes") or [])
        embedding_text = (
            f"{anime.title_romaji}. {summary} "
            f"Themes: {themes_str}. "
            f"Protagonist: {narrative_data.get('protagonist_archetype')}. "
            f"Tone: {narrative_data.get('tone')}. "
            f"Growth: {narrative_data.get('growth_type')}."
        )
        vector = generate_embedding(embedding_text)

        if vector:
            existing_emb = db.query(AnimeEmbedding).filter(
                AnimeEmbedding.anime_id == anime.id
            ).first()

            if existing_emb:
                existing_emb.embedding  = vector
                existing_emb.model_used = "all-mpnet-base-v2"
            else:
                db.add(AnimeEmbedding(
                    anime_id   = anime.id,
                    embedding  = vector,
                    model_used = "all-mpnet-base-v2"
                ))

    db.commit()
    return True


@app.command()
def run(
    batch_size:  int  = typer.Option(20,    help="Anime to enrich per run"),
    anime_id:    int  = typer.Option(None,  help="Enrich a specific anime by AniList ID"),
    re_enrich:   bool = typer.Option(False, help="Re-enrich already-processed anime"),
    show_sample: bool = typer.Option(False, help="Print a sample extracted narrative"),
):
    """
    Enrich anime records with AI-extracted narrative schema.

    Requires ANTHROPIC_API_KEY in .env
    Processes un-enriched anime in order of popularity.
    """
    console.rule("[bold blue]AnimeAI — Narrative Enrichment Pipeline[/bold blue]")

    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[bold red]Error: ANTHROPIC_API_KEY not set in .env[/bold red]")
        raise typer.Exit(1)

    db = SessionLocal()
    succeeded = 0
    failed    = 0

    # ── Select which anime to enrich ─────────────────────────────────────────
    if anime_id:
        targets = db.query(Anime).filter(Anime.id == anime_id).all()
        if not targets:
            console.print(f"[red]No anime found with ID {anime_id}[/red]")
            raise typer.Exit(1)
    elif re_enrich:
        targets = db.query(Anime).order_by(Anime.popularity.desc()).limit(batch_size).all()
    else:
        # Only un-enriched anime (no narrative row yet)
        enriched_ids = db.query(AnimeNarrative.anime_id).subquery()
        targets = (
            db.query(Anime)
            .filter(Anime.id.not_in(enriched_ids))
            .filter(Anime.description.isnot(None))   # Skip anime with no synopsis
            .order_by(Anime.popularity.desc())
            .limit(batch_size)
            .all()
        )

    if not targets:
        console.print("[green]All anime are already enriched! Run with --re-enrich to re-process.[/green]")
        db.close()
        return

    console.print(f"[cyan]Enriching {len(targets)} anime...[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Enriching...", total=len(targets))

        for anime in targets:
            progress.update(task, description=f"[cyan]{anime.title_romaji[:45]}")

            success = enrich_anime(db, anime)

            if success:
                succeeded += 1
                if show_sample and succeeded == 1:
                    # Print the first enriched narrative as a sample
                    narr = db.query(AnimeNarrative).filter(
                        AnimeNarrative.anime_id == anime.id
                    ).first()
                    if narr:
                        console.print(Panel(
                            f"[bold]{anime.title_romaji}[/bold]\n\n"
                            f"Archetype:   {narr.protagonist_archetype}\n"
                            f"Power:       {narr.power_origin} / {narr.growth_type}\n"
                            f"Tone:        {narr.tone}\n"
                            f"Themes:      {', '.join(narr.themes or [])}\n"
                            f"Pacing:      {narr.pacing}\n"
                            f"Conflict:    {narr.conflict_type}\n"
                            f"Team:        {narr.team_dynamics}\n"
                            f"Stakes:      {narr.stakes_level}\n\n"
                            f"[italic]{narr.narrative_summary}[/italic]",
                            title="[green]Sample Enriched Narrative[/green]",
                            border_style="green"
                        ))
            else:
                failed += 1

            progress.advance(task)
            # Respect API rate limits
            time.sleep(0.3)

    db.close()

    console.rule("[bold green]Enrichment Complete[/bold green]")
    console.print(f"  ✅ Succeeded: [bold green]{succeeded}[/bold green]")
    console.print(f"  ❌ Failed:    [bold red]{failed}[/bold red]")
    console.print()
    console.print("[bold]Next step:[/bold] Run [cyan]python -m engine.recommender[/cyan] to test similarity search.")


if __name__ == "__main__":
    app()
