"use client";

import { useState } from "react";
import { Star } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { submitRating } from "@/lib/api";

export function AnimeRating({ animeId }: { animeId: number }) {
  const { user, openAuthModal } = useAuth();
  const [hoveredStar, setHoveredStar] = useState(0);
  const [selectedScore, setSelectedScore] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleRate = async (score: number) => {
    if (!user) {
      openAuthModal();
      return;
    }

    setSelectedScore(score);
    setSubmitting(true);
    try {
      await submitRating(user.id, animeId, score * 20); // 1-5 stars -> 20-100 scale
      setSubmitted(true);
    } catch {
      // Silently handle — user sees star stays selected
    } finally {
      setSubmitting(false);
    }
  };

  const activeStar = hoveredStar || selectedScore;

  return (
    <div className="flex items-center gap-3">
      <div className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            disabled={submitting}
            onMouseEnter={() => setHoveredStar(star)}
            onMouseLeave={() => setHoveredStar(0)}
            onClick={() => handleRate(star)}
            className="rounded p-0.5 transition-colors hover:bg-white/[0.04] disabled:opacity-50"
          >
            <Star
              className={`h-5 w-5 transition-colors ${
                star <= activeStar
                  ? "fill-amber-400 text-amber-400"
                  : "text-white/15"
              }`}
            />
          </button>
        ))}
      </div>
      {submitted && (
        <span className="text-xs text-white/30">Saved</span>
      )}
      {!user && (
        <button
          onClick={openAuthModal}
          className="text-xs text-indigo-400/60 transition-colors hover:text-indigo-400/80"
        >
          Sign in to rate
        </button>
      )}
    </div>
  );
}
