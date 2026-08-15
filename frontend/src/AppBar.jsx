// Верхняя панель приложения: логотип, название, кто вошёл и выход.
// Одна и та же на всех экранах — так у пользователя всегда есть точка возврата
// и видно, от чьего имени и по какому судну он работает (docs/09).
const ROLE_LABELS = {
  mechanic: 'Механик',
  supplier_manager: 'Снабженец',
  fleet_owner: 'Судовладелец',
  expert: 'Эксперт',
  admin: 'Администратор',
}

export default function AppBar({ user, onLogout, onExpert }) {
  const role = ROLE_LABELS[user.role] || user.role
  // Судов у механика обычно одно; если несколько — показываем первое и счётчик,
  // чтобы панель не разъезжалась
  const vessels = user.vessels || []
  const vessel = vessels.length
    ? vessels[0].name + (vessels.length > 1 ? ` +${vessels.length - 1}` : '')
    : null

  return (
    <div className="bar">
      <div className="logo">⚓</div>
      <div className="brand">
        Совфрахт Детали
        <small>Распознавание · закупка · ремонт</small>
      </div>
      <div className="user">
        <b>{user.full_name}</b>
        {role}{vessel ? ` · ${vessel}` : ''}{' '}
        {onExpert && (
          <>
            <button className="logout" onClick={onExpert}>Очередь</button>
            {' · '}
          </>
        )}
        <button className="logout" onClick={onLogout}>Выйти</button>
      </div>
    </div>
  )
}
