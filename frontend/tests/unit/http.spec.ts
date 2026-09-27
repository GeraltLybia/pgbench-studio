import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, http, onForbidden, onUnauthorized } from '@/api/http'
import { jsonResponse, mockFetch } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
  onUnauthorized(() => {})
  onForbidden(() => {})
})

describe('http', () => {
  it('sends JSON and parses the response', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { ok: 1 }))
    await expect(http.post('/api/x', { a: 1 })).resolves.toEqual({ ok: 1 })
    const [path, init] = fetchMock.mock.calls[0]!
    expect(path).toBe('/api/x')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe('{"a":1}')
    expect(init?.credentials).toBe('same-origin')
  })

  it('returns undefined for 204', async () => {
    mockFetch(new Response(null, { status: 204 }))
    await expect(http.post('/api/auth/logout')).resolves.toBeUndefined()
  })

  it('turns backend errors into ApiError', async () => {
    mockFetch(jsonResponse(409, { detail: { code: 'last_admin', message: 'Нельзя' } }))
    const error = await http.patch('/api/users/1', {}).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).code).toBe('last_admin')
    expect((error as ApiError).message).toBe('Нельзя')
  })

  it('handles validation errors and non-JSON bodies', async () => {
    mockFetch(
      jsonResponse(422, { detail: [{ loc: ['body'], msg: 'bad' }] }),
      new Response('<html>', { status: 502 }),
    )
    await expect(http.post('/api/x', {})).rejects.toMatchObject({ code: 'validation_error' })
    await expect(http.get('/api/x')).rejects.toMatchObject({
      code: 'http_502',
      message: 'Ошибка сервера (502)',
    })
  })

  it('reports network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    await expect(http.get('/api/x')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })

  it('calls the 401 and 403 handlers unless silent', async () => {
    const unauthorized = vi.fn()
    const forbidden = vi.fn()
    onUnauthorized(unauthorized)
    onForbidden(forbidden)
    const denied = { detail: { code: 'forbidden', message: 'нет' } }
    mockFetch(
      jsonResponse(401, { detail: { code: 'not_authenticated', message: 'вход' } }),
      jsonResponse(403, denied),
      jsonResponse(401, { detail: { code: 'not_authenticated', message: 'вход' } }),
    )
    await http.get('/api/a').catch(() => {})
    await http.get('/api/b').catch(() => {})
    await http.get('/api/c', { silent: true }).catch(() => {})
    expect(unauthorized).toHaveBeenCalledOnce()
    expect(forbidden).toHaveBeenCalledOnce()
    expect((forbidden.mock.calls[0]![0] as ApiError).code).toBe('forbidden')
  })
})
