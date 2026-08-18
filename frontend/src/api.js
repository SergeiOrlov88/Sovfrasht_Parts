// Тонкий клиент API. Доменной логики здесь нет — она на бэкенде (NFR-MAINT-01).
//
// VITE_API_BASE задаётся на сборке. Пусто (по умолчанию) — запросы идут
// относительными путями: в разработке их проксирует Vite, за общим nginx это
// тоже верно. Для сборки, которая раздаётся отдельно от API (витрина на голом
// IP), сюда подставляется абсолютный адрес бэкенда.
//
// Отдельно: дев-стаб (devMock.js). Он подменяет транспорт, а не контракт —
// пути и поля ответов те же. Нужен, чтобы смотреть вёрстку состояний, которые
// на демо-сервере не воспроизводятся: vision-модель там отключена
// (ADR-06, гео-блокировка LLM-API). Включается флагом VITE_MOCK=1 в dev.
//
// Подключается динамическим import(): в прод-сборке import.meta.env.DEV — это
// литерал false, вся ветка сворачивается и devMock.js в бандл не попадает.
export const MOCK_ENABLED = import.meta.env.DEV && import.meta.env.VITE_MOCK === '1'

let mockModule = null
const mock = async () => (mockModule ||= await import('./devMock.js'))

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

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
  if (MOCK_ENABLED) return (await mock()).devMock(path, { method, body })

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

// ── Панель эксперта (F2) ─────────────────────────────────────────────────────
export const listTasks = (status = 'pending') =>
  request(`/moderation/tasks?status=${status}`)

export const claimTask = (taskId) =>
  request(`/moderation/tasks/${taskId}/claim`, { method: 'POST' })

export const resolveTask = (taskId, { resolution, correct_part_id }) =>
  request(`/moderation/tasks/${taskId}/resolve`, {
    method: 'POST',
    body: { resolution, correct_part_id: correct_part_id ?? null },
  })

// ── Уведомления ──────────────────────────────────────────────────────────────
export const listNotifications = () => request('/notifications')
export const readNotification = (id) => request(`/notifications/${id}/read`, { method: 'POST' })

// ── Съёмка и распознавание (A1) ──────────────────────────────────────────────
// FormData отправляем как есть: Content-Type с boundary браузер проставит сам,
// вручную его задавать нельзя — запрос развалится.
export const createScan = async (form) => {
  if (MOCK_ENABLED) return (await mock()).devMockScan()

  const headers = {}
  if (tokens.access) headers['Authorization'] = `Bearer ${tokens.access}`
  const response = await fetch(`${BASE}/scans`, { method: 'POST', headers, body: form })
  if (!response.ok) throw await toError(response)
  return response.json()
}

export const getScan = (scanId) => request(`/scans/${scanId}`)
