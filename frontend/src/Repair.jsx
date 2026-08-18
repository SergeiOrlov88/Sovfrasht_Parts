// Вкладка «Ремонт» (D1, FR-REPAIR-01/02): вердикт-«штамп», сравнение
// «ремонт vs замена» в двух колонках и обязательный дисклеймер.
// Вёрстка по макету design_ref3.html: рекомендованная колонка подсвечена,
// дисклеймер лежит внутри блока вердикта и не прячется никогда.
import { useEffect, useState } from 'react'
import { getRepair } from './api'
import { BannerError, EmptyCamera } from './icons.jsx'
import { SupplierRow } from './Purchase.jsx'

const VERDICT = {
  repair: {
    stamp: 'ремонт',
    title: 'Рекомендуем ремонт, замена не обязательна',
    hint: 'Деталь этого типа, как правило, ремонтопригодна.',
    block: ' repair-verdict--ok',
    stampMod: ' verdict-stamp--ok',
    pick: 'repair',
  },
  replace: {
    stamp: 'замена',
    title: 'Рекомендуем заменить, не ремонтировать',
    hint: 'Судовой ремонт этого типа детали обычно не восстанавливает паспортный ресурс.',
    block: '',
    stampMod: '',
    pick: 'replace',
  },
  unknown: {
    stamp: 'нет данных',
    title: 'Отраслевого правила для этого типа детали пока нет',
    hint: 'Честнее сказать «не знаем», чем выдать эвристику за рекомендацию.',
    block: ' repair-verdict--unknown',
    stampMod: ' verdict-stamp--unknown',
    pick: null,
  },
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
      <div className="empty-state">
        <div className="empty-ico"><EmptyCamera /></div>
        <h2>Оценивать не по чему</h2>
        <p>
          Позиции каталога для этой детали нет — стоимость ремонта считается
          от цены новой. Уточните результат на вкладке «Отчёт».
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="banner banner--danger">
        <BannerError />
        <div>{error}</div>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="stack">
        <div className="skeleton sk-title" />
        <div className="skeleton sk-block" />
      </div>
    )
  }

  const v = VERDICT[data.verdict] || VERDICT.unknown
  const e = data.estimate
  // Подсветку рекомендованной колонки красим в цвет вердикта: ремонт — acc,
  // замена — warn, «нет данных» — не подсвечиваем вовсе
  const pickCls = data.verdict === 'repair' ? ' is-pick-ok' : ' is-pick'

  return (
    <div className="stack">
      <div className={`repair-verdict${v.block}`}>
        <div className={`verdict-stamp${v.stampMod}`}>{v.stamp}</div>
        <h2>{v.title}</h2>
        <p className="tiny muted" style={{ marginTop: 8 }}>{data.rationale || v.hint}</p>

        {/* Сравнение «ремонт vs замена» (FR-REPAIR-01) */}
        <div className="compare">
          <div className={`compare-col${v.pick === 'repair' ? pickCls : ''}`}>
            <h3>Ремонт</h3>
            <b className={e.repair_cost_estimate ? undefined : 'is-na'}>
              {e.repair_cost_estimate || 'не рассчитан'}
            </b>
            <ul>
              {e.repair_share && <li>{e.repair_share} от цены новой</li>}
              {e.repair_time && <li>срок {e.repair_time}</li>}
              {data.rule_subtype && <li>правило: {data.rule_subtype}</li>}
              {v.pick === 'repair' && <li>рекомендация системы</li>}
            </ul>
          </div>
          <div className={`compare-col${v.pick === 'replace' ? pickCls : ''}`}>
            <h3>Замена</h3>
            <b className={e.replace_price ? undefined : 'is-na'}>
              {e.replace_price || 'по запросу'}
            </b>
            <ul>
              {e.replace_lead_time && <li>поставка {e.replace_lead_time}</li>}
              {e.replace_supplier && <li>{e.replace_supplier}</li>}
              {!e.replace_price && <li>цена неизвестна</li>}
              {v.pick === 'replace' && <li>рекомендация системы</li>}
            </ul>
          </div>
        </div>

        {/* Обязателен при любом вердикте (FR-REPAIR-02) */}
        <div className="disclaimer">
          <strong>Обязательный дисклеймер</strong>
          {data.disclaimer}
        </div>
      </div>

      {/* Восстановленная деталь — третий путь между ремонтом и новой */}
      {data.reman_offers.length > 0 && (
        <div>
          <div className="section-label">
            <span>Восстановленная деталь</span>
            <span>{data.reman_offers.length}</span>
          </div>
          <div className="stack">
            {data.reman_offers.map((o, i) => <SupplierRow key={i} offer={o} best={i === 0} />)}
          </div>
        </div>
      )}
    </div>
  )
}
