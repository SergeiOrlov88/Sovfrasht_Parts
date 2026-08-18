// Панель эксперта (F2, FR-HITL-02/03). Не отдельное приложение — экран того же
// фронта, доступный только роли expert/admin. Права всё равно проверяет сервер.
//
// Вёрстка по макету design_ref3.html: сводка по очереди, фильтры статуса,
// компактный список задач, а под ним — раскрытая карточка модерации выбранной
// задачи: полоса фото, предложенный результат, кандидаты радиокнопками и
// действия «подтвердить / исправить».
import { useEffect, useState } from 'react'
import { claimTask, listTasks, resolveTask } from './api'
import { BannerError, IconImage } from './icons.jsx'

const STATUS_TABS = [
  { key: 'pending', label: 'В очереди' },
  { key: 'in_progress', label: 'В работе' },
  { key: 'resolved', label: 'Решённые' },
]

const RESOLUTION = {
  confirmed: 'подтверждено',
  corrected: 'исправлено',
  rejected: 'не определяется',
}

const PHOTO_LABEL = {
  nameplate: 'Шильдик',
  overview: 'Деталь',
  context: 'Место',
}

// Тот же порог, что на экране отчёта и на бэкенде (FR-REC-04)
const HIGH = 70

// Псевдо-кандидат «вернуть механику»: в макете он третьим в списке выбора
const REJECT = '__reject__'

function fmtSla(seconds) {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds} с`
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`
  return `${(seconds / 3600).toFixed(1)} ч`
}

/** Метка задачи справа: чем она в очереди примечательна. */
function taskFlag(task) {
  const c = task.recognition?.confidence
  if (c != null && c < HIGH) return { cls: 'pill--danger', label: 'низкая %' }
  if (!task.part) return { cls: 'pill--warn', label: 'каталог' }
  return { cls: 'pill--info', label: 'проверка' }
}

/** Строка очереди: что предложено, откуда и насколько срочно. */
function TaskRow({ task, active, onSelect }) {
  const flag = taskFlag(task)
  const c = task.recognition?.confidence
  return (
    <button className={`task-row${active ? ' is-current' : ''}`} onClick={onSelect}>
      <div>
        <h3>{task.part ? task.part.name : 'деталь не определена'}</h3>
        <p className="tiny muted">
          {task.vessel_name || '—'} · {task.author_name || '—'}
          {c != null ? ` · ${c}%` : ''} · ожидание {fmtSla(task.sla.wait_seconds)}
        </p>
      </div>
      <span className={`pill ${flag.cls}`}>{flag.label}</span>
    </button>
  )
}

/** Раскрытая карточка модерации выбранной задачи. */
function ModerationCard({ task, onChanged, onError }) {
  const [busy, setBusy] = useState(false)
  // Что эксперт выбрал: id позиции каталога или REJECT. По умолчанию — то,
  // что предложила система.
  const [picked, setPicked] = useState(task.part?.id ?? null)

  useEffect(() => { setPicked(task.part?.id ?? null) }, [task.id])

  async function act(fn) {
    setBusy(true)
    try {
      await fn()
      await onChanged()
    } catch (e) {
      onError(e.message)
    } finally {
      setBusy(false)
    }
  }

  /** Применяет выбор эксперта тем же контрактом, что и раньше. */
  function apply() {
    if (picked === REJECT) {
      return act(() => resolveTask(task.id, { resolution: 'rejected' }))
    }
    if (picked && picked === task.part?.id) {
      return act(() => resolveTask(task.id, { resolution: 'confirmed' }))
    }
    return act(() => resolveTask(task.id, { resolution: 'corrected', correct_part_id: picked }))
  }

  const done = task.status === 'resolved'
  const rec = task.recognition
  const photos = task.photos.slice(0, 3)

  // Кандидаты для выбора: предложенная позиция + альтернативы, без дублей
  const options = []
  if (task.part) options.push({ id: task.part.id, part: task.part, relevance: null, proposed: true })
  task.candidates.forEach(c => {
    if (!options.some(o => o.id === c.part.id)) {
      options.push({ id: c.part.id, part: c.part, relevance: c.relevance })
    }
  })

  return (
    <article className="moderation-task-card">
      {photos.length > 0 && (
        <div className="mtc-photos">
          {photos.map(p => (
            <div key={p.id}>
              <img src={p.url} alt={p.kind} loading="lazy" />
              <label>{PHOTO_LABEL[p.kind] || p.kind}</label>
            </div>
          ))}
        </div>
      )}

      <div className="mtc-body">
        <div>
          <div className="kicker">Предложенный результат</div>
          <h3 style={{ fontSize: 16, fontWeight: 800 }}>
            {task.part ? task.part.name : 'деталь не определена'}
          </h3>
          <p className="tiny muted">
            {rec?.oem_detected && <>Маркировка <span className="mono">{rec.oem_detected}</span> · </>}
            уверенность {rec?.confidence ?? 0}% · {task.vessel_name || '—'}
          </p>
        </div>

        {rec?.ocr_text && (
          <div className="id-mark" style={{ marginTop: 0 }}>
            <span>Прочитано с детали</span>
            <code>{rec.ocr_text.slice(0, 220)}</code>
          </div>
        )}

        {!done && (
          <>
            {options.map(o => (
              <button key={o.id} className={`candidate${picked === o.id ? ' is-pick' : ''}`}
                onClick={() => setPicked(o.id)}>
                <span className="radio" />
                <div className="grow">
                  <b>{o.part.maker ? `${o.part.maker} · ` : ''}{o.part.name}</b>
                  <p className="tiny muted">
                    <span className="mono">{o.part.oem_number || 'без номера'}</span>
                    {o.proposed
                      ? ' · предложено системой'
                      : o.relevance != null ? ` · релевантность ${Math.round(o.relevance * 100)}%` : ''}
                  </p>
                </div>
              </button>
            ))}

            <button className={`candidate${picked === REJECT ? ' is-pick' : ''}`}
              onClick={() => setPicked(REJECT)}>
              <span className="radio" />
              <div className="grow">
                <b>Не опознана / запросить новый кадр</b>
                <p className="tiny muted">Вернуть механику на пересъёмку шильдика</p>
              </div>
            </button>

            {task.status === 'pending' ? (
              <div className="btn-row">
                <button className="btn btn--ghost btn--sm" disabled={busy}
                  onClick={() => act(() => claimTask(task.id))}>Взять в работу</button>
                <button className="btn btn--primary btn--sm" disabled={busy || !picked}
                  onClick={apply}>Подтвердить</button>
              </div>
            ) : (
              <button className="btn btn--primary btn--block btn--sm" disabled={busy || !picked}
                onClick={apply}>Подтвердить</button>
            )}

            {!picked && (
              <p className="tiny muted">Выберите позицию или верните кадр механику.</p>
            )}
          </>
        )}

        {done && (
          <p className="tiny muted">
            Решение: {RESOLUTION[task.resolution] || task.resolution} ·
            время работы {fmtSla(task.sla.work_seconds)}
          </p>
        )}
      </div>
    </article>
  )
}

