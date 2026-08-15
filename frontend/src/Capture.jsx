// Экран съёмки — первый шаг пользователя (A1, FR-CAP-01..04).
// Вёрстка по целевому макету capture_screen_target.html: шильдик — крупный
// главный слот с видоискателем, «деталь целиком» и «место установки» —
// компактные второстепенные слоты в ряд, внизу одна заметная кнопка.
//
// Два способа получить снимок:
//   1) input[capture="environment"] — открывает камеру на телефоне и работает
//      даже по HTTP; на десктопе это обычный выбор файла;
//   2) getUserMedia — живой предпросмотр с кадрированием, но браузеры дают его
//      только в защищённом контексте (HTTPS или localhost). Если контекста нет,
//      кнопку не показываем и честно объясняем почему.
import { useEffect, useRef, useState } from 'react'
import { createScan, getScan } from './api'

// Второстепенные кадры. Шильдик описан отдельно — он главный, по нему OCR.
const EXTRA_SLOTS = [
  { kind: 'overview', title: 'Деталь целиком', hint: 'Помогает определить тип', icon: '⚙️' },
  { kind: 'context', title: 'Место установки', hint: 'Необязательно', icon: '📍' },
]

const STAGES = [
  { key: 'upload', label: 'Загрузка фото' },
  { key: 'queued', label: 'Принято в обработку' },
  { key: 'processing', label: 'Распознавание: OCR шильдика' },
  { key: 'done', label: 'Сопоставление с каталогом' },
]

const cameraSupported = () =>
  typeof navigator !== 'undefined' &&
  navigator.mediaDevices &&
  typeof navigator.mediaDevices.getUserMedia === 'function' &&
  window.isSecureContext

