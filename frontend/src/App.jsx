// Корневой экран: вход, затем съёмка (главный экран механика), отчёт,
// открытие скана по id и панель эксперта. Все экраны идут в одной
// центрированной колонке под общей верхней панелью (docs/09).
import { useEffect, useState } from 'react'
import { login as apiLogin, me as apiMe, tokens } from './api'
import AppBar from './AppBar.jsx'
import Report from './Report.jsx'
import Capture from './Capture.jsx'
import ExpertQueue from './ExpertQueue.jsx'
import Notifications from './Notifications.jsx'

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)
  const [form, setForm] = useState({ login: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [scanId, setScanId] = useState('')      // какой отчёт открыт
  const [scanInput, setScanInput] = useState('')
  const [screen, setScreen] = useState('home')   // home | expert | byid

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
    setScanId('')
    setScreen('home')
  }

  if (checking) {
    return <main className="wrap center"><div className="app"><p className="muted">Загрузка…</p></div></main>
  }

  // ── Вход ───────────────────────────────────────────────────────────────────
  if (!user) {
    return (
      <main className="wrap center">
        <div className="app">
          <form className="card" onSubmit={onSubmit}>
            <div className="bar" style={{ padding: '0 0 8px', position: 'static', background: 'none' }}>
              <div className="logo">⚓</div>
              <div className="brand">
                Совфрахт Детали
                <small>Распознавание · закупка · ремонт</small>
              </div>
            </div>

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

            <button className="btn" type="submit" style={{ marginTop: 10 }}
              disabled={busy || !form.login || !form.password}>
              {busy ? 'Проверяем…' : 'Войти'}
            </button>
          </form>
        </div>
      </main>
    )
  }

  // Роль-гейт: панель эксперта — экран того же приложения, а не отдельное
  // приложение. Права всё равно проверяет сервер (NFR-SEC-03).
  const canModerate = ['expert', 'admin'].includes(user.role)

  // Верхняя панель одна на всех экранах под входом
  const bar = (
    <AppBar
      user={user}
      onLogout={onLogout}
      onExpert={canModerate && screen !== 'expert' ? () => { setScanId(''); setScreen('expert') } : null}
    />
  )

  let body
  if (screen === 'expert' && canModerate) {
    body = <ExpertQueue onBack={() => setScreen('home')} />
  } else if (scanId) {
    body = <Report scanId={scanId} onBack={() => setScanId('')} />
  } else if (screen === 'byid') {
    body = (
      <section className="report">
        <button className="link" onClick={() => setScreen('home')}>← К съёмке</button>
        <h1>Открыть скан по id</h1>
        <p className="lead">Отчёт по уже обработанному скану — например, из письма или от коллеги.</p>
        <div className="card">
          <label htmlFor="scan">Идентификатор скана</label>
          <input id="scan" value={scanInput} placeholder="00000000-0000-0000-0000-000000000000"
            onChange={e => setScanInput(e.target.value)} autoComplete="off" />
          <button className="btn" style={{ marginTop: 6 }} disabled={!scanInput.trim()}
            onClick={() => setScanId(scanInput.trim())}>Открыть отчёт</button>
        </div>
      </section>
    )
  } else {
    // Главный экран — съёмка: с неё начинается работа механика (A1).
    body = (
      <>
        <Notifications onOpenScan={id => setScanId(id)} />
        <Capture user={user} onReady={id => setScanId(id)} onOpenById={() => setScreen('byid')} />
      </>
    )
  }

  return (
    <main className="wrap">
      <div className="app">
        {bar}
        {body}
      </div>
    </main>
  )
}
