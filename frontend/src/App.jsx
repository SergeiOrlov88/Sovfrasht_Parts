// Шаг 1: только вход. Форма -> POST /auth/token -> сохранение токена -> GET /auth/me.
// Остальные экраны (съёмка, отчёт, заявка) — следующие шаги по docs/09.
import { useEffect, useState } from 'react'
import { login as apiLogin, me as apiMe, tokens } from './api'
import Report from './Report.jsx'

const ROLE_LABELS = {
  mechanic: 'Механик',
  supplier_manager: 'Снабженец',
  fleet_owner: 'Судовладелец',
  expert: 'Эксперт',
  admin: 'Администратор',
}

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)
  const [form, setForm] = useState({ login: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [scanId, setScanId] = useState('')      // какой отчёт открыт
  const [scanInput, setScanInput] = useState('')

  // При загрузке — если токен уже лежит, проверяем его через /auth/me
  useEffect(() => {
    if (!tokens.access) {
      setChecking(false)
      return
    }
    apiMe()
      .then(setUser)
      .catch(() => tokens.clear())
      .finally(() => setChecking(false))
  }, [])

  async function onSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const data = await apiLogin(form.login.trim(), form.password)
      tokens.save(data.access_token, data.refresh_token)
      setUser(await apiMe())      // отдельным запросом — проверяем, что токен реально принят
      setForm({ login: '', password: '' })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function onLogout() {
    tokens.clear()
    setUser(null)
  }

  if (checking) return <main className="wrap"><p className="muted">Загрузка…</p></main>

  if (user && scanId) {
    return (
      <main className="wrap">
        <Report scanId={scanId} onBack={() => setScanId('')} />
      </main>
    )
  }

  if (user) {
    return (
      <main className="wrap">
        <section className="card">
          <h1>Совфрахт Детали</h1>
          <p className="muted">Вход выполнен</p>
          <dl className="props">
            <dt>Пользователь</dt><dd>{user.full_name}</dd>
            <dt>Логин</dt><dd>{user.login}</dd>
            <dt>Роль</dt><dd>{ROLE_LABELS[user.role] || user.role}</dd>
            <dt>Суда</dt>
            <dd>{user.vessels?.length ? user.vessels.map(v => v.name).join(', ') : '—'}</dd>
          </dl>

          {/* Съёмка и реестр сканов — следующие шаги; пока открываем отчёт по id */}
          <label htmlFor="scan">Открыть отчёт по скану</label>
          <input id="scan" value={scanInput} placeholder="id скана"
            onChange={e => setScanInput(e.target.value)} autoComplete="off" />
          <button className="btn" disabled={!scanInput.trim()}
            onClick={() => setScanId(scanInput.trim())}>Открыть отчёт</button>

          <button className="btn ghost" onClick={onLogout}>Выйти</button>
        </section>
      </main>
    )
  }

  return (
    <main className="wrap">
      <form className="card" onSubmit={onSubmit}>
        <h1>Совфрахт Детали</h1>
        <p className="muted">Вход в систему</p>

        <label htmlFor="login">Логин</label>
        <input
          id="login"
          value={form.login}
          onChange={e => setForm({ ...form, login: e.target.value })}
          autoComplete="username"
          autoFocus
          required
        />

        <label htmlFor="password">Пароль</label>
        <input
          id="password"
          type="password"
          value={form.password}
          onChange={e => setForm({ ...form, password: e.target.value })}
          autoComplete="current-password"
          required
        />

        {error && <p className="error" role="alert">{error}</p>}

        <button className="btn" type="submit" disabled={busy || !form.login || !form.password}>
          {busy ? 'Проверяем…' : 'Войти'}
        </button>
      </form>
    </main>
  )
}
