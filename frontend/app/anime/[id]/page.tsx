"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import {
  ArrowLeft,
  Star,
  Loader2,
  Swords,
  Brain,
  Flame,
  Users,
  Target,
  Zap,
} from "lucide-react";
import { getAnime, getSimilarAnime } from "@/lib/api";
import { AnimeResultCard } from "@/components/anime-card";
import type { AnimeCard, RecommendationCard } from "@/lib/types";

function NarrativeTag({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | null;
  icon: React.ComponentType<{ className?: string }>;
}) {
  if (!value) return null;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-white/6 bg-white/2 px-3 py-2">
      <Icon className="h-3.5 w-3.5 text-white/25" />
      <div>
        <p className="text-[10px] uppercase tracking-wider text-white/25">
          {label}
        </p>
        <p className="text-sm text-white/70">
          {value.replace(/_/g, " ")}
        </p>
      </div>
    </div>
  );
}

export default function AnimeDetailPage() {
  const params = useParams();
  const id = Number(params.id);

  const [anime, setAnime] = useState<AnimeCard | null>(null);
  const [similar, setSimilar] = useState<RecommendationCard[]>([]);
  const [loadingAnime, setLoadingAnime] = useState(true);
  const [loadingSimilar, setLoadingSimilar] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;

    setLoadingAnime(true);
    setLoadingSimilar(true);

    getAnime(id)
      .then(setAnime)
      .catch(() => setError("Failed to load anime details."))
      .finally(() => setLoadingAnime(false));

    getSimilarAnime(id, 6)
      .then(setSimilar)
      .catch(() => {})
      .finally(() => setLoadingSimilar(false));
  }, [id]);

  if (loadingAnime) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-6 w-6 animate-spin text-white/20" />
      </div>
    );
  }

  if (error || !anime) {
    return (
      <div className="py-32 text-center">
        <p className="text-sm text-white/40">{error || "Anime not found."}</p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center gap-1.5 text-sm text-white/50 hover:text-white/70"
        >
          <ArrowLeft className="h-4 w-4" /> Back to search
        </Link>
      </div>
    );
  }

  const displayTitle = anime.title_english || anime.title;
  const n = anime.narrative;

  return (
    <div className="pb-16 pt-8">
      {/* Back */}
      <Link
        href="/"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-white/30 transition-colors hover:text-white/60"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back
      </Link>

      {/* Hero */}
      <div className="flex gap-6">
        {/* Cover */}
        <div className="relative h-[280px] w-[190px] flex-shrink-0 overflow-hidden rounded-xl">
          {anime.cover_image ? (
            <Image
              src={anime.cover_image}
              alt={displayTitle}
              fill
              className="object-cover"
              sizes="190px"
              priority
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-white/5 text-sm text-white/20">
              No image
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex flex-1 flex-col justify-between">
          <div>
            <h1 className="mb-1 text-2xl font-bold tracking-tight text-white/95">
              {displayTitle}
            </h1>
            {anime.title_english && anime.title !== anime.title_english && (
              <p className="mb-3 text-sm text-white/30">{anime.title}</p>
            )}

            {/* Meta row */}
            <div className="mb-4 flex flex-wrap items-center gap-3 text-sm text-white/40">
              {anime.average_score && (
                <span className="flex items-center gap-1">
                  <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
                  {anime.average_score}%
                </span>
              )}
              {anime.season_year && <span>{anime.season_year}</span>}
              {anime.episodes && <span>{anime.episodes} episodes</span>}
            </div>

            {/* Genres */}
            {anime.genres && anime.genres.length > 0 && (
              <div className="mb-4 flex flex-wrap gap-1.5">
                {anime.genres.map((g) => (
                  <span
                    key={g}
                    className="rounded-md border border-white/6 bg-white/3 px-2 py-0.5 text-xs text-white/40"
                  >
                    {g}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Narrative Schema */}
      {n && (
        <div className="mt-10">
          <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-white/25">
            Narrative DNA
          </h2>

          {/* Tags grid */}
          <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <NarrativeTag
              label="Archetype"
              value={n.protagonist_archetype}
              icon={Users}
            />
            <NarrativeTag label="Tone" value={n.tone} icon={Brain} />
            <NarrativeTag label="Growth" value={n.growth_type} icon={Zap} />
            <NarrativeTag
              label="Conflict"
              value={n.conflict_type}
              icon={Swords}
            />
            <NarrativeTag label="Stakes" value={n.stakes_level} icon={Target} />
            <NarrativeTag label="Pacing" value={n.pacing} icon={Flame} />
          </div>

          {/* Themes */}
          {n.themes && n.themes.length > 0 && (
            <div className="mb-6">
              <p className="mb-2 text-[10px] uppercase tracking-wider text-white/25">
                Themes
              </p>
              <div className="flex flex-wrap gap-1.5">
                {n.themes.map((t) => (
                  <span
                    key={t}
                    className="rounded-full border border-emerald-500/15 bg-emerald-500/5 px-2.5 py-0.5 text-xs text-emerald-400/70"
                  >
                    {t.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Relationships */}
          {n.relationship_types && n.relationship_types.length > 0 && (
            <div>
              <p className="mb-2 text-[10px] uppercase tracking-wider text-white/25">
                Relationships
              </p>
              <div className="flex flex-wrap gap-1.5">
                {n.relationship_types.map((r) => (
                  <span
                    key={r}
                    className="rounded-full border border-violet-500/15 bg-violet-500/5 px-2.5 py-0.5 text-xs text-violet-400/70"
                  >
                    {r.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Motivation */}
          {n.protagonist_motivation && (
            <div className="mt-6 rounded-lg border border-white/6 bg-white/2 p-4">
              <p className="mb-1 text-[10px] uppercase tracking-wider text-white/25">
                Protagonist Motivation
              </p>
              <p className="text-sm italic text-white/50">
                &ldquo;{n.protagonist_motivation}&rdquo;
              </p>
            </div>
          )}
        </div>
      )}

      {/* Similar Anime */}
      <div className="mt-12">
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-white/25">
          Similar Anime
        </h2>

        {loadingSimilar ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-white/20" />
          </div>
        ) : similar.length > 0 ? (
          <div className="space-y-3">
            {similar.map((result) => (
              <AnimeResultCard key={result.anime.id} result={result} />
            ))}
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-white/25">
            No similar anime found.
          </p>
        )}
      </div>
    </div>
  );
}
