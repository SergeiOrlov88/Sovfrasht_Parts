// Дев-стаб API. Только для локального просмотра вёрстки: на демо-сервере
// vision-модель недоступна (ADR-06, гео-блокировка LLM-API), и состояния
// «в каталоге / нет в каталоге / низкая достоверность» вживую не воспроизвести.
//
// Контракты не меняет: отдаёт ровно те же поля, что схемы бэкенда
// (app/schemas/scan.py, purchase.py, moderation.py). Включается только в
// dev-режиме и только явным флагом:
//
//     npm run dev -- --mode development       # обычный режим, ходит в API
//     VITE_MOCK=1 npm run dev                 # вёрстка на стабе
//
// Модуль подключается только динамическим import() из api.js под флагом
// import.meta.env.DEV — в прод-сборке ветка сворачивается и этот файл в
// бандл не попадает вовсе (проверяется grep-ом по dist).

/** Какое состояние отчёта показывать: catalog | missing | low.
 *  Ключ тот же, что пишет дев-переключатель в App.jsx. */
const mockState = { get: () => localStorage.getItem('sp_mock_state') || 'catalog' }

const svg = (body) =>
  'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 240">${body}</svg>`)

const PHOTO_PLATE = svg(`
  <rect width="360" height="240" fill="#1a334c"/>
  <rect x="38" y="48" width="284" height="144" rx="8" fill="#c5d0d8"/>
  <rect x="58" y="68" width="244" height="104" fill="#1c2430"/>
  <text x="70" y="94" fill="#d7e6f2" font-size="11" font-family="monospace">ALFA LAVAL</text>
  <text x="70" y="118" fill="#7fe3cc" font-size="16" font-family="monospace">MAPX 207 TGT-24</text>
  <text x="70" y="140" fill="#b8c9d8" font-size="11" font-family="monospace">S/N 412890 · 2014</text>`)

const PHOTO_PART = svg(`
  <rect width="360" height="240" fill="#163047"/>
  <ellipse cx="180" cy="130" rx="96" ry="58" fill="#2a4d68"/>
  <rect x="156" y="40" width="48" height="140" rx="16" fill="#3d6b86"/>
  <circle cx="180" cy="130" r="34" fill="#1b3346" stroke="#2fc4a3" stroke-width="4"/>`)

const PHOTO_PLACE = svg(`
  <rect width="360" height="240" fill="#12283a"/>
  <path d="M20 170h320" stroke="#38b6ff" stroke-width="12"/>
  <path d="M70 170V80h64v90" stroke="#8aa6c2" stroke-width="16" fill="none"/>
  <circle cx="250" cy="120" r="38" fill="#18324a" stroke="#f0a341" stroke-width="6"/>`)

const VESSEL_ID = '2b0e6f2c-6b4d-4f7a-9f6f-0b6d0f0a1c11'
const SCAN_ID = '7a51d5d0-1f2b-4b3a-8a0c-9d1e2f3a4b5c'
const PART_ID = 'c3a1e5b7-4d2f-4c8a-9e1b-2f3a4b5c6d7e'
const REC_ID = 'ee11f0a2-3b4c-4d5e-8f90-a1b2c3d4e5f6'

const PART = {
  id: PART_ID,
  name: 'Сепаратор топливный Alfa Laval MAPX 207',
  maker: 'Alfa Laval',
  category: 'Топливная система',
  impa_code: '351102',
  issa_code: '75.201.11',
  oem_number: 'MAPX207TGT24',
  equipment: 'Сепараторная установка ГД',
  specs: { 'Производительность': '2600 л/ч', 'Питание': '440 В · 50 Гц' },
}

const IDENT = {
  title: 'Alfa Laval MAPX 207',
  part_type: 'Сепаратор / пурификатор топлива',
  maker: 'Alfa Laval',
  model: 'MAPX 207 TGT-24',
  function: 'Очистка HFO от воды и механических примесей перед топливной системой ГД',
  markings: 'MAPX207TGT24 · S/N 412890 · 2014 · 50Hz',
  confidence: 91,
  notes: 'Серийный номер частично бликует; год выпуска прочитан с уверенностью 74%.',
}

const PHOTOS = [
  { id: 'p1', kind: 'nameplate', url: PHOTO_PLATE, width: 360, height: 240 },
  { id: 'p2', kind: 'overview', url: PHOTO_PART, width: 360, height: 240 },
  { id: 'p3', kind: 'context', url: PHOTO_PLACE, width: 360, height: 240 },
]

