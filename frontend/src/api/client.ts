import type {
  BatchWriteResult,
  MediaUploadResponse,
  ObservationCreateRequest,
  ObservationDetail,
  ObservationListQuery,
  ObservationListResponse,
  ObservationUpdateRequest,
  ParseRequest,
  ParseResult,
  SpeciesSearchResponse,
  UUID,
} from './types.ts'

interface ErrorPayload {
  detail?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `请求失败（${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const payload = (await response.json()) as ErrorPayload
      detail = payload.detail ?? detail
    } catch {
      // Keep the HTTP status text when the server did not return JSON.
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

function jsonBody(value: unknown): Pick<RequestInit, 'body'> {
  return { body: JSON.stringify(value) }
}

function observationPath(observationId: UUID): string {
  return `/api/observations/${encodeURIComponent(observationId)}`
}

export const apiClient = {
  uploadMedia(photo: File): Promise<MediaUploadResponse> {
    const body = new FormData()
    body.set('photo', photo)
    return request('/api/media', { method: 'POST', body })
  },

  parse(input: ParseRequest): Promise<ParseResult> {
    return request('/api/parse', { method: 'POST', ...jsonBody(input) })
  },

  createObservations(input: ObservationCreateRequest): Promise<BatchWriteResult> {
    return request('/api/observations', {
      method: 'POST',
      ...jsonBody(input),
    })
  },

  listObservations(query: ObservationListQuery = {}): Promise<ObservationListResponse> {
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== '') {
        params.set(key, String(value))
      }
    })
    const suffix = params.size ? `?${params.toString()}` : ''
    return request(`/api/observations${suffix}`)
  },

  getObservation(observationId: UUID): Promise<ObservationDetail> {
    return request(observationPath(observationId))
  },

  updateObservation(
    observationId: UUID,
    input: ObservationUpdateRequest,
  ): Promise<ObservationDetail> {
    return request(observationPath(observationId), {
      method: 'PATCH',
      ...jsonBody(input),
    })
  },

  deleteObservation(observationId: UUID): Promise<void> {
    return request(observationPath(observationId), { method: 'DELETE' })
  },

  searchSpecies(query: string, limit = 20): Promise<SpeciesSearchResponse> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    return request(`/api/species?${params.toString()}`)
  },
}
