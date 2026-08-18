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
    <div style={{ padding: '0 var(--pad)' }}>
      <button className="btn btn--link" onClick={() => setOpen(v => !v)}>
        Уведомления
        {data.unread > 0 && <span className="pill pill--info">{data.unread}</span>}
      </button>

      {open && (
        <div className="notice-list" style={{ marginTop: 8 }}>
          {data.items.map(n => (
            <div key={n.id} className={`notice${n.read_at ? ' is-read' : ''}`}>
              <div className="grow">
                <div style={{ fontWeight: 700, fontSize: 14 }}>{n.title}</div>
                {n.body && <div className="tiny">{n.body}</div>}
              </div>
              {n.payload?.scan_id && (
                <button className="btn btn--ghost btn--sm" onClick={async () => {
                  if (!n.read_at) { await readNotification(n.id); await load() }
                  onOpenScan(n.payload.scan_id)
                }}>Открыть</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
