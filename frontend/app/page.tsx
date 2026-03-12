"use client";

import { useState } from "react";
import { Search, Loader2, Sparkles } from "lucide-react";
import { searchAnime } from "@/lib/api";
import { AnimeResultCard } from "@/components/anime-card";
import type { RecommendationCard } from "@/lib/types";

export default function Home() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RecommendationCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || loading) return;

    setLoading(true);
    setError(null);
    setSearched(true);

    try {
      const data = await searchAnime(query.trim(), 20);
      setResults(data);
    } catch {
      setError("Failed to fetch recommendations. Is the backend running?");
      setResults([]);
    } finally {
      setLoading(false);
    }
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
              className="w-full rounded-xl border border-white/[0.08] bg-white/[0.03] py-3.5 pl-11 pr-4 text-[15px] text-white/90 placeholder-white/25 outline-none transition-all focus:border-white/[0.15] focus:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.08]"
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
                className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-xs text-white/35 transition-all hover:border-white/[0.1] hover:bg-white/[0.04] hover:text-white/50"
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

      {/* Loading state */}
      {loading && (
        <div className="flex flex-col items-center gap-3 py-20">
          <Loader2 className="h-6 w-6 animate-spin text-white/20" />
          <p className="text-sm text-white/30">
            Analyzing your request and finding matches...
          </p>
        </div>
      )}

      {/* Results */}
      {!loading && results.length > 0 && (
        <div className="space-y-3 pb-16">
          <p className="mb-4 text-xs font-medium uppercase tracking-wider text-white/25">
            {results.length} results
          </p>
          {results.map((result) => (
            <AnimeResultCard key={result.anime.id} result={result} />
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
