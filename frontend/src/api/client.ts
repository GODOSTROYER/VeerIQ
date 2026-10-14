import type { ApiErrorBody } from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }
  get isNetwork(): boolean {
    return this.status === 0
  }
}

export const API_BASE = '/api'

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      credentials: 'include',
      signal,
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network', 'Cannot reach the VeerIQ server. Check that the backend is running on port 8020.')
  }

  if (res.status === 204) return undefined as T

  const text = await res.text()
  let parsed: unknown = undefined
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = undefined
    }
  }

  if (!res.ok) {
    const err = (parsed as Partial<ApiErrorBody> | undefined)?.error
    // FastAPI default validation errors use {detail}; fall back gracefully.
    const detail = (parsed as { detail?: unknown } | undefined)?.detail
    const message =
      err?.message ?? (typeof detail === 'string' ? detail : undefined) ?? `Request failed (${res.status})`
    throw new ApiError(res.status, err?.code ?? `http_${res.status}`, message)
  }
  return parsed as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) => request<T>('POST', path, body ?? {}, signal),
}

/** Human-readable message for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Something went wrong.'
}
