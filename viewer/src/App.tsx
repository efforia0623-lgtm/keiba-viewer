import { useState, useEffect, useRef } from 'react'
import type { DayData, Venue, Race } from './types'
import PredictionView from './components/PredictionView'

const PASSWORD    = 'LegacyWorld'
const AUTH_KEY    = 'efforia_auth_v1'

function PasswordGate({ onAuth }: { onAuth: () => void }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState(false)
  const [shake, setShake] = useState(false)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (value === PASSWORD) {
      onAuth()
    } else {
      setError(true)
      setShake(true)
      setValue('')
      setTimeout(() => setShake(false), 600)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#f4f6fa',
    }}>
      <div style={{
        background: '#fff', borderRadius: 12, padding: '48px 40px 40px',
        boxShadow: '0 4px 32px rgba(0,51,160,0.10)', width: '100%', maxWidth: 380,
        textAlign: 'center',
      }}>
        <div style={{
          width: 52, height: 52, borderRadius: 12,
          background: '#0033A0', color: '#fff',
          fontSize: 26, fontWeight: 700, lineHeight: '52px',
          margin: '0 auto 20px', letterSpacing: 1,
        }}>E</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: '#0a1929', marginBottom: 4 }}>
          競馬予想 Efforia
        </div>
        <div style={{ fontSize: 13, color: '#6b7a8d', marginBottom: 32 }}>
          パスワードを入力してください
        </div>
        <form onSubmit={handleSubmit} style={{ animation: shake ? 'pw-shake 0.6s' : 'none' }}>
          <input
            type="password"
            value={value}
            onChange={e => { setValue(e.target.value); setError(false) }}
            placeholder="Password"
            autoFocus
            style={{
              width: '100%', padding: '12px 14px', fontSize: 15,
              border: `1.5px solid ${error ? '#d32f2f' : '#c8d0dc'}`,
              borderRadius: 8, outline: 'none', boxSizing: 'border-box',
              marginBottom: 8, background: '#f9fafc', color: '#0a1929',
              transition: 'border-color 0.2s',
            }}
            onFocus={e => { if (!error) e.target.style.borderColor = '#0033A0' }}
            onBlur={e =>  { if (!error) e.target.style.borderColor = '#c8d0dc' }}
          />
          {error && (
            <div style={{ color: '#d32f2f', fontSize: 13, marginBottom: 8, textAlign: 'left' }}>
              パスワードが違います
            </div>
          )}
          <button
            type="submit"
            style={{
              width: '100%', padding: '12px', fontSize: 15, fontWeight: 600,
              background: '#0033A0', color: '#fff', border: 'none', borderRadius: 8,
              cursor: 'pointer', marginTop: 8, letterSpacing: 0.5,
              transition: 'background 0.2s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#002280')}
            onMouseLeave={e => (e.currentTarget.style.background = '#0033A0')}
          >
            ログイン
          </button>
        </form>
      </div>
      <style>{`
        @keyframes pw-shake {
          0%,100% { transform: translateX(0); }
          20%      { transform: translateX(-8px); }
          40%      { transform: translateX(8px); }
          60%      { transform: translateX(-6px); }
          80%      { transform: translateX(6px); }
        }
      `}</style>
    </div>
  )
}

type View = 'date' | 'venue' | 'race' | 'prediction'

const SLIDES = [
  'https://images.unsplash.com/photo-1635895901494-539a6b2647af?w=1920&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1526094633853-031707a44819?w=1920&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1495543377553-b2aba1f925d7?w=1920&auto=format&fit=crop&q=80',
]

const VENUE_PHOTOS: Record<string, string> = {
  '05': 'https://plus.unsplash.com/premium_photo-1661914240950-b0124f20a5c1?w=800&auto=format&fit=crop&q=80',
  '06': 'https://plus.unsplash.com/premium_photo-1661914240950-b0124f20a5c1?w=800&auto=format&fit=crop&q=80',
  '08': 'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?w=800&auto=format&fit=crop&q=80',
  '09': 'https://images.unsplash.com/photo-1589452271712-64b8a66c7b71?w=800&auto=format&fit=crop&q=80',
  '07': 'https://images.unsplash.com/photo-1696245206938-4913660cc260?w=800&auto=format&fit=crop&q=80',
  '01': 'https://images.unsplash.com/photo-1622607941338-38e1d2035b5a?w=800&auto=format&fit=crop&q=80',
  '02': 'https://images.unsplash.com/photo-1622607941338-38e1d2035b5a?w=800&auto=format&fit=crop&q=80',
  '03': 'https://images.unsplash.com/photo-1635562985686-4f8bb9c0d3bf?w=800&auto=format&fit=crop&q=80',
  '04': 'https://images.unsplash.com/photo-1635562985686-4f8bb9c0d3bf?w=800&auto=format&fit=crop&q=80',
  '10': 'https://images.unsplash.com/photo-1698110707910-6af9a3fd5d07?w=800&auto=format&fit=crop&q=80',
}

