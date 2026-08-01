// Тонкий клиент API. Доменной логики здесь нет — она на бэкенде (NFR-MAINT-01).
const BASE = '/api/v1'

const ACCESS_KEY = 'sp_access_token'
const REFRESH_KEY = 'sp_refresh_token'

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY)
  },
  save(access, refresh) {
    localStorage.setItem(ACCESS_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

/** Бэкенд отдаёт ошибки в едином формате docs/08 §1 — достаём из него сообщение. */
async function toError(response) {
  let message = `Ошибка ${response.status}`
  try {
    const body = await response.json()
    if (body?.error?.message) message = body.error.message
  } catch {
    /* тело не JSON — оставляем общее сообщение */
  }
  const err = new Error(message)
  err.status = response.status
  return err
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (auth && tokens.access) headers['Authorization'] = `Bearer ${tokens.access}`

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await toError(response)
  return response.status === 204 ? null : response.json()
}

export const login = (loginName, password) =>
  request('/auth/token', { method: 'POST', body: { login: loginName, password }, auth: false })

export const me = () => request('/auth/me')

export const refreshAccess = () =>
  request('/auth/refresh', { method: 'POST', body: { refresh_token: tokens.refresh }, auth: false })

export const getReport = (scanId) => request(`/scans/${scanId}/report`)

export const sendFeedback = (scanId, { verdict, correct_part_id, comment }) =>
  request(`/scans/${scanId}/feedback`, {
    method: 'POST',
    body: { verdict, correct_part_id: correct_part_id ?? null, comment: comment ?? null },
  })

export const getOffers = (partId) => request(`/parts/${partId}/offers`)

export const createPartRequest = (payload) =>
  request('/part-requests', { method: 'POST', body: payload })

export const listPartRequests = (params = '') => request(`/part-requests${params}`)

export const getRepair = (partId) => request(`/parts/${partId}/repair`)
