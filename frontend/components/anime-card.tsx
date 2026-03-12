"use client";

import Link from "next/link";
import Image from "next/image";
import { Star, ChevronRight } from "lucide-react";
import type { RecommendationCard } from "@/lib/types";

export function AnimeResultCard({ result }: { result: RecommendationCard }) {
  const { anime, similarity_score, explanation, match_reasons } = result;
  const displayTitle = anime.title_english || anime.title;
  const pct = Math.round(similarity_score * 100);

  return (
    <Link href={`/anime/${anime.id}`}>
      <div className="group relative flex gap-4 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 transition-all hover:border-white/[0.12] hover:bg-white/[0.04]">
        {/* Cover */}
        <div className="relative h-[180px] w-[120px] flex-shrink-0 overflow-hidden rounded-lg">
          {anime.cover_image ? (
            <Image
              src={anime.cover_image}
              alt={displayTitle}
              fill
              className="object-cover"
              sizes="120px"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-white/[0.05] text-xs text-white/30">
              No image
            </div>
          )}
          {/* Score badge */}
          {anime.average_score && (
            <div className="absolute left-1.5 top-1.5 flex items-center gap-0.5 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-medium backdrop-blur-sm">
              <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
              <span className="text-white/90">{anime.average_score}%</span>
            </div>
          )}
        </div>

        {/* Content */}
        <div className="flex min-w-0 flex-1 flex-col justify-between">
          <div>
            {/* Header */}
            <div className="mb-1.5 flex items-start justify-between gap-2">
              <h3 className="text-[15px] font-semibold leading-tight text-white/90 group-hover:text-white">
                {displayTitle}
              </h3>
              <span className="flex-shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
                {pct}%
              </span>
            </div>

            {/* Meta */}
            <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-white/40">
              {anime.season_year && <span>{anime.season_year}</span>}
              {anime.episodes && <span>{anime.episodes} ep</span>}
              {anime.genres?.slice(0, 3).map((g) => (
                <span key={g}>{g}</span>
              ))}
            </div>

            {/* Explanation */}
            <p className="mb-2 text-[13px] leading-relaxed text-white/50">
              {explanation}
            </p>

            {/* Match reasons */}
            <ul className="space-y-0.5">
              {match_reasons.slice(0, 3).map((reason, i) => (
                <li
                  key={i}
                  className="flex items-start gap-1.5 text-xs text-white/35"
                >
                  <ChevronRight className="mt-0.5 h-3 w-3 flex-shrink-0 text-emerald-500/50" />
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </Link>
  );
}

export function AnimeCardCompact({
  anime,
  score,
}: {
  anime: RecommendationCard["anime"];
  score?: number;
}) {
  const displayTitle = anime.title_english || anime.title;

  return (
    <Link href={`/anime/${anime.id}`}>
      <div className="group relative overflow-hidden rounded-lg border border-white/[0.06] bg-white/[0.02] transition-all hover:border-white/[0.12] hover:bg-white/[0.04]">
        <div className="relative aspect-[3/4] w-full overflow-hidden">
          {anime.cover_image ? (
            <Image
              src={anime.cover_image}
              alt={displayTitle}
              fill
              className="object-cover transition-transform group-hover:scale-105"
              sizes="(max-width: 768px) 50vw, 200px"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-white/[0.05] text-xs text-white/30">
              No image
            </div>
          )}
          {score !== undefined && (
            <div className="absolute right-1.5 top-1.5 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-medium text-emerald-400 backdrop-blur-sm">
              {Math.round(score * 100)}%
            </div>
          )}
        </div>
        <div className="p-2.5">
          <h4 className="truncate text-sm font-medium text-white/80 group-hover:text-white">
            {displayTitle}
          </h4>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-white/35">
            {anime.average_score && (
              <span className="flex items-center gap-0.5">
                <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
                {anime.average_score}
              </span>
            )}
            {anime.season_year && <span>{anime.season_year}</span>}
          </div>
        </div>
      </div>
    </Link>
  );
}
