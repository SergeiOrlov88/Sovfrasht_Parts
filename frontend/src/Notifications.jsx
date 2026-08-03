// Уведомления внутри приложения (FR-NOT-01). Email — следующий этап.
import { useEffect, useState } from 'react'
import { listNotifications, readNotification } from './api'

export default function Notifications({ onOpenScan }) {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(false)

  async function load() {
    try {
      setData(await listNotifications())
    } catch {
      /* уведомления не критичны: молча не показываем блок */
    }
  }

  useEffect(() => { load() }, [])

  if (!data || data.total === 0) return null

  return (
    <div className="notifications">
      <button className="link" onClick={() => setOpen(v => !v)}>
        Уведомления{data.unread > 0 ? ` · ${data.unread} новых` : ''}
      </button>

      {open && (
        <ul className="list">
          {data.items.map(n => (
            <li key={n.id} className={n.read_at ? 'read' : ''}>
              <div>
                <b>{n.title}</b>
                <div className="muted small">{n.body}</div>
              </div>
              <div className="row">
                {n.payload?.scan_id && (
                  <button className="btn small" onClick={async () => {
                    if (!n.read_at) { await readNotification(n.id); await load() }
                    onOpenScan(n.payload.scan_id)
                  }}>Открыть</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