function getVenueImg(venueCode: string): string {
  return VENUE_PHOTOS[venueCode] ?? VENUE_PHOTOS['05']
}

function fmtDate(d: string): string {
  const y = parseInt(d.slice(0, 4), 10)
  const m = parseInt(d.slice(4, 6), 10)
  const day = parseInt(d.slice(6, 8), 10)
  const wd = ['日', '月', '火', '水', '木', '金', '土'][new Date(y, m - 1, day).getDay()]
  return `${y}年${m}月${day}日（${wd}）`
}

function useScrolled() {
  const [s, setS] = useState(false)
  useEffect(() => {
    const h = () => setS(window.scrollY > 60)
    window.addEventListener('scroll', h, { passive: true })
    return () => window.removeEventListener('scroll', h)
  }, [])
  return s
}

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

// ── Hero (slideshow) ─────────────────────────────────────────────────────────
function Hero({ onScrollDown }: { onScrollDown: () => void }) {
  const [current, setCurrent] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setCurrent(c => (c + 1) % SLIDES.length), 5000)
    return () => clearInterval(t)
  }, [])

  return (
    <section className="hero-section">
      {SLIDES.map((url, i) => (
        <div
          key={url}
          className={`hero-slide${i === current ? ' active' : ''}`}
          style={{ backgroundImage: `url(${url})` }}
        />
      ))}
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
          <div className="section-headline">
            今週の予想
            <small>開催日を選択してください</small>
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
    <div className="section-wrap-gray">
      <div className="section">
        <div ref={headRef} className="reveal">
          <div className="section-headline">
            開催競馬場
            <small>Race Venue · {fmtDate(date)}</small>
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
                <div
                  className="venue-card-bg"
                  style={{ backgroundImage: `url(${getVenueImg(v.venue_code)})` }}
                />
                <div className="venue-card-overlay" />
                <div className="venue-card-content">
                  <div className="venue-label">Racecourse</div>
                  <div className="venue-name">{v.venue_name}</div>
                  <div className="venue-sub">{v.races.length}レース開催</div>
                  {gc > 0 && <div className="venue-badge">Grade Race ×{gc}</div>}
                  <div className="venue-cta">→ レースを見る</div>
                </div>
              </div>
            )
          })}
        </div>
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

// ── Footer ────────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <div className="footer-logo">競馬予想Efforia</div>
        <p className="footer-disclaimer">予想はあくまで参考です。馬券の購入は自己責任でお願いします。</p>
        <p className="footer-copy">© 2026 競馬予想Efforia</p>
      </div>
    </footer>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [authed, setAuthed] = useState(false)

  const [view, setView]   = useState<View>('date')
  const [dates, setDates] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [selectedDate, setSelectedDate]   = useState<string | null>(null)
  const [dayData, setDayData]             = useState<DayData | null>(null)
  const [selectedVenue, setSelectedVenue] = useState<Venue | null>(null)
  const [selectedRace, setSelectedRace]   = useState<Race | null>(null)

  // すべてのフックを条件分岐より前に呼ぶ（Rules of Hooks）
  const scrolled = useScrolled()
  const headerScrolled = view !== 'date' || scrolled

  useEffect(() => {
    if (!authed) return
    fetch('/predictions/manifest.json')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<{ dates: string[] }> })
      .then(d => { setDates([...d.dates].reverse()); setLoading(false) })
      .catch((e: Error) => { setError(`データ取得に失敗しました: ${e.message}`); setLoading(false) })
  }, [authed])

  if (!authed) return <PasswordGate onAuth={() => setAuthed(true)} />

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

      <Footer />
    </>
  )
}
