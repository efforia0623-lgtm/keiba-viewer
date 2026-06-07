import { useState, useEffect, useRef } from 'react'
import type { DayData, Venue, Race } from './types'
import PredictionView from './components/PredictionView'

type View = 'date' | 'venue' | 'race' | 'prediction'

const HERO_PHOTO_URL = 'https://images.unsplash.com/flagged/photo-1569319388901-605a6d2d1299?w=1920&q=80'

function fmtDate(d: string): string {
  const y = parseInt(d.slice(0, 4), 10)
  const m = parseInt(d.slice(4, 6), 10)
  const day = parseInt(d.slice(6, 8), 10)
  const wd = ['日', '月', '火', '水', '木', '金', '土'][new Date(y, m - 1, day).getDay()]
  return `${y}年${m}月${day}日（${wd}）`
}

// Transparent → white header on scroll
function useScrolled() {
  const [s, setS] = useState(false)
  useEffect(() => {
    const h = () => setS(window.scrollY > 60)
    window.addEventListener('scroll', h, { passive: true })
    return () => window.removeEventListener('scroll', h)
  }, [])
  return s
}

// Single-element reveal
function useReveal() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current; if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { el.classList.add('in'); obs.disconnect() } },
      { threshold: 0.08, rootMargin: '0px 0px -20px 0px' }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return ref
}

// Stagger-reveal children when container enters viewport
function useStagger(len: number) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const container = ref.current; if (!container) return
    const kids = Array.from(container.children) as HTMLElement[]
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          kids.forEach((k, i) => setTimeout(() => k.classList.add('in'), i * 55))
          obs.disconnect()
        }
      },
      { threshold: 0.04, rootMargin: '0px 0px -20px 0px' }
    )
    obs.observe(container)
    return () => obs.disconnect()
  }, [len])
  return ref
}

// ── Hero ─────────────────────────────────────────────────────────────────────
function Hero({ onScrollDown }: { onScrollDown: () => void }) {
  return (
    <section className="hero-section">
      <div
        className="hero-bg"
        style={{ backgroundImage: `url(${HERO_PHOTO_URL})` }}
      />
      <div className="hero-overlay" />

      <div className="hero-content">
        <div className="hero-eyebrow">AI Racing Prediction</div>
        <h1 className="hero-title">競馬予想<br />Efforia</h1>
        <p className="hero-subtitle">開催日程を選択してください</p>
      </div>

      <div className="hero-scroll" onClick={onScrollDown}>
        <span>Scroll</span>
        <div className="hero-chevron" />
      </div>

      <div className="hero-credit">
        Photo from{' '}
        <a href="https://unsplash.com/" target="_blank" rel="noopener noreferrer">
          Unsplash
        </a>
      </div>
    </section>
  )
}

