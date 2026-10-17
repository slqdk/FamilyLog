/** FamilyMap data shapes (2.43.0) - shared by the family's page (/fm/) and
    the admin section. Mirrors backend/app/familymap.py. */

export type FmFieldKind = 'rating' | 'bool' | 'choice' | 'text';

export interface FmField {
  key: string;
  label: string;
  kind: FmFieldKind;
  options?: string[];
  /** Example text for a text field ("fx 3-10 år"). (2.49.3) */
  placeholder?: string;
  /** A score the server computes as the average of these fields (2.50.0). */
  computed?: string[];
  /** This field is one of the parts of that computed field. */
  part_of?: string;
}

export interface FmCategory {
  label: string;
  icon: string;
  fields: FmField[];
}

export type FmCategories = Record<string, FmCategory>;

export type FmFieldValue = number | boolean | string;

export interface FmPhoto {
  id: number;
  width: number | null;
  height: number | null;
  takenAt: string | null;
  description: string | null;
  /** Vision description (2.44.0): null/pending, queued, done, failed, nomodel. */
  describeState: string | null;
  describeError: string | null;
}

export interface FmReview {
  id: number;
  placeId: number;
  userId: number | null;
  author: string;
  visitedOn: string | null;
  who: string;
  overall: number;
  fields: Record<string, FmFieldValue>;
  text: string;
  again: boolean | null;
  createdAt: string;
  updatedAt: string;
  photos: FmPhoto[];
  placeName?: string;
  placeCategory?: string;
}

export interface FmPlace {
  id: number;
  name: string;
  category: string;
  address: string;
  lat: number | null;
  lng: number | null;
  website: string;
  notes: string;
  source: 'family' | 'osm' | 'google' | 'web';
  sourceId: string | null;
  webRating: number | null;
  webRatingCount: number | null;
  webRatingAt: string | null;
  createdBy: number | null;
  createdAt: string;
  updatedAt: string;
  reviewCount: number;
  familyScore: number | null;
  coverPhotoId: number | null;
  lastVisit: string | null;
  /** An imported place the admin corrected; later imports leave it be. */
  locked: boolean;
  /** Kept OSM tags (cuisine, opening_hours, min_age...), for the model. */
  extra: Record<string, string>;
  /** Only in a near-me list. */
  distanceKm?: number;
  /** The newest review text, for the card's line (2.45.0). */
  latestText: string | null;
  /** On the signed-in person's own wishlist. */
  wished: boolean;
  reviews?: FmReview[];
}

export interface FmUser {
  id: number;
  username: string;
  role: string;
  gender?: string;
  createdAt?: string;
  online?: boolean;
}

export interface FmStats {
  places: number;
  reviewedPlaces: number;
  reviews: number;
  photos: number;
  photoStates: Record<'pending' | 'queued' | 'done' | 'failed' | 'nomodel', number>;
  sources: Record<string, number>;
}

export interface FmSettings {
  /** What the family page calls itself (2.44.1). */
  appName: string;
  chatModel: string;
  visionModel: string;
  overpassUrl: string;
}

export interface FmImportCategory {
  state: 'waiting' | 'fetching' | 'retrying' | 'saving' | 'done' | 'failed' | 'stopped';
  found: number | null;
  added?: number;
  updated?: number;
  unchanged?: number;
  locked?: number;
  seconds?: number;
  error?: string;
}

export interface FmImportState {
  running: boolean;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  categories: Record<string, FmImportCategory>;
  region: string;
  /** Category -> the OSM selectors that feed it. */
  sources: Record<string, string[]>;
}

/** What the review form sends. */
export interface FmReviewBody {
  overall: number;
  visitedOn: string;
  who: string;
  fields: Record<string, FmFieldValue>;
  text: string;
  again: boolean | null;
}

/** A photo in "Mine billeder": where it was taken. */
export interface FmMyPhoto extends FmPhoto {
  placeId: number;
  placeName: string;
  visitedOn: string | null;
}

export const photoUrl = (id: number, thumb = false) =>
  `/api/fm/photos/${id}${thumb ? '?thumb=1' : ''}`;

/** Spørg Alf's state for this person (2.46.0) - polled while it works. */
export interface FmAsk {
  state: 'none' | 'queued' | 'working' | 'done' | 'failed';
  question?: string;
  step?: string;
  /** Which animation: queue, understand, search, web, think, write (2.48.0). */
  phase?: string;
  ahead?: number;
  text?: string;
  error?: string | null;
  where?: string | null;
  /** What was searched for, in words: "Legeplads med \"gynger\", 4 år". (2.49.2) */
  searched?: string | null;
  radiusKm?: number | null;
  webAdded?: number;
  places?: FmPlace[];
}
