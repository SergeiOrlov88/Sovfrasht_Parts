// Иконки интерфейса — те же контуры, что в эталонном макете design_ref3.html.
// Инлайн-SVG, а не шрифт иконок: цвет наследуется от токенов темы, вес линии
// одинаковый, лишнего запроса за файлом нет.

/** Знак приложения в верхней панели. */
export const BrandMark = (props) => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" {...props}>
    <circle cx="10" cy="10" r="7.2" stroke="var(--acc)" strokeWidth="1.6" />
    <path d="M10 4.2v11.6M4.2 10h11.6" stroke="var(--acc2)" strokeWidth="1.2" />
    <circle cx="10" cy="10" r="2.1" fill="var(--acc)" />
  </svg>
)

// ── Иконки плашек ────────────────────────────────────────────────────────────
// Цвет задан явно, а не currentColor: плашка красит текст, а не контур иконки.

/** Всё хорошо: позиция найдена, действие выполнено */
export const BannerOk = (props) => (
  <svg className="banner-ico" viewBox="0 0 20 20" fill="none" {...props}>
    <circle cx="10" cy="10" r="8" stroke="var(--acc)" />
    <path d="M6 10.2l2.4 2.4L14 7.4" stroke="var(--acc)" strokeWidth="1.6" />
  </svg>
)

/** Ниже порога достоверности — треугольник */
export const BannerDanger = (props) => (
  <svg className="banner-ico" viewBox="0 0 20 20" fill="none" {...props}>
    <path d="M10 3l8 14H2L10 3z" stroke="var(--danger)" />
    <path d="M10 8v5M10 15.2v.6" stroke="var(--danger)" />
  </svg>
)

/** Нет в каталоге — круг с восклицанием */
export const BannerWarn = (props) => (
  <svg className="banner-ico" viewBox="0 0 20 20" fill="none" {...props}>
    <circle cx="10" cy="10" r="8" stroke="var(--warn)" />
    <path d="M10 6v5M10 13.5v.8" stroke="var(--warn)" />
  </svg>
)

/** Ошибка запроса или чтения шильдика — крест */
export const BannerError = (props) => (
  <svg className="banner-ico" viewBox="0 0 20 20" fill="none" {...props}>
    <circle cx="10" cy="10" r="8" stroke="var(--danger)" />
    <path d="M7 7l6 6M13 7l-6 6" stroke="var(--danger)" />
  </svg>
)

// ── Прочее ───────────────────────────────────────────────────────────────────

/** Пустое состояние: камера с объективом */
export const EmptyCamera = (props) => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" {...props}>
    <rect x="4" y="7" width="20" height="14" rx="3" stroke="var(--mut)" />
    <circle cx="14" cy="14" r="4" stroke="var(--acc)" />
  </svg>
)

/** Заглушка снимка */
export const IconImage = (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="8.5" cy="8.5" r="1.5" />
    <polyline points="21 15 16 10 5 21" />
  </svg>
)

/** Открыть предложение у поставщика */
export const IconExternal = (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    <polyline points="15 3 21 3 21 9" />
    <path d="M10 14 21 3" />
  </svg>
)
