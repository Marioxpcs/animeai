"use client";

import { useState, useRef, useCallback } from "react";
import posthog from "posthog-js";
import { Search, Loader2, Sparkles } from "lucide-react";
import { searchAnime, streamSearch } from "@/lib/api";
import { AnimeResultCard } from "@/components/anime-card";
import type { RecommendationCard, StreamResultAnime, StreamExplanation } from "@/lib/types";

export default function Home() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RecommendationCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [explanationsLoaded, setExplanationsLoaded] = useState<Set<number>>(new Set());
  const [cardsReady, setCardsReady] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fallbackSearch = useCallback(async (trimmed: string) => {
    try {
      const data = await searchAnime(trimmed, 20);
      setResults(data);
      setExplanationsLoaded(new Set(data.map((d) => d.anime.id)));
      setCardsReady(true);
      posthog.capture("search_results_viewed", {
        query: trimmed,
        result_count: data.length,
      });
    } catch (err) {
      setError("Failed to fetch recommendations. Is the backend running?");
      setResults([]);
      posthog.capture("search_failed", {
        query: trimmed,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, []);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || loading) return;

    const trimmed = query.trim();
    setLoading(true);
    setError(null);
    setSearched(true);
    setResults([]);
    setExplanationsLoaded(new Set());
    setCardsReady(false);

    // Abort any in-flight stream
    abortRef.current?.abort();

    posthog.capture("search_submitted", {
      query: trimmed,
      query_length: trimmed.length,
    });

    const controller = streamSearch(trimmed, 20, {
      onResults(anime: StreamResultAnime[]) {
        const cards: RecommendationCard[] = anime.map((a) => ({
          anime: {
            id: a.id,
            title: a.title,
            title_english: a.title_english,
            cover_image: a.cover_image,
            average_score: a.average_score,
            episodes: a.episodes,
            season_year: a.season_year,
            genres: a.genres,
            narrative: a.narrative,
          },
          similarity_score: a.similarity_score,
          explanation: "",
          match_reasons: [],
        }));
        setResults(cards);
        setCardsReady(true);
      },
      onExplanation(data: StreamExplanation) {
        setResults((prev) =>
          prev.map((r) =>
            r.anime.id === data.anime_id
              ? {
                  ...r,
                  explanation: data.explanation,
                  match_reasons: data.match_reasons,
                  match_confidence: data.match_confidence,
                }
              : r
          )
        );
        setExplanationsLoaded((prev) => new Set(prev).add(data.anime_id));
      },
      onDone() {
        // Mark any remaining cards without explanations as done
        setResults((prev) => {
          const allIds = new Set(prev.map((r) => r.anime.id));
          setExplanationsLoaded(allIds);
          return prev.map((r) =>
            !r.explanation
              ? { ...r, explanation: "Explanation unavailable." }
              : r
          );
        });
        setLoading(false);
        posthog.capture("search_results_viewed", {
          query: trimmed,
          result_count: -1, // streamed
        });
      },
      onError() {
        // SSE failed — fall back to regular endpoint
        fallbackSearch(trimmed);
      },
    });
    abortRef.current = controller;
  }

  return (
    <div className="flex flex-col">
      {/* Hero */}
      <div
        className={`flex flex-col items-center transition-all duration-500 ${
          searched ? "pb-8 pt-12" : "pb-8 pt-32"
        }`}
      >
        {!searched && (
          <div className="mb-8 text-center">
            <h1 className="mb-3 text-4xl font-bold tracking-tight text-white/95">
              Find your next anime
            </h1>
            <p className="text-[15px] text-white/40">
              Describe what you&apos;re looking for in natural language.
              <br />
              Our AI matches your request against the narrative DNA of 500+
              titles.
            </p>
          </div>
        )}

        {/* Search */}
        <form onSubmit={handleSearch} className="w-full max-w-2xl">
          <div className="group relative">
            <Search className="absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-white/20 transition-colors group-focus-within:text-white/40" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Describe the anime you're looking for..."
              className="w-full rounded-xl border border-white/[0.08] bg-white/[0.03] py-3.5 pl-11 pr-4 text-[15px] text-white/90 placeholder-white/25 outline-none transition-all focus:border-indigo-500/30 focus:bg-white/[0.04] focus:ring-1 focus:ring-indigo-500/20"
              autoFocus
            />
            {loading && (
              <Loader2 className="absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-white/30" />
            )}
          </div>
        </form>

        {/* Example queries */}
        {!searched && (
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {[
              "dark psychological thriller with plot twists",
              "underdog who gets stronger through hard work",
              "wholesome found family with emotional moments",
            ].map((example) => (
              <button
                key={example}
                onClick={() => setQuery(example)}
                className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-xs text-white/35 transition-all hover:border-indigo-500/20 hover:bg-indigo-500/5 hover:text-indigo-300/70"
              >
                <Sparkles className="h-3 w-3" />
                {example}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400/80">
          {error}
        </div>
      )}

      {/* Loading state — before cards arrive */}
      {loading && !cardsReady && (
        <div className="flex flex-col items-center gap-3 py-20">
          <Loader2 className="h-6 w-6 animate-spin text-white/20" />
          <p className="text-sm text-white/30">
            Analyzing your request and finding matches...
          </p>
        </div>
      )}

      {/* Results — show as soon as cards are ready */}
      {cardsReady && results.length > 0 && (
        <div className="space-y-3 pb-16">
          <p className="mb-4 text-xs font-medium uppercase tracking-wider text-white/25">
            {results.length} results
            {loading && (
              <span className="ml-2 inline-flex items-center gap-1 normal-case tracking-normal text-white/20">
                <Loader2 className="h-3 w-3 animate-spin" />
                loading explanations...
              </span>
            )}
          </p>
          {results.map((result) => (
            <AnimeResultCard
              key={result.anime.id}
              result={result}
              explanationLoading={!explanationsLoaded.has(result.anime.id)}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && searched && results.length === 0 && !error && (
        <div className="py-20 text-center text-sm text-white/30">
          No results found. Try a different description.
        </div>
      )}
    </div>
  );
}
