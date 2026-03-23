import axios from "axios";
import type { AnimeCard, RecommendationCard } from "./types";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
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
