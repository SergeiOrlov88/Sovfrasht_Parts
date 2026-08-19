// Экран отчёта по скану (B1, FR-REP-01..04). Вёрстка по эталонному макету
// design_ref3.html: опознание — СВЕРХУ, карточкой с градиентной кромкой и
// круговым индикатором достоверности; под ним — плашки состояния и только
// затем три вкладки «Отчёт» (B1), «Закупка» (C1/C2) и «Ремонт» (D1).
//
// Опознание идёт первым сознательно: главный вопрос механика — «что у меня в
// руках», и ответ на него не зависит от того, нашлась ли позиция в каталоге.
import { useEffect, useState } from 'react'
import { getReport, sendFeedback } from './api'
import Purchase from './Purchase.jsx'
import Repair from './Repair.jsx'
import { BannerDanger, BannerError, BannerOk, BannerWarn, EmptyCamera } from './icons.jsx'

const TABS = [
  { key: 'report', label: 'Отчёт' },
  { key: 'purchase', label: 'Закупка' },
  { key: 'repair', label: 'Ремонт' },
]

// Порог достоверности из макета 3: ≥70 — зелёный, 40–69 — жёлтый, <40 — красный.
// Нижний порог совпадает с CONFIDENCE_THRESHOLD бэкенда (FR-REC-04).
const HIGH = 70
const MID = 40

/** Круговой индикатор достоверности. pathLength=100 → длина дуги = проценты. */
function ConfidenceMeter({ value }) {
  const pct = Math.max(0, Math.min(100, Math.round(value ?? 0)))
  const mod = pct >= HIGH ? '' : pct >= MID ? ' confidence-meter--mid' : ' confidence-meter--low'
  const label = pct >= HIGH ? 'уверенность' : pct >= MID ? 'средняя' : 'низкая'
  return (
    <div className={`confidence-meter${mod}`} style={{ '--val': String(pct) }}
      aria-label={`Достоверность ${pct} процентов`}>
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle className="cm-track" cx="18" cy="18" r="15.5" pathLength="100" />
        <circle className="cm-val" cx="18" cy="18" r="15.5" pathLength="100" />
      </svg>
      <div className="cm-center"><b>{pct}<small>%</small></b><span>{label}</span></div>
    </div>
  )
}

/** Поле карточки опознания. Пустые значения не показываем. */
function Field({ label, value, mono, wide }) {
  if (!value) return null
  return (
    <div className={`id-field${wide ? ' id-field--wide' : ''}`}>
      <span>{label}</span>
      <b className={mono ? 'mono' : undefined}>{value}</b>
    </div>
  )
}

