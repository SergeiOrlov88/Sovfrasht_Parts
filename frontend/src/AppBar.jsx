// Верхняя панель приложения: марка, название, роль и контекст (судно или скан).
// Одна и та же на всех экранах — так у пользователя всегда есть точка возврата
// и видно, от чьего имени и по какому судну он работает (docs/09).
// Вёрстка по макету design_ref3.html: слева бренд в две строки, справа
// ролевая пилюля с индикатором и подпись контекста.
import { BrandMark } from './icons.jsx'

const ROLE_LABELS = {
  mechanic: 'Механик',
  supplier_manager: 'Снабженец',
  fleet_owner: 'Судовладелец',
  expert: 'Эксперт',
  admin: 'Администратор',
}

// Роли модерации отличаем цветом пилюли: панель эксперта — не борт
const INFO_ROLES = ['expert', 'admin']

export default function AppBar({ user, onLogout, onExpert, context }) {
  const role = ROLE_LABELS[user.role] || user.role
  // Судов у механика обычно одно; если несколько — показываем первое и счётчик,
  // чтобы панель не разъезжалась
  const vessels = user.vessels || []
  const vessel = vessels.length
    ? vessels[0].name + (vessels.length > 1 ? ` +${vessels.length - 1}` : '')
    : null
  const sub = context || vessel

  return (
    <header className="app-bar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true"><BrandMark /></div>
        <div className="brand-name">Совфрахт<span>Детали</span></div>
      </div>

      <div className="role-stack">
        <div className={`role-pill${INFO_ROLES.includes(user.role) ? ' role-pill--info' : ''}`}>
          <i />{role}
        </div>
        {sub && <div className="role-sub">{sub}</div>}
        <div className="bar-actions">
          {onExpert && <button onClick={onExpert}>Очередь</button>}
          <button onClick={onLogout}>Выйти</button>
        </div>
      </div>
    </header>
  )
}
