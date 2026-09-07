export type UUID = string
export type ISODate = string
export type ISODateTime = string

export interface MediaUploadResponse {
  media_id: UUID
  hash: string
  url: string
}

export interface DraftObservation {
  client_draft_id: string
  place: string | null
  obs_date: ISODate | null
  time_of_day: string | null
  count: number | null
  behavior: string | null
  raw_note: string
  species_label: string | null
  species_id: UUID | null
  confidence: number | null
  source: string
  flags: string[]
  photo_ids: UUID[]
  needs_confirmation: boolean
}

export interface PhotoDraft {
  photo_id: UUID
  client_draft_id: string
}

export interface ParseRequest {
  text: string
  media_ids: UUID[]
}

export interface ParseResult {
  draft_observations: DraftObservation[]
  unmatched_photos: PhotoDraft[]
  warnings: string[]
  job_status: 'completed'
}

export interface ObservationCreateRequest {
  text: string
  media_ids: UUID[]
  observations: DraftObservation[]
  confirmed: boolean
}

export interface CreatedObservation {
  client_draft_id: string
  observation_id: UUID
}

export interface FailedObservation {
  client_draft_id: string
  reason: string
}

export interface BatchWriteResult {
  session_id: UUID
  created: CreatedObservation[]
  failed: FailedObservation[]
}

export interface ObservationSummary {
  observation_id: UUID
  timestamp: ISODateTime
  species_label: string | null
  species_id: UUID | null
  count: number | null
  place: string | null
  obs_date: ISODate | null
  time_of_day: string | null
  photo_count: number
  thumbnail_url: string | null
}

export interface ObservationPhoto {
  media_id: UUID
  url: string
  original_filename: string
  mime_type: string
  size_bytes: number
}

export interface ObservationSessionInfo {
  session_id: UUID
  created_at: ISODateTime
  raw_text: string
  status: string
}

export interface ObservationDetail extends ObservationSummary {
  behavior: string | null
  raw_note: string
  confidence: number | null
  source: string
  flags: string[]
  photos: ObservationPhoto[]
  session: ObservationSessionInfo | null
}

export interface ObservationListResponse {
  items: ObservationSummary[]
}

export interface ObservationListQuery {
  limit?: number
  place?: string
  species?: string
  date_from?: ISODate
  date_to?: ISODate
}

export interface ObservationUpdateRequest {
  place?: string | null
  obs_date?: ISODate | null
  time_of_day?: string | null
  species_label?: string | null
  species_id?: UUID | null
  count?: number | null
  behavior?: string | null
  raw_note?: string
  confidence?: number | null
  flags?: string[]
}

export interface SpeciesSearchItem {
  species_id: UUID
  canonical_chinese_name: string
  scientific_name: string | null
  aliases: string[]
}

export interface SpeciesSearchResponse {
  items: SpeciesSearchItem[]
}
