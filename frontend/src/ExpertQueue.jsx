// Панель эксперта (F2, FR-HITL-02/03). Не отдельное приложение — экран того же
// фронта, доступный только роли expert/admin. Права всё равно проверяет сервер.
import { useEffect, useState } from 'react'
import { claimTask, listTasks, resolveTask } from './api'

const STATUS_TABS = [
  { key: 'pending', label: 'В очереди' },
  { key: 'in_progress', label: 'В работе' },
  { key: 'resolved', label: 'Решённые' },
]

function fmtSla(seconds) {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds} с`
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`
  return `${(seconds / 3600).toFixed(1)} ч`
}

function Task({ task, onChanged, onError }) {
  const [busy, setBusy] = useState(false)
  const [picking, setPicking] = useState(false)

  async function act(fn) {
    setBusy(true)
    try {
      await fn()
      setPicking(false)
      await onChanged()
    } catch (e) {
      onError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const done = task.status === 'resolved'

  return (
    <div className="card">
      <div className="conf-row">
        <span className="conf-label">
          {task.vessel_name || '—'} · {task.author_name || '—'}
        </span>
        <span className="pill">
          ожидание {fmtSla(task.sla.wait_seconds)}
          {task.sla.total_seconds != null && ` · всего ${fmtSla(task.sla.total_seconds)}`}
        </span>
      </div>

      {/* Фото — по подписанным ссылкам */}
      {task.photos.length > 0 && (
        <div className="thumbs">
          {task.photos.map(p => <img key={p.id} src={p.url} alt={p.kind} loading="lazy" />)}
        </div>
      )}

      <h3 style={{ marginTop: 10 }}>
        Предложено: {task.part ? task.part.name : 'деталь не определена'}
      </h3>
      {task.part && (
        <p className="muted small">
          {task.part.maker || '—'} · {task.part.oem_number || 'без номера'}
        </p>
      )}
      <p className="muted small">
        Достоверность {task.recognition?.confidence ?? 0}%
        {task.recognition?.oem_detected ? ` · с шильдика: ${task.recognition.oem_detected}` : ''}
      </p>
      {task.recognition?.ocr_text && (
        <p className="rationale">{task.recognition.ocr_text.slice(0, 220)}</p>
      )}

      {task.candidates.length > 0 && (
        <>
          <h3 style={{ marginTop: 10 }}>Кандидаты</h3>
          <ul className="list">
            {task.candidates.map(c => (
              <li key={c.part.id}>
                <div>
                  <b>{c.part.name}</b>
                  <span className="muted"> · {c.part.maker || '—'} · {c.part.oem_number || '—'}</span>
                </div>
                <div className="row">
                  <span className="pill">{Math.round(c.relevance * 100)}%</span>
                  {picking && !done && (
                    <button className="btn small" disabled={busy}
                      onClick={() => act(() => resolveTask(task.id,
                        { resolution: 'corrected', correct_part_id: c.part.id }))}>
                      Это верная
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {done ? (
        <p className="muted small" style={{ marginTop: 10 }}>
          Решение: {task.resolution} · время работы {fmtSla(task.sla.work_seconds)}
        </p>
      ) : (
        <div className="actions" style={{ marginTop: 10 }}>
          {task.status === 'pending' && (
            <button className="btn ghost" disabled={busy}
              onClick={() => act(() => claimTask(task.id))}>Взять в работу</button>
          )}
          {task.part && (
            <button className="btn" disabled={busy}
              onClick={() => act(() => resolveTask(task.id, { resolution: 'confirmed' }))}>
              Подтвердить
            </button>
          )}
          <button className="btn ghost" disabled={busy || !task.candidates.length}
            onClick={() => setPicking(v => !v)}>
            {picking ? 'Отмена' : 'Исправить'}
          </button>
          <button className="btn ghost" disabled={busy}
            onClick={() => act(() => resolveTask(task.id, { resolution: 'rejected' }))}>
            Не определяется
          </button>
        </div>
      )}
    </div>
  )
}

export default function ExpertQueue({ onBack }) {
  const [status, setStatus] = useState('pending')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setData(await listTasks(status))
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { load() }, [status])

  return (
    <section className="report">
      <button className="link" onClick={onBack}>← Назад</button>
      <h2>Очередь эксперта</h2>

      <div className="tabs" role="tablist">
        {STATUS_TABS.map(t => (
          <button key={t.key} role="tab" aria-selected={status === t.key}
            className={`tab ${status === t.key ? 'active' : ''}`}
            onClick={() => setStatus(t.key)}>{t.label}</button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Загружаем очередь…</p>}
      {data?.items?.length === 0 && (
        <div className="card stub"><p className="muted">Задач нет.</p></div>
      )}
      {data?.items?.map(t => (
        <Task key={t.id} task={t} onChanged={load} onError={setError} />
      ))}
    </section>
  )
}