const CANDIDATES = [
  { part: { ...PART, id: PART_ID }, relevance: 0.91 },
  {
    part: {
      id: 'd4b2f6c8-5e3a-4f9b-8c1d-3e4f5a6b7c8d',
      name: 'Сепаратор Alfa Laval MAB 103',
      maker: 'Alfa Laval', oem_number: 'MAB103B14',
    },
    relevance: 0.34,
  },
]

const OFFERS = {
  part: PART,
  offers: [
    {
      supplier: { name: 'Морские комплектации', type: 'supplier', region: 'Санкт-Петербург', url: null },
      price: '412 000 ₽', lead_time: '2 дня', stock_status: 'in',
      deep_link: 'https://example.org/offer/1', source: 'curated',
    },
    {
      supplier: { name: 'Alfa Laval Marine', type: 'oem', region: 'Швеция', url: null },
      price: '5 400 EUR', lead_time: '21 день', stock_status: 'low',
      deep_link: null, source: 'curated',
    },
    {
      supplier: { name: 'Логистика Севера', type: 'marketplace', region: 'Мурманск', url: null },
      price: null, lead_time: '14 дней', stock_status: 'out',
      deep_link: 'https://example.org/offer/3', source: 'curated',
    },
  ],
  alternatives: [
    {
      part: {
        id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        name: 'Сепаратор Westfalia OSD 6-91-067',
        maker: 'GEA Westfalia', oem_number: 'OSD691067',
      },
      compatibility: 'partial',
      offers: [{
        supplier: { name: 'GEA Сервис', type: 'supplier', region: 'Москва', url: null },
        price: '389 000 ₽', lead_time: '9 дней', stock_status: 'in',
        deep_link: null, source: 'curated',
      }],
    },
  ],
  message: null,
}

const REPAIR = {
  part: PART,
  verdict: 'repair',
  rationale: 'Сепараторы этого класса ремонтопригодны: барабан и подшипниковый узел ' +
    'восстанавливаются в сервисе, замена оправдана только при трещине корпуса.',
  rule_subtype: 'separator',
  estimate: {
    replace_price: '412 000 ₽',
    replace_lead_time: '2 дня',
    replace_supplier: 'Морские комплектации',
    repair_cost_estimate: '≈ 148 000 ₽',
    repair_share: '36%',
    repair_time: '7 дней',
  },
  reman_offers: [{
    supplier: { name: 'Балтик Реман', type: 'reman', region: 'Калининград', url: null },
    price: '243 000 ₽', lead_time: '12 дней', stock_status: 'in',
    deep_link: 'https://example.org/reman/1', source: 'curated',
  }],
  disclaimer: 'Оценка предварительная и построена на автоматическом распознавании. ' +
    'Фактический объём работ, стоимость запчастей и трудозатраты могут отличаться. ' +
    'Решение принимайте после осмотра сертифицированным инженером.',
}

/** Отчёт под выбранное состояние. Поля — как в ScanReport. */
function report() {
  const base = {
    scan_id: SCAN_ID,
    vessel_id: VESSEL_ID,
    status: 'done',
    created_at: '2026-08-18T09:12:00Z',
    recognition: {
      id: REC_ID, part_id: PART_ID, confidence: 91,
      ocr_text: 'ALFA LAVAL MAPX 207 TGT-24 S/N 412890 2014 50Hz Made in Sweden',
      maker_detected: 'Alfa Laval', oem_detected: 'MAPX207TGT24',
      model_version: 'mock-1', status: 'matched', catalog_status: 'matched',
    },
    identification: IDENT,
    part: PART,
    candidates: CANDIDATES,
    alternatives: [{
      part: {
        id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        name: 'Сепаратор Westfalia OSD 6-91-067',
        maker: 'GEA Westfalia', oem_number: 'OSD691067',
      },
      compatibility: 'partial',
      note: 'Требуется переходная плита крепления.',
    }],
    photos: PHOTOS,
    needs_expert: false,
    confidence: 91,
    confidence_level: 'high',
    warning: null,
    can_confirm: true,
    can_request_expert: true,
    feedback: null,
    message: null,
  }

  if (mockState.get() === 'missing') {
    return {
      ...base,
      part: null,
      candidates: [],
      alternatives: [],
      recognition: { ...base.recognition, part_id: null, status: 'not_found', catalog_status: 'not_found' },
      confidence: 88,
      confidence_level: 'high',
    }
  }

  if (mockState.get() === 'low') {
    return {
      ...base,
      part: null,
      candidates: CANDIDATES.slice(1),
      alternatives: [],
      identification: {
        ...IDENT,
        title: 'Сепаратор, производитель не читается',
        maker: null,
        model: null,
        markings: 'M?PX 2?7 · S/N 4128??',
        confidence: 41,
        notes: 'Кадр засвечен, часть маркировки не читается.',
      },
      recognition: { ...base.recognition, confidence: 41, part_id: null, status: 'low_confidence' },
      needs_expert: true,
      confidence: 41,
      confidence_level: 'low',
      warning: 'Кадр засвечен, часть маркировки не читается. Отправьте скан эксперту, не заказывайте деталь по догадке.',
      can_confirm: false,
      can_request_expert: true,
    }
  }

  return base
}

