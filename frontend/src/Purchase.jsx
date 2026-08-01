// Вкладка «Закупка» (C1/C2): предложения поставщиков и оформление заявки.
// Цены демонстрационные — это помечено явно, чтобы их не приняли за реальные.
import { useEffect, useState } from 'react'
import { createPartRequest, getOffers } from './api'

const STOCK = {
  in: { label: 'в наличии', color: 'var(--ok)' },
  low: { label: 'мало', color: 'var(--warn)' },
  out: { label: 'нет', color: 'var(--bad)' },
}

const SUPPLIER_TYPE = {
  marketplace: 'площадка',
  supplier: 'дистрибьютор',
  oem: 'производитель',
  reman: 'восстановление',
}

function OfferRow({ offer }) {
  const stock = STOCK[offer.stock_status] || { label: '—', color: 'var(--muted)' }
  return (
    <li>
      <div>
        <b>{offer.supplier.name}</b>
        <span className="muted"> · {SUPPLIER_TYPE[offer.supplier.type] || offer.supplier.type}</span>
        {offer.supplier.region && <span className="muted"> · {offer.supplier.region}</span>}
        <div className="muted small">
          {offer.price || 'цена по запросу'}
          {offer.lead_time ? ` · срок ${offer.lead_time}` : ''}
          {offer.source !== 'api' ? ' · демо-данные' : ''}
        </div>
      </div>
      <div className="row">
        <span className="pill" style={{ color: stock.color }}>{stock.label}</span>
        {offer.deep_link && (
          <a className="btn small" href={offer.deep_link} target="_blank" rel="noreferrer">
            Открыть
          </a>
        )}
      </div>
    </li>
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
      <div className="card stub">
        <p className="muted">Деталь не определена — закупать нечего. Уточните результат на вкладке «Отчёт».</p>
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

  return (
    <>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Предложения поставщиков</h3>
        {!data && <p className="muted">Загружаем…</p>}
        {data?.message && <p className="muted">{data.message}</p>}
        {data?.offers?.length > 0 && (
          <ul className="list">
            {data.offers.map((o, i) => <OfferRow key={i} offer={o} />)}
          </ul>
        )}
      </div>

      {data?.alternatives?.map(alt => (
        <div className="card" key={alt.part.id}>
          <h3>Аналог: {alt.part.name}</h3>
          <p className="muted small">
            {alt.part.maker} · {alt.part.oem_number || 'без номера'} · совместимость: {alt.compatibility}
          </p>
          {alt.offers.length
            ? <ul className="list">{alt.offers.map((o, i) => <OfferRow key={i} offer={o} />)}</ul>
            : <p className="muted small">Предложений нет.</p>}
        </div>
      ))}

      <div className="card">
        <h3>Заявка на снабжение</h3>
        {created ? (
          <p className="ok-box">
            Заявка создана, статус «{created.status}».
            {created.idempotent_reuse && ' Такая заявка уже была — повторно не создавали.'}
          </p>
        ) : (
          <>
            <label htmlFor="qty">Количество</label>
            <input id="qty" type="number" min="1" value={qty}
              onChange={e => setQty(e.target.value)} />

            <label htmlFor="prio">Приоритет</label>
            <select id="prio" value={priority} onChange={e => setPriority(e.target.value)}>
              <option value="low">низкий</option>
              <option value="normal">обычный</option>
              <option value="urgent">срочно</option>
            </select>

            <label htmlFor="cmt">Комментарий</label>
            <input id="cmt" value={comment} onChange={e => setComment(e.target.value)}
              placeholder="необязательно" />

            <button className="btn" disabled={busy || qty < 1} onClick={submit}>
              {busy ? 'Оформляем…' : 'Оформить заявку'}
            </button>
            {report.needs_expert && (
              <p className="muted small">
                Достоверность ниже порога — сначала подтвердите результат на вкладке «Отчёт».
              </p>
            )}
          </>
        )}
      </div>
    </>
  )
}
