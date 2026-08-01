// Вкладка «Ремонт» (D1, FR-REPAIR-01/02): вердикт, обоснование,
// сравнение «замена vs ремонт» и обязательный дисклеймер.
import { useEffect, useState } from 'react'
import { getRepair } from './api'

const VERDICT = {
  repair: { label: 'Ремонт', color: 'var(--ok)',
            hint: 'Деталь, как правило, ремонтопригодна' },
  replace: { label: 'Замена', color: 'var(--warn)',
             hint: 'Как правило, выгоднее заменить' },
  unknown: { label: 'Нет данных', color: 'var(--muted)',
             hint: 'Отраслевого правила для этого типа детали пока нет' },
}

export default function Repair({ report }) {
  const part = report.part
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!part) return
    getRepair(part.id).then(setData).catch(e => setError(e.message))
  }, [part?.id])

  if (!part) {
    return (
      <div className="card stub">
        <p className="muted">
          Деталь не определена — оценивать ремонтопригодность не по чему.
          Уточните результат на вкладке «Отчёт».
        </p>
      </div>
    )
  }

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="muted">Загружаем рекомендацию…</p>

  const v = VERDICT[data.verdict] || VERDICT.unknown
  const e = data.estimate

  return (
    <>
      <div className="card">
        <div className="conf-row">
          <span className="conf-label">Рекомендация</span>
          <span className="conf-value" style={{ color: v.color }}>{v.label}</span>
        </div>
        <p className="muted small">{v.hint}</p>
        {data.rationale && <p className="rationale">{data.rationale}</p>}
        {data.rule_subtype && (
          <p className="muted small">Правило по типу детали: {data.rule_subtype}</p>
        )}
      </div>

      {/* Сравнение «замена vs ремонт» (FR-REPAIR-01) */}
      <div className="card">
        <h3>Замена или ремонт</h3>
        <div className="compare">
          <div className="opt">
            <div className="opt-title">Замена</div>
            <div className="opt-value">{e.replace_price || 'цена по запросу'}</div>
            <div className="muted small">
              {e.replace_lead_time ? `срок ${e.replace_lead_time}` : 'срок уточняется'}
              {e.replace_supplier ? ` · ${e.replace_supplier}` : ''}
            </div>
          </div>
          <div className="opt">
            <div className="opt-title">Ремонт</div>
            <div className="opt-value">{e.repair_cost_estimate || '—'}</div>
            <div className="muted small">
              {e.repair_share ? `${e.repair_share} от цены новой` : 'доля не определена'}
              {e.repair_time ? ` · срок ${e.repair_time}` : ''}
            </div>
          </div>
        </div>
        {!e.replace_price && (
          <p className="muted small">
            Цена замены неизвестна — оценка ремонта не рассчитана.
          </p>
        )}
      </div>

      {/* Восстановленная деталь — третий путь между ремонтом и новой */}
      {data.reman_offers.length > 0 && (
        <div className="card">
          <h3>Восстановленная деталь</h3>
          <ul className="list">
            {data.reman_offers.map((o, i) => (
              <li key={i}>
                <div>
                  <b>{o.supplier.name}</b>
                  <div className="muted small">
                    {o.price || 'цена по запросу'}
                    {o.lead_time ? ` · срок ${o.lead_time}` : ''}
                  </div>
                </div>
                {o.deep_link && (
                  <a className="btn small" href={o.deep_link} target="_blank" rel="noreferrer">
                    Открыть
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Обязателен при любом вердикте (FR-REPAIR-02) */}
      <div className="card">
        <p className="warn-box">{data.disclaimer}</p>
      </div>
    </>
  )
}
