"""
pipeline/reembed.py
Re-generate embeddings for all enriched anime using Cohere.
Does NOT re-run Claude narrative extraction — just the embedding step.

Usage:
    python -m pipeline.reembed
"""

import time
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from db.database import SessionLocal
from db.schema import AnimeNarrative, AnimeEmbedding, Anime
from pipeline.enricher import generate_embedding
from dotenv import load_dotenv

load_dotenv()

console = Console()
app = typer.Typer()


@app.command()
def run():
    """Re-embed all enriched anime with Cohere embed-english-v3.0."""
    console.rule("[bold blue]AnimeAI — Re-embed with Cohere[/bold blue]")

    db = SessionLocal()
    narratives = db.query(AnimeNarrative).all()
    console.print(f"[cyan]Re-embedding {len(narratives)} anime...[/cyan]\n")

    succeeded = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding...", total=len(narratives))

        for narr in narratives:
            anime = db.query(Anime).filter(Anime.id == narr.anime_id).first()
            title = anime.title_romaji if anime else f"ID {narr.anime_id}"
            progress.update(task, description=f"[cyan]{title[:45]}")

            # Skip if already re-embedded with Cohere
            existing = db.query(AnimeEmbedding).filter(
                AnimeEmbedding.anime_id == narr.anime_id,
                AnimeEmbedding.model_used == "cohere-embed-english-v3.0"
            ).first()
            if existing:
                succeeded += 1
                progress.advance(task)
                continue

            if not narr.narrative_summary:
                failed += 1
                progress.advance(task)
                continue

            # Build same embedding text as enricher
            themes_str = ", ".join(narr.themes or [])
            embedding_text = (
                f"{title}. {narr.narrative_summary} "
                f"Themes: {themes_str}. "
                f"Protagonist: {narr.protagonist_archetype}. "
                f"Tone: {narr.tone}. "
                f"Growth: {narr.growth_type}."
            )

            vector = generate_embedding(embedding_text, input_type="search_document")
            if not vector:
                failed += 1
                progress.advance(task)
                continue

            # Upsert embedding
            existing = db.query(AnimeEmbedding).filter(
                AnimeEmbedding.anime_id == narr.anime_id
            ).first()

            if existing:
                existing.embedding = vector
                existing.model_used = "cohere-embed-english-v3.0"
            else:
                db.add(AnimeEmbedding(
                    anime_id=narr.anime_id,
                    embedding=vector,
                    model_used="cohere-embed-english-v3.0",
                ))

            db.commit()
            succeeded += 1
            progress.advance(task)
            time.sleep(0.7)  # Stay under 100 calls/min rate limit

    db.close()
    console.rule("[bold green]Re-embedding Complete[/bold green]")
    console.print(f"  Succeeded: [bold green]{succeeded}[/bold green]")
    console.print(f"  Failed:    [bold red]{failed}[/bold red]")


if __name__ == "__main__":
    app()
