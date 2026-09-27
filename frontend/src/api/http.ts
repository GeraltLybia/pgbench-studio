/** fetch wrapper: JSON bodies, uniform errors, 401/403 hooks. */

export interface ErrorDetail {
  code: string
  message: string
  [key: string]: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: ErrorDetail

  constructor(status: number, detail: ErrorDetail) {
    super(detail.message)
    this.name = 'ApiError'
    this.status = status
    this.code = detail.code
    this.detail = detail
  }
}

type Handler = (error: ApiError) => void

const handlers: { unauthorized?: Handler; forbidden?: Handler } = {}

/** 401 — session is gone: the app sends the user to /login. */
export function onUnauthorized(handler: Handler): void {
  handlers.unauthorized = handler
}

/** 403 — role or a pending password change: the app reacts globally, callers still get the error. */
export function onForbidden(handler: Handler): void {
  handlers.forbidden = handler
}

const GENERIC_MESSAGES: Record<number, string> = {
  401: 'Требуется вход',
  403: 'Недостаточно прав для этого действия',
  404: 'Не найдено',
  422: 'Проверьте введённые данные',
  429: 'Слишком много запросов',
}

function toDetail(status: number, body: unknown): ErrorDetail {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && 'code' in detail) {
    return detail as ErrorDetail
  }
  if (Array.isArray(detail)) {
    // FastAPI request validation errors
    return { code: 'validation_error', message: GENERIC_MESSAGES[422]!, errors: detail }
  }
  return {
    code: `http_${status}`,
    message: GENERIC_MESSAGES[status] ?? `Ошибка сервера (${status})`,
  }
}

export interface RequestOptions {
  /** Skip global 401/403 handlers (e.g. the login form handles its own errors). */
  silent?: boolean
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, { code: 'network_error', message: 'Сервер недоступен' })
  }

  if (response.status === 204) return undefined as T
  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (response.ok) return data as T

  const error = new ApiError(response.status, toDetail(response.status, data))
  if (!options.silent) {
    if (response.status === 401) handlers.unauthorized?.(error)
    if (response.status === 403) handlers.forbidden?.(error)
  }
  throw error
}

export const http = {
  get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PATCH', path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PUT', path, body, options),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>('DELETE', path, undefined, options),
}
