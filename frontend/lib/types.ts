export interface NarrativeSchema {
  protagonist_archetype: string | null;
  power_origin: string | null;
  growth_type: string | null;
  protagonist_motivation: string | null;
  conflict_type: string | null;
  pacing: string | null;
  tone: string | null;
  themes: string[] | null;
  relationship_types: string[] | null;
  team_dynamics: string | null;
  stakes_level: string | null;
}

export interface AnimeCard {
  id: number;
  title: string;
  title_english: string | null;
  cover_image: string | null;
  average_score: number | null;
  episodes: number | null;
  season_year: number | null;
  genres: string[] | null;
  narrative: NarrativeSchema | null;
}

export interface RecommendationCard {
  anime: AnimeCard;
  similarity_score: number;
  explanation: string;
  match_reasons: string[];
}
