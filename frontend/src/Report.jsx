// Экран отчёта по скану (B1, FR-REP-01..04). Три вкладки как в прототипе:
// «Отчёт» (B1), «Закупка» (C1/C2) и «Ремонт» (D1).
import { useEffect, useState } from 'react'
import { getReport, sendFeedback } from './api'
import Purchase from './Purchase.jsx'
import Repair from './Repair.jsx'

const TABS = [
  { key: 'report', label: 'Отчёт' },
  { key: 'purchase', label: 'Закупка' },
  { key: 'repair', label: 'Ремонт' },
]

const LEVEL_COLOR = { high: 'var(--ok)', medium: 'var(--warn)', low: 'var(--bad)' }
const LEVEL_LABEL = { high: 'Высокая', medium: 'Средняя', low: 'Низкая' }

function Field({ label, value }) {
  if (!value) return null
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  )
}

export default function Report({ scanId, onBack }) {
  const [tab, setTab] = useState('report')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [correcting, setCorrecting] = useState(false)

  async function load() {
    try {
      setData(await getReport(scanId))
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    load()
  }, [scanId])

  async function feedback(verdict, correctPartId) {
    setBusy(true)
    setError('')
    try {
      const result = await sendFeedback(scanId, { verdict, correct_part_id: correctPartId })
      setNotice(result.message)
      setCorrecting(false)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !data) return <p className="error">{error}</p>
  if (!data) return <p className="muted">Загружаем отчёт…</p>

  const { part, candidates, alternatives, recognition } = data
  const level = data.confidence_level || 'low'

  return (
    <section className="report">
      <button className="link" onClick={onBack}>← К списку</button>

      <div className="tabs" role="tablist">
        {TABS.map(t => (
          <button key={t.key} role="tab" aria-selected={tab === t.key}
            className={`tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      {tab === 'purchase' && <Purchase report={data} />}

      {tab === 'repair' && <Repair report={data} />}

      {tab === 'report' && (
        <>
          {/* Индикатор достоверности (FR-REP-02) */}
          <div className="card">
            <div className="conf-row">
              <span className="conf-label">Достоверность</span>
              <span className="conf-value" style={{ color: LEVEL_COLOR[level] }}>
                {data.confidence ?? 0}% · {LEVEL_LABEL[level]}
              </span>
            </div>
            <div className="conf-bar">
              <span style={{ width: `${data.confidence ?? 0}%`, background: LEVEL_COLOR[level] }} />
            </div>
            {data.warning && <p className="warn-box">{data.warning}</p>}
            {notice && <p className="ok-box">{notice}</p>}
            {error && <p className="error">{error}</p>}
          </div>

          {/* Позиция каталога (FR-REP-01) */}
          <div className="card">
            <h2>{part ? part.name : 'Деталь не определена'}</h2>
            {part ? (
              <dl className="props">
                <Field label="Производитель" value={part.maker} />
                <Field label="Оборудование" value={part.equipment} />
                <Field label="IMPA" value={part.impa_code} />
                <Field label="ISSA" value={part.issa_code} />
                <Field label="OEM" value={part.oem_number} />
                <Field label="Категория" value={part.category} />
                {part.specs && Object.entries(part.specs).map(([k, v]) => (
                  <Field key={k} label={k} value={String(v)} />
                ))}
              </dl>
            ) : (
              <p className="muted">
                {recognition?.oem_detected
                  ? `С шильдика считан номер ${recognition.oem_detected}, но в каталоге его нет.`
                  : 'Номер на шильдике распознать не удалось.'}
              </p>
            )}
          </div>

          {/* Кандидаты (NFR-ACC-02) */}
          {candidates.length > 0 && (
            <div className="card">
              <h3>Кандидаты</h3>
              <ul className="list">
                {candidates.map(c => (
                  <li key={c.part.id}>
                    <div>
                      <b>{c.part.name}</b>
                      <span className="muted"> · {c.part.maker || '—'} · {c.part.oem_number || 'без номера'}</span>
                    </div>
                    <div className="row">
                      <span className="pill">{Math.round(c.relevance * 100)}%</span>
                      {correcting && (
                        <button className="btn small" disabled={busy}
                          onClick={() => feedback('reject', c.part.id)}>Это верная</button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Аналоги (FR-REP-03) */}
          {alternatives.length > 0 && (
            <div className="card">
              <h3>Аналоги и заменители</h3>
              <ul className="list">
                {alternatives.map(a => (
                  <li key={a.part.id}>
                    <div>
                      <b>{a.part.name}</b>
                      <span className="muted"> · {a.part.maker || '—'} · {a.part.oem_number || '—'}</span>
                      {a.note && <div className="muted small">{a.note}</div>}
                    </div>
                    <span className="pill">{a.compatibility}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Действия (FR-REP-04) */}
          <div className="card actions">
            {data.feedback ? (
              <p className="muted">
                Вы уже ответили: {data.feedback.verdict === 'confirm' ? 'подтверждено' : 'отклонено'}.
              </p>
            ) : (
              <>
                {data.can_confirm && (
                  <button className="btn" disabled={busy}
                    onClick={() => feedback('confirm')}>Всё верно</button>
                )}
                <button className="btn ghost" disabled={busy}
                  onClick={() => setCorrecting(v => !v)}>
                  {correcting ? 'Отмена' : 'Не та деталь'}
                </button>
                {data.can_request_expert && (
                  <button className="btn ghost" disabled={busy}
                    onClick={() => feedback('reject')}>Отправить эксперту</button>
                )}
              </>
            )}
            {correcting && candidates.length === 0 && (
              <p className="muted small">
                Кандидатов нет — нажмите «Отправить эксперту», он определит деталь.
              </p>
            )}
          </div>

          {/* Фото скана — по подписанным ссылкам (NFR-SEC-04) */}
          {data.photos.length > 0 && (
            <div className="card">
              <h3>Фото</h3>
              <div className="thumbs">
                {data.photos.map(p => (
                  <img key={p.id} src={p.url} alt={p.kind} loading="lazy" />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
