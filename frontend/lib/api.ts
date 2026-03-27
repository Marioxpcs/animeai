import axios from "axios";
import type { AnimeCard, RecommendationCard, StreamResultAnime, StreamExplanation } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 120_000,
});

export async function searchAnime(
  query: string,
  limit = 8
): Promise<RecommendationCard[]> {
  const { data } = await api.get<RecommendationCard[]>("/api/anime/search", {
    params: { q: query, limit },
  });
  return data;
}

export function streamSearch(
  query: string,
  limit: number,
  callbacks: {
    onResults: (anime: StreamResultAnime[]) => void;
    onExplanation: (data: StreamExplanation) => void;
    onDone: () => void;
    onError: (err: Error) => void;
  }
): AbortController {
  const controller = new AbortController();
  const params = new URLSearchParams({ q: query, limit: String(limit) });

  fetch(`${API_BASE}/api/anime/search/stream?${params}`, {
    signal: controller.signal,
    headers: { Accept: "text/event-stream" },
  })
    .then(async (res) => {
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // Parse SSE frames
        const parts = buf.split("\n\n");
        buf = parts.pop()!; // keep incomplete frame in buffer

        for (const part of parts) {
          let eventType = "message";
          let data = "";
          for (const line of part.split("\n")) {
            if (line.startsWith("event: ")) eventType = line.slice(7);
            else if (line.startsWith("data: ")) data = line.slice(6);
          }
          if (!data) continue;

          try {
            const parsed = JSON.parse(data);
            if (eventType === "results") callbacks.onResults(parsed);
            else if (eventType === "explanation") callbacks.onExplanation(parsed);
            else if (eventType === "done") callbacks.onDone();
            else if (eventType === "error") callbacks.onError(new Error(parsed.message));
          } catch {
            // skip malformed frames
          }
        }
      }
      // If stream ended without a done event
      callbacks.onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") callbacks.onError(err);
    });

  return controller;
}

export async function getAnime(id: number): Promise<AnimeCard> {
  const { data } = await api.get<AnimeCard>(`/api/anime/${id}`);
  return data;
}

export async function getSimilarAnime(
  id: number,
  limit = 6
): Promise<RecommendationCard[]> {
  const { data } = await api.get<RecommendationCard[]>(
    `/api/anime/${id}/similar`,
    { params: { limit } }
  );
  return data;
}

export async function submitRating(
  userId: string,
  animeId: number,
  score: number
): Promise<void> {
  await api.post("/api/ratings", {
    user_id: userId,
    anime_id: animeId,
    score,
  });
}