export default function ExpertQueue({ onBack }) {
  const [status, setStatus] = useState('pending')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)

  async function load() {
    setError('')
    try {
      const page = await listTasks(status)
      setData(page)
      // Держим раскрытой первую задачу списка: эксперт работает сверху вниз
      setOpenId(prev => (page.items.some(t => t.id === prev) ? prev : page.items[0]?.id ?? null))
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { load() }, [status])

  const items = data?.items || []
  const open = items.find(t => t.id === openId)

  // Сводка считается по тому, что реально пришло в очереди
  const lowCount = items.filter(t => (t.recognition?.confidence ?? 0) < HIGH).length
  const noCatalogCount = items.filter(t => !t.part).length

  return (
    <div className="screen-body">
      <button className="btn btn--link" onClick={onBack}>← Назад</button>

      <div className="page-head">
        <div className="kicker">Модерация опознаний</div>
        <h1>Очередь эксперта</h1>
        <p>Сначала низкая достоверность и позиции вне каталога.</p>
      </div>

      <div className="stat-row">
        <div className="stat"><b>{lowCount}</b><span>низкая %</span></div>
        <div className="stat"><b>{noCatalogCount}</b><span>нет в каталоге</span></div>
        <div className="stat"><b>{data?.total ?? 0}</b><span>всего</span></div>
      </div>

      <div className="filters" role="tablist">
        {STATUS_TABS.map(t => (
          <button key={t.key} role="tab" aria-selected={status === t.key}
            className={status === t.key ? 'is-active' : undefined}
            onClick={() => setStatus(t.key)}>{t.label}</button>
        ))}
      </div>

      {error && (
        <div className="banner banner--danger">
          <BannerError />
          <div>{error}</div>
        </div>
      )}

      {!data && !error && (
        <div className="stack">
          <div className="skeleton sk-block" />
          <div className="skeleton sk-block" />
        </div>
      )}

      {data && items.length === 0 && (
        <div className="empty-state">
          <div className="empty-ico"><IconImage width="26" height="26" /></div>
          <h2>Задач нет</h2>
          <p>В этом разделе очередь пуста.</p>
        </div>
      )}

      {items.length > 0 && (
        <div className="stack">
          {items.map(t => (
            <TaskRow key={t.id} task={t} active={t.id === openId}
              onSelect={() => setOpenId(t.id === openId ? null : t.id)} />
          ))}
        </div>
      )}

      {open && (
        <>
          <div className="section-label">
            <span>Открытая задача</span>
            <span className="mono">{String(open.scan_id).slice(0, 8)}</span>
          </div>
          <ModerationCard task={open} onChanged={load} onError={setError} />
        </>
      )}
    </div>
  )
}
