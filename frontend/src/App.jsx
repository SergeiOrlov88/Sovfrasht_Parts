// Корневой экран: вход, затем съёмка (главный экран механика), отчёт,
// открытие скана по id и панель эксперта. Все экраны идут в одном
// центрированном шелле под общей верхней панелью (docs/09).
//
// Переключатель экранов, боковые аннотации и рамка телефона из макета сюда
// сознательно не перенесены: это презентационная обвязка для показа всех
// экранов на одной странице, а не навигация приложения. Ролевая навигация и
// лендинг — отдельные задачи BL-01/BL-04.
import { useEffect, useState } from 'react'
import { login as apiLogin, me as apiMe, MOCK_ENABLED, tokens } from './api'
import AppBar from './AppBar.jsx'
import Report from './Report.jsx'
import Capture from './Capture.jsx'
import ExpertQueue from './ExpertQueue.jsx'
import Notifications from './Notifications.jsx'
import { BannerError, BrandMark } from './icons.jsx'

// Дев-переключатель состояний отчёта. Виден только на стабе: на демо-сервере
// vision-модель отключена (ADR-06), и вживую эти три состояния не получить.
const MOCK_STATES = [
  { key: 'catalog', label: 'В каталоге' },
  { key: 'missing', label: 'Нет в каталоге' },
  { key: 'low', label: 'Низкая достоверность' },
]

// Ключи читает devMock.js; пишем их здесь, чтобы App не тянул дев-модуль
const MOCK_STATE_KEY = 'sp_mock_state'
const MOCK_ROLE_KEY = 'sp_mock_role'

const MOCK_ROLES = [
  { key: 'mechanic', label: 'Механик' },
  { key: 'expert', label: 'Эксперт' },
]

function MockSwitch() {
  if (!MOCK_ENABLED) return null
  const current = localStorage.getItem(MOCK_STATE_KEY) || 'catalog'
  const role = localStorage.getItem(MOCK_ROLE_KEY) || 'mechanic'
  return (
    <div style={{ padding: 'var(--pad) var(--pad) 0' }}>
      <div className="section-label"><span>дев-стаб · состояние отчёта</span></div>
      <div className="demo-switch">
        {MOCK_STATES.map(s => (
          <button key={s.key} className={current === s.key ? 'is-active' : undefined}
            onClick={() => { localStorage.setItem(MOCK_STATE_KEY, s.key); location.reload() }}>
            {s.label}
          </button>
        ))}
      </div>

      <div className="section-label"><span>дев-стаб · роль</span></div>
      <div className="demo-switch">
        {MOCK_ROLES.map(r => (
          <button key={r.key} className={role === r.key ? 'is-active' : undefined}
            onClick={() => { localStorage.setItem(MOCK_ROLE_KEY, r.key); location.reload() }}>
            {r.label}
          </button>
        ))}
      </div>
    </div>
  )
}

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
    return (
      <main className="app-shell">
        <div className="screen-body">
          <div className="panel scan-panel">
            <div className="scan-line" />
            <div className="skeleton sk-title" />
            <div className="skeleton sk-line" style={{ width: '70%' }} />
            <div className="skeleton sk-block" />
          </div>
        </div>
      </main>
    )
  }

  // ── Вход ───────────────────────────────────────────────────────────────────
  if (!user) {
    return (
      <main className="app-shell app-shell--center">
        <form className="login" onSubmit={onSubmit}>
          <div className="login__head">
            <div className="brand-mark" aria-hidden="true"><BrandMark /></div>
            <div className="brand-name">Совфрахт<span>Детали</span></div>
          </div>

          <div className="identification-card">
            <div className="stack">
              <div className="kicker">Вход в приложение</div>

              <div className="field">
                <label htmlFor="login">Логин</label>
                <input
                  id="login"
                  value={form.login}
                  onChange={e => setForm({ ...form, login: e.target.value })}
                  autoComplete="username"
                  autoFocus
                  required
                />
              </div>

              <div className="field">
                <label htmlFor="password">Пароль</label>
                <input
                  id="password"
                  type="password"
                  value={form.password}
                  onChange={e => setForm({ ...form, password: e.target.value })}
                  autoComplete="current-password"
                  required
                />
              </div>

              {error && (
                <div className="banner banner--danger" role="alert">
                  <BannerError />
                  <div>{error}</div>
                </div>
              )}

              <button className="btn btn--primary btn--block" type="submit"
                disabled={busy || !form.login || !form.password}>
                {busy ? 'Проверяем…' : 'Войти'}
              </button>
            </div>
          </div>
        </form>
      </main>
    )
  }

  // Роль-гейт: панель эксперта — экран того же приложения, а не отдельное
  // приложение. Права всё равно проверяет сервер (NFR-SEC-03).
  const canModerate = ['expert', 'admin'].includes(user.role)

  let body
  let context
  if (screen === 'expert' && canModerate) {
    context = 'очередь модерации'
    body = <ExpertQueue onBack={() => setScreen('home')} />
  } else if (scanId) {
    context = `скан ${String(scanId).slice(0, 8)}`
    body = <Report scanId={scanId} onBack={() => setScanId('')} />
  } else if (screen === 'byid') {
    context = 'открыть по id'
    body = (
      <div className="screen-body">
        <button className="btn btn--link" onClick={() => setScreen('home')}>← К съёмке</button>
        <div className="page-head">
          <div className="kicker">Готовый скан</div>
          <h1>Открыть скан по id</h1>
          <p>Отчёт по уже обработанному скану — например, из письма или от коллеги.</p>
        </div>
        <div className="panel">
          <div className="stack">
            <div className="field">
              <label htmlFor="scan">Идентификатор скана</label>
              <input id="scan" value={scanInput} placeholder="00000000-0000-0000-0000-000000000000"
                onChange={e => setScanInput(e.target.value)} autoComplete="off" />
            </div>
            <button className="btn btn--primary btn--block" disabled={!scanInput.trim()}
              onClick={() => setScanId(scanInput.trim())}>Открыть отчёт</button>
          </div>
        </div>
      </div>
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
    <main className="app-shell">
      <AppBar
        user={user}
        context={context}
        onLogout={onLogout}
        onExpert={canModerate && screen !== 'expert' ? () => { setScanId(''); setScreen('expert') } : null}
      />
      <MockSwitch />
      {body}
    </main>
  )
}