const TASKS = {
  items: [
    {
      id: 't1', status: 'pending', resolution: null, expert_id: null,
      created_at: '2026-08-18T11:22:00Z', claimed_at: null, resolved_at: null,
      sla: { wait_seconds: 940, work_seconds: null, total_seconds: null },
      scan_id: SCAN_ID, vessel_name: 'т/х «Капитан Сорокин»', author_name: 'Пахомов И.',
      recognition: {
        id: REC_ID, part_id: null, confidence: 54,
        ocr_text: 'ALFA LAVAL MAPX 2?7 S/N 4128?0',
        maker_detected: 'Alfa Laval', oem_detected: 'MAPX207',
        model_version: 'mock-1', status: 'low_confidence', catalog_status: 'candidates',
      },
      part: null,
      candidates: CANDIDATES,
      photos: PHOTOS,
    },
    {
      id: 't2', status: 'pending', resolution: null, expert_id: null,
      created_at: '2026-08-18T09:10:00Z', claimed_at: null, resolved_at: null,
      sla: { wait_seconds: 8400, work_seconds: null, total_seconds: null },
      scan_id: 'b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e',
      vessel_name: 'т/х «Мыс Дежнёва»', author_name: 'Ковалёв С.',
      recognition: {
        id: 'rec-2', part_id: PART_ID, confidence: 61, ocr_text: 'DN50 PN16 GOST 5762',
        maker_detected: null, oem_detected: 'DN50PN16',
        model_version: 'mock-1', status: 'low_confidence', catalog_status: 'matched',
      },
      part: { id: PART_ID, name: 'Клапан запорный Ду 50', maker: 'Броен', oem_number: 'BRN-DN50' },
      candidates: [],
      photos: [PHOTOS[1]],
    },
  ],
  total: 2, page: 1, page_size: 20,
}

// Счётчик опросов статуса: см. ветку /scans/ в devMock()
let scanPolls = 0

// Роль тоже переключается из дев-панели: очередь эксперта иначе не открыть
const USER = () => ({
  id: 'u1', login: 'mechanic', full_name: 'Пахомов Игорь',
  role: localStorage.getItem('sp_mock_role') || 'mechanic',
  vessels: [{ id: VESSEL_ID, name: 'т/х «Капитан Сорокин»' }],
})

/** Роутер стаба: путь → ответ. Пути совпадают с реальными (docs/08). */
export async function devMock(path, { method = 'GET' } = {}) {
  await new Promise(r => setTimeout(r, 260))     // видимая задержка: скелетоны показываются

  if (path === '/auth/me') return USER()
  if (path === '/auth/token') return { access_token: 'mock', refresh_token: 'mock' }
  if (path === '/notifications') return { items: [], total: 0, unread: 0, page: 1, page_size: 20 }
  if (path.startsWith('/moderation/tasks?status=pending')) return TASKS
  if (path.startsWith('/moderation/tasks')) return { items: [], total: 0, page: 1, page_size: 20 }
  if (path.endsWith('/report')) return report()
  if (path.endsWith('/offers')) return OFFERS
  if (path.endsWith('/repair')) return REPAIR
  if (path.endsWith('/feedback') && method === 'POST') {
    return {
      scan_id: SCAN_ID, recognition_status: 'rejected', verdict: 'reject',
      part: null, training_sample_created: false, moderation_task_created: true,
      message: 'Скан отправлен эксперту, ответ придёт уведомлением.',
    }
  }
  // Поллинг статуса: первые опросы держим в работе, чтобы было видно
  // состояние «идёт распознавание» с прогрессом и скелетоном
  if (path.startsWith('/scans/')) {
    scanPolls += 1
    const status = scanPolls < 4 ? (scanPolls < 2 ? 'queued' : 'processing') : 'done'
    return { id: SCAN_ID, status, photos: PHOTOS }
  }

  throw new Error(`Стаб не знает путь ${path}`)
}

/** POST /scans (multipart) — отдельно: тело FormData, а не JSON. */
export async function devMockScan() {
  await new Promise(r => setTimeout(r, 400))
  scanPolls = 0
  return { scan_id: SCAN_ID, status: 'queued', idempotent_reuse: false }
}