// ── 日程選択 ──────────────────────────────────────────────────────────────────
function DateSection({
  dates,
  onSelect,
}: {
  dates: string[]
  onSelect: (d: string) => void
}) {
  const scheduleRef = useRef<HTMLDivElement>(null)
  const headRef     = useReveal()
  const gridRef     = useStagger(dates.length)

  const scrollDown = () =>
    scheduleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  if (dates.length === 0)
    return <div className="empty-msg">予想データがありません</div>

  return (
    <>
      <Hero onScrollDown={scrollDown} />

      <div ref={scheduleRef} className="section">
        <div ref={headRef} className="reveal">
          <div className="section-eyebrow">Schedule</div>
          <div className="section-headline">
            開催日程
            <small>Select a race date</small>
          </div>
        </div>

        <div ref={gridRef} className="date-grid">
          {dates.map(d => {
            const y    = parseInt(d.slice(0, 4), 10)
            const m    = parseInt(d.slice(4, 6), 10)
            const day  = parseInt(d.slice(6, 8), 10)
            const wdi  = new Date(y, m - 1, day).getDay()
            const wd   = ['日', '月', '火', '水', '木', '金', '土'][wdi]
            const cls  = `date-card reveal${wdi === 0 ? ' sunday' : wdi === 6 ? ' saturday' : ''}`
            return (
              <div key={d} className={cls} onClick={() => onSelect(d)}>
                <div className="date-card-mo">{y}.{String(m).padStart(2, '0')}</div>
                <div className="date-card-day">{day}</div>
                <div className="date-card-wd">{wd}</div>
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}

// ── 会場選択 ──────────────────────────────────────────────────────────────────
function VenueSection({
  date,
  venues,
  onSelect,
}: {
  date: string
  venues: DayData['venues']
  onSelect: (v: Venue) => void
}) {
  const headRef = useReveal()
  const gridRef = useStagger(venues.length)

  return (
    <div className="section">
      <div ref={headRef} className="reveal">
        <div className="section-eyebrow">Venue</div>
        <div className="section-headline">
          競馬場を選択
          <small>{fmtDate(date)}</small>
        </div>
      </div>

      <div ref={gridRef} className="venue-grid">
        {venues.map(v => {
          const gc = v.races.filter(r => ['A', 'B', 'C'].includes(r.grade_code)).length
          return (
            <div
              key={v.venue_code}
              className="venue-card reveal"
              onClick={() => onSelect(v)}
            >
              <div className="venue-label">Racecourse</div>
              <div className="venue-name">{v.venue_name}</div>
              <div className="venue-sub">{v.races.length}レース開催</div>
              {gc > 0 && <div className="venue-badge">Grade Race ×{gc}</div>}
              <div className="venue-cta">→ レースを見る</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── レース選択 ────────────────────────────────────────────────────────────────
function RaceSection({
  venue,
  onSelect,
}: {
  venue: Venue
  onSelect: (r: Race) => void
}) {
  const headRef = useReveal()
  const listRef = useStagger(venue.races.length)

  return (
    <div className="section">
      <div ref={headRef} className="reveal">
        <div className="section-eyebrow">Race List</div>
        <div className="section-headline">
          {venue.venue_name}
          <small>{venue.races.length} races</small>
        </div>
      </div>

      <div ref={listRef} className="race-list">
        {venue.races.map(r => {
          const isGrade = ['A', 'B', 'C'].includes(r.grade_code)
          return (
            <div
              key={r.race_num}
              className={`race-item reveal${isGrade ? ' grade' : ''}`}
              onClick={() => onSelect(r)}
            >
              <div className="race-num">{r.race_num}</div>
              <div className="race-info">
                <div className="race-name-row">
                  {r.race_name}
                  {isGrade && <span className="race-grade-pill">重賞</span>}
                </div>
                <div className="race-detail-row">
                  <span className={`tag tag-${r.track_type}`}>{r.track_type}</span>
                  <span>{r.distance}m</span>
                  <span>·</span>
                  <span>{r.starters}頭立て</span>
                </div>
              </div>
              <div className="race-cta">→ 予想を見る</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView]   = useState<View>('date')
  const [dates, setDates] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [selectedDate, setSelectedDate]   = useState<string | null>(null)
  const [dayData, setDayData]             = useState<DayData | null>(null)
  const [selectedVenue, setSelectedVenue] = useState<Venue | null>(null)
  const [selectedRace, setSelectedRace]   = useState<Race | null>(null)

  const scrolled = useScrolled()
  // Header is always opaque outside of the date hero
  const headerScrolled = view !== 'date' || scrolled

  useEffect(() => {
    fetch('/predictions/manifest.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<{ dates: string[] }> })
      .then(d => { setDates([...d.dates].reverse()); setLoading(false) })
      .catch((e: Error) => { setError(`データ取得に失敗しました: ${e.message}`); setLoading(false) })
  }, [])

  async function selectDate(date: string) {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`/predictions/${date}.json`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json() as Record<string, unknown>
      setSelectedDate(date)
      setDayData(json[date] as DayData)
      setSelectedVenue(null); setSelectedRace(null)
      setView('venue')
      window.scrollTo({ top: 0 })
    } catch (e: unknown) {
      setError(`データ読み込みに失敗しました: ${String(e)}`)
    } finally {
      setLoading(false)
    }
  }

  function goHome() {
    setView('date'); setSelectedDate(null); setDayData(null)
    setSelectedVenue(null); setSelectedRace(null)
    window.scrollTo({ top: 0 })
  }
  function goVenue() {
    setView('venue'); setSelectedVenue(null); setSelectedRace(null)
    window.scrollTo({ top: 0 })
  }
  function goRace() {
    setView('race'); setSelectedRace(null)
    window.scrollTo({ top: 0 })
  }

  type BcItem = { label: string; onClick?: () => void }
  const bc: BcItem[] = []
  if (view !== 'date') {
    bc.push({ label: '競馬予想Efforia', onClick: goHome })
    if (selectedDate)
      bc.push({ label: fmtDate(selectedDate), onClick: view !== 'venue' ? goVenue : undefined })
    if (selectedVenue && (view === 'race' || view === 'prediction'))
      bc.push({ label: selectedVenue.venue_name, onClick: view === 'prediction' ? goRace : undefined })
    if (selectedRace && view === 'prediction')
      bc.push({ label: `${selectedRace.race_num}R ${selectedRace.race_name}` })
  }

  return (
    <>
      <header className={`header${headerScrolled ? ' scrolled' : ''}`}>
        <div className="header-inner">
          <div className="header-logo" onClick={goHome}>
            <div className="header-logo-mark">E</div>
            競馬予想Efforia
          </div>
          <div className="header-tag">AI Prediction</div>
        </div>
      </header>

      {bc.length > 0 && (
        <div className="bc-bar">
          <div className="bc-inner">
            {bc.map((item, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'center' }}>
                {i > 0 && <span className="bc-sep">›</span>}
                {item.onClick
                  ? <span className="bc-link" onClick={item.onClick}>{item.label}</span>
                  : <span className="bc-current">{item.label}</span>
                }
              </span>
            ))}
          </div>
        </div>
      )}

      <main>
        {loading && (
          <div className="page-loading" style={{ marginTop: bc.length > 0 ? 0 : 72 }}>
            <div className="spinner" />
            <span>読み込み中...</span>
          </div>
        )}

        {!loading && error && (
          <div className="error-box" style={{ marginTop: bc.length > 0 ? 0 : 100 }}>{error}</div>
        )}

        {!loading && !error && view === 'date' && (
          <DateSection dates={dates} onSelect={selectDate} />
        )}
        {!loading && !error && view === 'venue' && dayData && selectedDate && (
          <VenueSection
            date={selectedDate}
            venues={dayData.venues}
            onSelect={v => { setSelectedVenue(v); setView('race'); window.scrollTo({ top: 0 }) }}
          />
        )}
        {!loading && !error && view === 'race' && selectedVenue && (
          <RaceSection
            venue={selectedVenue}
            onSelect={r => { setSelectedRace(r); setView('prediction'); window.scrollTo({ top: 0 }) }}
          />
        )}
        {view === 'prediction' && selectedRace && (
          <PredictionView race={selectedRace} />
        )}
      </main>
    </>
  )
}
