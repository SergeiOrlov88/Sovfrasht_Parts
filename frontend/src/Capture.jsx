// Экран съёмки — первый шаг пользователя (A1, FR-CAP-01..04).
// Вёрстка по эталонному макету design_ref3.html: шильдик — крупный слот с
// рамкой-видоискателем, отметкой «обязательно» и кнопкой-затвором; «деталь
// целиком» и «место установки» — два компактных слота в ряд; внизу одна
// кнопка «Распознать деталь».
// Состояния экрана: пусто → кадры готовы → идёт распознавание → ошибка.
//
// Два способа получить снимок:
//   1) input[capture="environment"] — открывает камеру на телефоне и работает
//      даже по HTTP; на десктопе это обычный выбор файла;
//   2) getUserMedia — живой предпросмотр с кадрированием, но браузеры дают его
//      только в защищённом контексте (HTTPS или localhost). Если контекста нет,
//      кнопку не показываем и честно объясняем почему.
import { useEffect, useRef, useState } from 'react'
import { createScan, getScan } from './api'
import { BannerError } from './icons.jsx'

// Второстепенные кадры. Шильдик описан отдельно — он главный, по нему OCR.
const EXTRA_SLOTS = [
  { kind: 'overview', title: 'Деталь целиком', hint: 'по возможности' },
  { kind: 'context', title: 'Место установки', hint: 'контекст' },
]

// Шаги распознавания. Индекс текущего считаем от статуса скана.
const STEPS = [
  'Кадры загружены',
  'Читаем маркировку шильдика…',
  'Сверяем с каталогом закупки',
]

const stepIndex = (status) => (status === 'done' || status === 'needs_review' ? 2 : 1)

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

/** Уголки рамки-видоискателя. Четыре span — как в макете. */
const Corners = () => (
  <div className="slot-corners" aria-hidden="true">
    <span /><span /><span /><span />
  </div>
)

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
      <div className="stack">
        <div className="banner banner--danger">
          <BannerError />
          <div><b>Камера не открылась</b>{error}</div>
        </div>
        <button className="btn btn--ghost btn--block btn--sm" onClick={onClose}>Закрыть</button>
      </div>
    )
  }

  return (
    <div className="live-camera">
      <video ref={videoRef} autoPlay playsInline muted />
      <Corners />
      <div className="btn-row">
        <button className="btn btn--primary btn--sm" onClick={shoot}>Снять</button>
        <button className="btn btn--ghost btn--sm" onClick={onClose}>Отмена</button>
      </div>
    </div>
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

  const pick = (kind) => fileInputs.current[kind]?.click()

  const order = ['nameplate', ...EXTRA_SLOTS.map(s => s.kind)]
  const taken = order.filter(k => shots[k])
  const nameplate = shots.nameplate
  const busy = Boolean(scanId)
  const canSend = Boolean(nameplate) && vesselId && !busy

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

  const current = stepIndex(status)

  return (
    <div className="screen-body">
      <div className="page-head">
        <div className="kicker">Новая заявка · ЦМО</div>
        <h1>Съёмка детали</h1>
        <p>
          Сначала шильдик — по нему читаем номер. Затем деталь целиком и место,
          если есть доступ.
        </p>
      </div>

      {user.vessels?.length > 1 && (
        <div className="field">
          <label htmlFor="vessel">Судно</label>
          <select id="vessel" value={vesselId} onChange={e => setVesselId(e.target.value)}>
            {user.vessels.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>
      )}

      {/* ── Главный слот: шильдик ─────────────────────────────────────────── */}
      {liveFor === 'nameplate' ? (
        <LiveCamera onShot={f => attach('nameplate', f)} onClose={() => setLiveFor(null)} />
      ) : (
        <div className={`capture-slot capture-slot--primary${nameplate ? ' is-filled' : ''}`}>
          <Corners />
          <span className="slot-req">обязательно</span>
          <FilePicker kind="nameplate" inputs={fileInputs} onPick={attach} />

          {nameplate ? (
            <div className="slot-preview">
              <img src={nameplate.url} alt="Шильдик" />
              <button className="recapture recapture--left" onClick={() => drop('nameplate')}>
                Убрать
              </button>
              <button className="recapture" onClick={() => pick('nameplate')}>Переснять</button>
            </div>
          ) : (
            <div className="slot-empty">
              <div className="slot-title">Шильдик</div>
              <div className="slot-sub">Держите табличку в рамке. Вспышка лучше, чем тень.</div>
              <button className="shutter" type="button" onClick={() => pick('nameplate')}>
                <span className="shutter-dot" /> Сфотографировать
              </button>
              {cameraSupported() && (
                <div style={{ marginTop: 10 }}>
                  <button className="btn btn--link" onClick={() => setLiveFor('nameplate')}>
                    Камера с рамкой
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Второстепенные кадры ──────────────────────────────────────────── */}
      <div className="slot-grid">
        {EXTRA_SLOTS.map(slot => {
          const shot = shots[slot.kind]
          return (
            <div key={slot.kind}
              className={`capture-slot capture-slot--sec${shot ? ' is-filled' : ''}`}>
              <FilePicker kind={slot.kind} inputs={fileInputs} onPick={attach} />
              {shot ? (
                <div className="slot-preview">
                  <img src={shot.url} alt={slot.title} />
                  <button className="recapture recapture--left" onClick={() => drop(slot.kind)}>
                    Убрать
                  </button>
                  <button className="recapture" onClick={() => pick(slot.kind)}>Переснять</button>
                </div>
              ) : (
                <button className="slot-empty slot-empty--fill" type="button"
                  onClick={() => pick(slot.kind)}>
                  <span className="slot-title">{slot.title}</span>
                  <span className="slot-sub">{slot.hint}</span>
                </button>
              )}
            </div>
          )
        })}
      </div>

      <button className="btn btn--primary btn--block" type="button"
        disabled={!canSend} onClick={send}>
        Распознать деталь{taken.length > 1 ? ` · ${taken.length} фото` : ''}
      </button>

      {/* Отключённая кнопка обязана объяснять причину */}
      {!nameplate && !busy && (
        <p className="tiny muted">
          Нужен хотя бы снимок шильдика — без него OCR не запустится.
        </p>
      )}

      {/* ── Идёт распознавание: сканер, скелетон и шаги ───────────────────── */}
      {busy && (
        <>
          <div className="panel scan-panel">
            <div className="scan-line" />
            <div className="skeleton sk-title" />
            <div className="skeleton sk-line" style={{ width: '88%' }} />
            <div className="skeleton sk-line" style={{ width: '64%' }} />
            <div className="skeleton sk-block" />
          </div>
          <div className="progress-steps">
            {STEPS.map((label, i) => (
              <div key={label}
                className={`pstep${i < current ? ' is-done' : i === current ? ' is-run' : ''}`}>
                <span className="dot" />{label}
              </div>
            ))}
          </div>
          <p className="tiny muted">Обычно занимает несколько секунд. Отчёт откроется сам.</p>
        </>
      )}

      {error && (
        <div className="banner banner--danger">
          <BannerError />
          <div><b>Не удалось начать распознавание</b>{error}</div>
        </div>
      )}

      <p className="tiny muted">
        На телефоне кнопка откроет камеру, на компьютере — выбор файла.
        {cameraSupported()
          ? ' Живой предпросмотр с рамкой доступен.'
          : ' Живой предпросмотр с рамкой доступен по HTTPS.'}
      </p>

      <button className="btn btn--link" style={{ justifyContent: 'center' }} onClick={onOpenById}>
        Уже есть скан? Открыть по id
      </button>
    </div>
  )
}
