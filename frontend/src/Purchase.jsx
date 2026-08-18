// Вкладка «Закупка» (C1/C2): предложения поставщиков и оформление заявки.
// Вёрстка по макету design_ref3.html: строка поставщика — логотип-инициалы,
// название с метками, цена моноширинным справа. Первый оффер выделен рамкой:
// бэкенд сортирует предложения по наличию, затем по цене, значит он и есть
// лучший. Цены демонстрационные — это помечено меткой «демо».
import { useEffect, useState } from 'react'
import { createPartRequest, getOffers } from './api'
import { BannerError, BannerOk, EmptyCamera, IconExternal } from './icons.jsx'

const STOCK = {
  in: { label: 'в наличии', cls: 'pill--ok' },
  low: { label: 'мало', cls: 'pill--warn' },
  out: { label: 'нет в наличии', cls: 'pill--danger' },
}

const SUPPLIER_TYPE = {
  marketplace: 'площадка',
  supplier: 'дистрибьютор',
  oem: 'производитель',
  reman: 'восстановление',
}

/** Инициалы поставщика для плитки-логотипа: до трёх первых букв слов. */
function initials(name) {
  return (name || '?')
    .split(/[\s·—-]+/)
    .filter(Boolean)
    .slice(0, 3)
    .map(w => w[0].toUpperCase())
    .join('')
}

export function SupplierRow({ offer, best }) {
  const stock = STOCK[offer.stock_status]
  return (
    <article className={`supplier-row${best ? ' is-best' : ''}`}>
      <div className="sup-logo">{initials(offer.supplier.name)}</div>
      <div>
        <div className="sup-name">{offer.supplier.name}</div>
        <div className="sup-meta">
          {stock && <span className={`pill ${stock.cls}`}>{stock.label}</span>}
          {offer.lead_time && <span className="pill">{offer.lead_time}</span>}
          {offer.supplier.region && <span className="pill">{offer.supplier.region}</span>}
        </div>
      </div>
      <div className="sup-price">
        <b className={offer.price ? undefined : 'is-na'}>{offer.price || 'по запросу'}</b>
        <span>
          {SUPPLIER_TYPE[offer.supplier.type] || offer.supplier.type}
          {offer.source !== 'api' ? ' · демо' : ''}
        </span>
      </div>
      {offer.deep_link && (
        <div className="sup-link">
          <a className="btn btn--ghost btn--block btn--sm" href={offer.deep_link}
            target="_blank" rel="noreferrer">
            <IconExternal width="16" height="16" /> Открыть у поставщика
          </a>
        </div>
      )}
    </article>
  )
}

export default function Purchase({ report, onRequested }) {
  const part = report.part
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [qty, setQty] = useState(1)
  const [priority, setPriority] = useState('normal')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState(null)

  useEffect(() => {
    if (!part) return
    getOffers(part.id).then(setData).catch(e => setError(e.message))
  }, [part?.id])

  if (!part) {
    return (
      <div className="empty-state">
        <div className="empty-ico"><EmptyCamera /></div>
        <h2>Закупать нечего</h2>
        <p>
          Позиции каталога для этой детали нет — коды и поставщиков подобрать
          не удалось. Уточните результат на вкладке «Отчёт».
        </p>
      </div>
    )
  }

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const result = await createPartRequest({
        part_id: part.id,
        vessel_id: report.vessel_id,
        quantity: Number(qty),
        priority,
        comment: comment || null,
        recognition_id: report.recognition?.id ?? null,
        // Ключ идемпотентности: повторное нажатие не создаст вторую заявку
        client_request_id: `${report.scan_id}:${part.id}`,
      })
      setCreated(result)
      onRequested?.(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const offers = data?.offers || []

  return (
    <div className="stack">
      {error && (
        <div className="banner banner--danger">
          <BannerError />
          <div>{error}</div>
        </div>
      )}

      <div className="codes">
        {part.impa_code && <div className="code-cell"><span>IMPA</span><b>{part.impa_code}</b></div>}
        {part.oem_number && <div className="code-cell"><span>OEM</span><b>{part.oem_number}</b></div>}
      </div>

      <div>
        <div className="section-label">
          <span>Поставщики</span>
          {offers.length > 0 && <span>{offers.length} предложения</span>}
        </div>
        <div className="stack">
          {!data && <div className="skeleton sk-block" />}
          {data?.message && <p className="tiny muted">{data.message}</p>}
          {offers.map((o, i) => <SupplierRow key={i} offer={o} best={i === 0} />)}
          {data && offers.length === 0 && !data.message && (
            <p className="tiny muted">Предложений нет.</p>
          )}
        </div>
      </div>

      {data?.alternatives?.map(alt => (
        <div className="panel" key={alt.part.id}>
          <div className="section-label" style={{ marginBottom: 8 }}>
            <span>Аналог</span>
            <span className="pill pill--warn">совместимость: {alt.compatibility}</span>
          </div>
          <h3 style={{ fontSize: 15, fontWeight: 700 }}>{alt.part.name}</h3>
          <p className="tiny muted" style={{ margin: '6px 0 10px' }}>
            {alt.part.maker || '—'} · <span className="mono">{alt.part.oem_number || 'без номера'}</span>
          </p>
          {alt.offers.length
            ? <div className="stack">{alt.offers.map((o, i) => <SupplierRow key={i} offer={o} />)}</div>
            : <p className="tiny muted">Предложений нет.</p>}
        </div>
      ))}

      <div className="panel">
        <div className="section-label"><span>Заявка на снабжение</span></div>
        {created ? (
          <div className="banner banner--ok">
            <BannerOk />
            <div>
              <b>Заявка создана</b>
              Статус «{created.status}».
              {created.idempotent_reuse && ' Такая заявка уже была — повторно не создавали.'}
            </div>
          </div>
        ) : (
          <div className="stack">
            <div className="field">
              <label htmlFor="qty">Количество</label>
              <input id="qty" type="number" min="1" value={qty}
                onChange={e => setQty(e.target.value)} />
            </div>

            <div className="field">
              <label htmlFor="prio">Приоритет</label>
              <select id="prio" value={priority} onChange={e => setPriority(e.target.value)}>
                <option value="low">низкий</option>
                <option value="normal">обычный</option>
                <option value="urgent">срочно</option>
              </select>
            </div>

            <div className="field">
              <label htmlFor="cmt">Комментарий</label>
              <input id="cmt" value={comment} onChange={e => setComment(e.target.value)}
                placeholder="необязательно" />
            </div>

            <button className="btn btn--primary btn--block" disabled={busy || qty < 1}
              onClick={submit}>
              {busy ? 'Оформляем…' : 'Создать заявку на закупку'}
            </button>

            {report.needs_expert && (
              <p className="tiny muted">
                Достоверность ниже порога — сначала подтвердите результат на вкладке «Отчёт».
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