function uuid() {
  if (crypto?.randomUUID) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

/** Скрытый input: на телефоне открывает камеру, на десктопе — выбор файла.
 *  Объявлен на уровне модуля, а не внутри Capture: иначе React пересоздавал бы
 *  тип компонента на каждом рендере, перемонтировал input и терял бы выбранный
 *  файл, если перерисовка случится при открытом системном диалоге. */
function FilePicker({ kind, inputs, onPick }) {
  return (
    <input
      ref={el => (inputs.current[kind] = el)}
      type="file"
      accept="image/*"
      capture="environment"
      hidden
      onChange={e => onPick(kind, e.target.files?.[0])}
    />
  )
}

/** Живой предпросмотр камеры прямо в рамке видоискателя. */
function LiveCamera({ onShot, onClose }) {
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    navigator.mediaDevices
      // facingMode: environment — задняя камера на телефоне
      .getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1600 } } })
      .then(stream => {
        if (cancelled) {
          stream.getTracks().forEach(t => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
      })
      .catch(e => setError(
        e.name === 'NotAllowedError'
          ? 'Доступ к камере запрещён. Разрешите его в настройках браузера или загрузите файл.'
          : `Камера недоступна: ${e.message}`))
    return () => {
      cancelled = true
      streamRef.current?.getTracks().forEach(t => t.stop())
    }
  }, [])

  function shoot() {
    const video = videoRef.current
    if (!video || !video.videoWidth) return
    // Сжимаем до 2000 px по длинной стороне (NFR-PERF-03): читаемость маркировки
    // сохраняется, а объём и стоимость распознавания падают
    const scale = Math.min(1, 2000 / Math.max(video.videoWidth, video.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(video.videoWidth * scale)
    canvas.height = Math.round(video.videoHeight * scale)
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(blob => blob && onShot(new File([blob], 'shot.jpg', { type: 'image/jpeg' })),
                  'image/jpeg', 0.85)
  }

  if (error) {
    return (
      <>
        <p className="error">{error}</p>
        <button className="btn ghost" onClick={onClose}>Закрыть</button>
      </>
    )
  }

  return (
    <>
      <div className="vf live">
        <video ref={videoRef} autoPlay playsInline muted />
        <div className="corner tl" /><div className="corner tr" />
        <div className="corner bl" /><div className="corner br" />
      </div>
      <div className="btnrow">
        <button className="btn" onClick={shoot}>Снять</button>
        <button className="btn ghost" onClick={onClose}>Отмена</button>
      </div>
    </>
  )
}

export default function Capture({ user, onReady, onOpenById }) {
  const [shots, setShots] = useState({})        // kind -> {file, url}
  const [liveFor, setLiveFor] = useState(null)  // для какого слота открыт предпросмотр
  const [vesselId, setVesselId] = useState(user.vessels?.[0]?.id || '')
  const [error, setError] = useState('')
  const [scanId, setScanId] = useState(null)
  const [status, setStatus] = useState(null)
  const fileInputs = useRef({})

  // Освобождаем object-URL превью, чтобы не течь памятью
  useEffect(() => () => Object.values(shots).forEach(s => URL.revokeObjectURL(s.url)), [])

  function attach(kind, file) {
    if (!file) return
    setShots(prev => {
      if (prev[kind]) URL.revokeObjectURL(prev[kind].url)
      return { ...prev, [kind]: { file, url: URL.createObjectURL(file) } }
    })
    setLiveFor(null)
    setError('')
  }

  function drop(kind) {
    setShots(prev => {
      if (prev[kind]) URL.revokeObjectURL(prev[kind].url)
      const next = { ...prev }
      delete next[kind]
      return next
    })
  }

  const order = ['nameplate', ...EXTRA_SLOTS.map(s => s.kind)]
  const taken = order.filter(k => shots[k])
  const nameplate = shots.nameplate
  const canSend = Boolean(nameplate) && vesselId && !scanId

  async function send() {
    setError('')
    const form = new FormData()
    taken.forEach(k => form.append('photos', shots[k].file, `${k}.jpg`))
    form.append('kinds', taken.join(','))
    form.append('meta', JSON.stringify({
      vessel_id: vesselId,
      // Ключ идемпотентности: повторная отправка не создаст второй скан
      client_scan_id: uuid(),
    }))
    try {
      const res = await createScan(form)
      setScanId(res.scan_id)
      setStatus(res.status)
    } catch (e) {
      setError(e.message)
    }
  }

  // Поллинг статуса: как только скан обработан — уходим в отчёт
  useEffect(() => {
    if (!scanId) return
    let stop = false
    const tick = async () => {
      try {
        const s = await getScan(scanId)
        if (stop) return
        setStatus(s.status)
        if (['done', 'needs_review', 'error'].includes(s.status)) {
          onReady(scanId)
          return
        }
      } catch (e) {
        if (!stop) setError(e.message)
      }
      if (!stop) setTimeout(tick, 1500)
    }
    tick()
    return () => { stop = true }
  }, [scanId])

  // ── Экран прогресса ────────────────────────────────────────────────────────
  if (scanId) {
    const current = status === 'queued' ? 1 : status === 'processing' ? 2 : 3
    return (
      <section className="report">
        <h1>Распознаём деталь</h1>
        <p className="lead">Обычно занимает несколько секунд. Отчёт откроется сам.</p>
        <div className="card">
          <ol className="stages">
            {STAGES.map((st, i) => (
              <li key={st.key} className={i < current ? 'done' : i === current ? 'active' : ''}>
                <span className="dot" />
                {st.label}
              </li>
            ))}
          </ol>
          {error && <p className="error">{error}</p>}
        </div>
      </section>
    )
  }

  // ── Экран съёмки ───────────────────────────────────────────────────────────
  return (
    <section className="report">
      <h1>Новый скан детали</h1>
      <p className="lead">
        Сфотографируйте деталь — система определит её и подберёт варианты закупки и ремонта.
      </p>

      {user.vessels?.length > 1 && (
        <div className="card">
          <label htmlFor="vessel">Судно</label>
          <select id="vessel" value={vesselId} onChange={e => setVesselId(e.target.value)}>
            {user.vessels.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>
      )}

      {/* Главный слот: шильдик. Крупный, с рамкой-видоискателем */}
      <div className="hero">
        <span className="req">обязательно</span>
        <h3>📛 Шильдик</h3>
        <p>Главный кадр. Снимите табличку с номером крупно, чтобы буквы читались.</p>

        {liveFor === 'nameplate' ? (
          <LiveCamera onShot={f => attach('nameplate', f)} onClose={() => setLiveFor(null)} />
        ) : (
          <>
            <div className={`vf${nameplate ? ' shot' : ''}`}>
              {nameplate ? (
                <img src={nameplate.url} alt="Шильдик" />
              ) : (
                <div className="ico">🔎</div>
              )}
              <div className="corner tl" /><div className="corner tr" />
              <div className="corner bl" /><div className="corner br" />
            </div>

            <FilePicker kind="nameplate" inputs={fileInputs} onPick={attach} />
            <button className="btn" onClick={() => fileInputs.current.nameplate?.click()}>
              📷 {nameplate ? 'Переснять шильдик' : 'Сфотографировать шильдик'}
            </button>

            <div className="btnrow" style={{ marginTop: 10 }}>
              {cameraSupported() && (
                <button className="btn ghost small" onClick={() => setLiveFor('nameplate')}>
                  Камера с рамкой
                </button>
              )}
              {nameplate && (
                <button className="btn ghost small" onClick={() => drop('nameplate')}>
                  Убрать кадр
                </button>
              )}
            </div>
          </>
        )}
      </div>

      {/* Второстепенные кадры — компактно, в один ряд */}
      <div className="row2">
        {EXTRA_SLOTS.map(slot => {
          const shot = shots[slot.kind]
          return (
            <div className="slot" key={slot.kind}>
              <div className="ph">
                {shot ? <img src={shot.url} alt={slot.title} /> : slot.icon}
              </div>
              <h4>{slot.title}</h4>
              <small>{slot.hint}</small>
              <FilePicker kind={slot.kind} inputs={fileInputs} onPick={attach} />
              {shot ? (
                <button className="add drop" onClick={() => drop(slot.kind)}>× убрать</button>
              ) : (
                <button className="add" onClick={() => fileInputs.current[slot.kind]?.click()}>
                  ＋ добавить
                </button>
              )}
            </div>
          )
        })}
      </div>

      {error && <p className="error">{error}</p>}

      <button className={`btn cta${canSend ? '' : ' disabled'}`} disabled={!canSend} onClick={send}>
        {nameplate ? `Распознать деталь${taken.length > 1 ? ` · ${taken.length} фото` : ''}`
                   : 'Сначала снимите шильдик'}
      </button>

      <div className="hint">
        На телефоне кнопка откроет камеру, на компьютере — выбор файла.
        {cameraSupported()
          ? ' Живой предпросмотр с рамкой доступен.'
          : ' Живой предпросмотр с рамкой доступен по HTTPS.'}
      </div>

      <button className="byid" onClick={onOpenById}>
        Уже есть скан? <u>Открыть по id</u>
      </button>
    </section>
  )
}