/** Ячейка каталожного кода — моноширинным, коды сверяют посимвольно. */
function CodeCell({ label, value }) {
  if (!value) return null
  return (
    <div className="code-cell">
      <span>{label}</span>
      <b>{value}</b>
    </div>
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

  if (error && !data) {
    return (
      <div className="screen-body">
        <button className="btn btn--link" onClick={onBack}>← К съёмке</button>
        <div className="banner banner--danger">
          <BannerError />
          <div><b>Отчёт не открылся</b>{error}</div>
        </div>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="screen-body">
        <div className="panel scan-panel">
          <div className="scan-line" />
          <div className="skeleton sk-title" />
          <div className="skeleton sk-line" style={{ width: '88%' }} />
          <div className="skeleton sk-line" style={{ width: '64%' }} />
          <div className="skeleton sk-block" />
        </div>
      </div>
    )
  }

  // identification — что определила vision-модель. Приходит и тогда, когда
  // каталожной позиции нет: именно оно отвечает «что это за деталь».
  const { part, candidates, alternatives, recognition, identification: ident } = data
  const confidence = data.confidence ?? 0
  const isLow = confidence < HIGH || data.confidence_level === 'low'
  const noCatalog = !part && Boolean(ident)
  // by_number — номер дал точное совпадение с каталогом; appearance — нет
  const basis = recognition?.identification_basis
  const specs = part?.specs ? Object.entries(part.specs) : []

  return (
    <div className="screen-body screen-body--tight">
      <button className="btn btn--link" onClick={onBack}>← К съёмке</button>

      {/* ── Опознание: сверху, до каталога (FR-REC-01) ─────────────────────── */}
      <article className="identification-card">
        <div className="id-top">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="kicker">{isLow ? 'Опознание · черновик' : 'Опознание'}</div>
            <h2>{part ? part.name : (ident?.title || 'Деталь не определена')}</h2>
            {ident?.part_type && <div className="id-type">{ident.part_type}</div>}
            {/* Основание опознания (FR-REC-07). Показываем только когда
                подтверждённого номера нет — «по номеру» это норма и шума
                в интерфейсе не заслуживает. */}
            {basis === 'appearance' && (
              <div className="row wrap-row" style={{ marginTop: 8, gap: 6 }}>
                <span className="pill pill--warn">
                  {recognition?.oem_detected
                    ? 'номер не подтверждён каталогом'
                    : 'опознано по внешнему виду'}
                </span>
              </div>
            )}
          </div>
          <ConfidenceMeter value={confidence} />
        </div>

        {(ident || part) && (
          <div className="id-grid">
            <Field label="Производитель" value={ident?.maker || part?.maker} />
            <Field label="Модель" value={ident?.model} mono />
            <Field label="Назначение" value={ident?.function} wide />
            <Field label="Узел" value={part?.equipment} wide />
          </div>
        )}

        {/* Маркировка — моноширинным: её сверяют с деталью посимвольно */}
        {(ident?.markings || recognition?.oem_detected) && (
          <div className="id-mark">
            <span>{ident?.markings ? 'Прочитанная маркировка' : 'Считано с шильдика'}</span>
            <code>{ident?.markings || recognition.oem_detected}</code>
          </div>
        )}

        {ident?.notes && <p className="id-caveat">Оговорка: {ident.notes}</p>}
      </article>

      {/* ── Две отдельные плашки: порог и каталог — это разные проблемы ────── */}
      {isLow && (
        <div className="banner banner--danger">
          <BannerDanger />
          <div>
            <b>Достоверность ниже порога {HIGH}%</b>
            {data.warning
              || 'Автоподтверждение отключено. Заявка уйдёт эксперту — механик не принимает решение по коду.'}
          </div>
        </div>
      )}

      {noCatalog && (
        /* Вторая плашка въезжает следом, а не одновременно: два предупреждения,
           появившиеся разом, читаются как одна вспышка */
        <div className="banner banner--warn" style={{ animationDelay: isLow ? '70ms' : '0ms' }}>
          <BannerWarn />
          <div>
            <b>Опознана, но в каталоге закупки не найдена</b>
            Нет карточки IMPA/OEM Совфрахт. Нельзя выставить поставщиков и цену.
          </div>
        </div>
      )}

      {(isLow || noCatalog) && (
        <>
          <div className="btn-row">
            <button className="btn btn--warn btn--sm" disabled={busy || !data.can_request_expert}
              onClick={() => feedback('reject')}>
              Отправить эксперту
            </button>
            {/* BL-10: эндпоинта заведения позиции ещё нет — кнопка на своём месте
                по макету, но без действия */}
            <button className="btn btn--ghost btn--sm" disabled>Добавить в каталог</button>
          </div>
          <p className="tiny muted">
            «Добавить в каталог» доступно снабженцу и админу. Механик видит кнопку
            серой. Действие пока отключено: заведение позиции из опознания в работе (BL-10).
          </p>
        </>
      )}

      {notice && (
        <div className="banner banner--ok">
          <BannerOk />
          <div>{notice}</div>
        </div>
      )}
      {error && (
        <div className="banner banner--danger">
          <BannerError />
          <div>{error}</div>
        </div>
      )}

      {/* ── Вкладки ────────────────────────────────────────────────────────── */}
      <nav className="tab-bar" role="tablist" aria-label="Разделы отчёта">
        {TABS.map(t => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} type="button"
            className={tab === t.key ? 'is-active' : undefined}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </nav>

      {tab === 'purchase' && <Purchase report={data} />}
      {tab === 'repair' && <Repair report={data} />}

      {tab === 'report' && (
        <div className="stack">
          {/* Позиция найдена в каталоге — показываем коды закупки */}
          {part && (
            <>
              <div className="banner banner--ok">
                <BannerOk />
                <div>
                  <b>Есть в каталоге закупки Совфрахт</b>
                  {part.impa_code
                    ? `Сопоставлено с карточкой IMPA ${part.impa_code}`
                    : 'Позиция найдена в справочнике'}
                  {part.maker ? ` · ${part.maker}` : ''}.
                </div>
              </div>

              {/* Только коды — их сверяют посимвольно, поэтому моноширинный.
                  Категория и прочее кодом не является и живёт ниже. */}
              <div className="codes">
                <CodeCell label="IMPA" value={part.impa_code} />
                <CodeCell label="ISSA" value={part.issa_code} />
                <CodeCell label="OEM" value={part.oem_number} />
              </div>

              {(part.category || specs.length > 0) && (
                <div className="panel">
                  <div className="section-label"><span>Характеристики</span></div>
                  <div className="id-grid" style={{ marginTop: 0 }}>
                    <Field label="Категория" value={part.category} />
                    {specs.map(([k, v]) => <Field key={k} label={k} value={String(v)} />)}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Ни каталога, ни опознания */}
          {!part && !ident && (
            <div className="empty-state">
              <div className="empty-ico"><EmptyCamera /></div>
              <h2>Деталь не определена</h2>
              <p>
                {recognition?.oem_detected
                  ? `С шильдика считан номер ${recognition.oem_detected}, но в каталоге его нет.`
                  : 'Номер на шильдике распознать не удалось. Переснимите шильдик крупнее или отправьте кадры эксперту.'}
              </p>
            </div>
          )}

          {/* Фото скана — по подписанным ссылкам (NFR-SEC-04) */}
          {data.photos.length > 0 && (
            <div>
              <div className="section-label">
                <span>Снимки</span><span>{data.photos.length} кадра</span>
              </div>
              <div className="photo-strip">
                {data.photos.map(p => (
                  <figure key={p.id}>
                    <img src={p.url} alt={p.kind} loading="lazy" />
                    <figcaption>{p.kind}</figcaption>
                  </figure>
                ))}
              </div>
            </div>
          )}

          {/* Кандидаты (NFR-ACC-02) */}
          {candidates.length > 0 && (
            <div>
              <div className="section-label">
                <span>{basis === 'appearance' ? 'Похожее · не подтверждено' : 'Кандидаты'}</span>
                <span>{candidates.length}</span>
              </div>
              <div className="stack">
                {candidates.map(c => (
                  <div className="candidate" key={c.part.id}>
                    <span className="radio" />
                    <div className="grow">
                      <b>{c.part.name}</b>
                      <p className="tiny muted">
                        {c.part.maker || '—'} · <span className="mono">{c.part.oem_number || 'без номера'}</span>
                        {' · '}{Math.round(c.relevance * 100)}%
                      </p>
                      {correcting && (
                        <button className="btn btn--ghost btn--sm" style={{ marginTop: 8 }}
                          disabled={busy} onClick={() => feedback('reject', c.part.id)}>
                          Это верная
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Аналоги (FR-REP-03) */}
          {alternatives.length > 0 && (
            <div>
              <div className="section-label">
                <span>Аналоги и заменители</span>
                <span className="pill pill--warn">не OEM</span>
              </div>
              <div className="stack">
                {alternatives.map(a => (
                  <div className="panel" key={a.part.id}>
                    <b style={{ fontSize: 15 }}>{a.part.name}</b>
                    <p className="tiny muted" style={{ marginTop: 4 }}>
                      {a.part.maker || '—'} · <span className="mono">{a.part.oem_number || '—'}</span>
                      {' · совместимость: '}{a.compatibility}
                    </p>
                    {a.note && <p className="tiny muted" style={{ marginTop: 4 }}>{a.note}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Действия (FR-REP-04) */}
          <div className="panel">
            <div className="section-label"><span>Результат верен?</span></div>
            {data.feedback ? (
              <p className="tiny muted">
                Вы уже ответили: {data.feedback.verdict === 'confirm' ? 'подтверждено' : 'отклонено'}.
              </p>
            ) : (
              <>
                <div className="btn-row">
                  <button className="btn btn--primary btn--sm"
                    disabled={busy || !data.can_confirm}
                    onClick={() => feedback('confirm')}>Всё верно</button>
                  <button className="btn btn--ghost btn--sm" disabled={busy}
                    onClick={() => setCorrecting(v => !v)}>
                    {correcting ? 'Отмена' : 'Не та деталь'}
                  </button>
                </div>
                {correcting && candidates.length === 0 && (
                  <p className="tiny muted" style={{ marginTop: 8 }}>
                    Кандидатов нет — нажмите «Отправить эксперту», он определит деталь.
                  </p>
                )}
                {correcting && candidates.length > 0 && (
                  <p className="tiny muted" style={{ marginTop: 8 }}>
                    Выберите верную позицию в списке кандидатов выше.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
