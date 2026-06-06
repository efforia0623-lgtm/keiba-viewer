import { useState, useEffect } from 'react'
import type { DayData, Venue, Race } from './types'
import PredictionView from './components/PredictionView'

type View = 'date' | 'venue' | 'race' | 'prediction'

interface UnsplashPhoto {
  url: string
  name: string
  link: string
}

async function fetchHorsePhoto(): Promise<UnsplashPhoto | null> {
  const key = import.meta.env.VITE_UNSPLASH_ACCESS_KEY as string | undefined
  if (!key) return null
  try {
    const res = await fetch(
      `https://api.unsplash.com/photos/random?query=horse+racing&orientation=landscape&client_id=${key}`
    )
    if (!res.ok) return null
    const data = await res.json() as {
      urls: { regular: string }
      user: { name: string; links: { html: string } }
    }
    return {
      url: data.urls.regular,
      name: data.user.name,
      link: data.user.links.html + '?utm_source=keiba_efforia&utm_medium=referral',
    }
  } catch {
    return null
  }
}

function fmtDate(d: string): string {
  const y = parseInt(d.slice(0, 4), 10)
  const m = parseInt(d.slice(4, 6), 10)
  const day = parseInt(d.slice(6, 8), 10)
  const wd = ['日', '月', '火', '水', '木', '金', '土'][new Date(y, m - 1, day).getDay()]
  return `${y}年${m}月${day}日（${wd}）`
}

// ── 日程選択 ─────────────────────────────────────────────────────────────────
function DateSelect({ dates, onSelect }: { dates: string[]; onSelect: (d: string) => void }) {
  const [photo, setPhoto] = useState<UnsplashPhoto | null>(null)

  useEffect(() => {
    fetchHorsePhoto().then(p => { if (p) setPhoto(p) })
  }, [])

  const heroStyle = photo
    ? { backgroundImage: `linear-gradient(135deg, rgba(0,55,118,.82) 0%, rgba(0,102,204,.70) 55%, rgba(46,139,192,.65) 100%), url(${photo.url})` }
    : undefined

  if (dates.length === 0) return <div className="empty">予想データがありません</div>
  return (
    <>
      <div className="hero" style={heroStyle}>
        <div className="hero-eyebrow">AI RACING PREDICTION</div>
        <div className="hero-title">競馬予想Efforia</div>
        <div className="hero-sub">最新のAIモデルが全出走馬を分析。開催日を選んでレース予想をご確認ください。</div>
        {photo && (
          <div className="hero-photo-credit">
            Photo by{' '}
            <a href={photo.link} target="_blank" rel="noopener noreferrer">{photo.name}</a>
            {' '}on{' '}
            <a href="https://unsplash.com/?utm_source=keiba_efforia&utm_medium=referral" target="_blank" rel="noopener noreferrer">Unsplash</a>
          </div>
        )}
      </div>
      <div className="section-label">SCHEDULE</div>
      <div className="section-title">開催日程</div>
      <div className="date-grid">
        {dates.map(d => {
          const y = parseInt(d.slice(0, 4), 10)
          const m = parseInt(d.slice(4, 6), 10)
          const day = parseInt(d.slice(6, 8), 10)
          const wdIdx = new Date(y, m - 1, day).getDay()
          const wd = ['日', '月', '火', '水', '木', '金', '土'][wdIdx]
          const isSun = wdIdx === 0
          const isSat = wdIdx === 6
          const cls = `date-card${isSun ? ' weekend sunday' : isSat ? ' weekend saturday' : ''}`
          return (
            <div key={d} className={cls} onClick={() => onSelect(d)}>
              <div className="date-card-month">{y}年{m}月</div>
              <div className="date-card-day">{day}</div>
              <div className="date-card-wd">{wd}曜日</div>
            </div>
          )
        })}
      </div>
    </>
  )
}

// ── 会場選択 ─────────────────────────────────────────────────────────────────
function VenueSelect({ venues, onSelect }: { venues: DayData['venues']; onSelect: (v: Venue) => void }) {
  return (
    <>
      <div className="section-label">VENUE</div>
      <div className="section-title">競馬場を選択</div>
      <div className="cards-grid">
        {venues.map(v => {
          const gradeCount = v.races.filter(r => ['A', 'B', 'C'].includes(r.grade_code)).length
          return (
            <div key={v.venue_code} className="card" onClick={() => onSelect(v)}>
              <div className="card-icon">🏇</div>
              <div className="card-title">{v.venue_name}</div>
              <div className="card-sub">{v.races.length}レース開催</div>
              {gradeCount > 0 && <div className="card-badge">重賞 {gradeCount}R</div>}
            </div>
          )
        })}
      </div>
    </>
  )
}

// ── レース選択 ───────────────────────────────────────────────────────────────
function RaceSelect({ venue, onSelect }: { venue: Venue; onSelect: (r: Race) => void }) {
  return (
    <>
      <div className="section-label">RACE LIST</div>
      <div className="section-title">{venue.venue_name}</div>
      <div className="race-list">
        {venue.races.map(r => {
          const isGrade = ['A', 'B', 'C'].includes(r.grade_code)
          return (
            <div
              key={r.race_num}
              className={`race-item${isGrade ? ' grade' : ''}`}
              onClick={() => onSelect(r)}
            >
              <div className="race-num-badge">{r.race_num}</div>
              <div className="race-info-block">
                <div className="race-name-row">
                  {r.race_name}
                  {isGrade && <span className="grade-badge">重賞</span>}
                </div>
                <div className="race-detail-row">
                  <span className={`tag tag-${r.track_type}`}>{r.track_type}</span>
                  <span>{r.distance}m</span>
                  <span>·</span>
                  <span>{r.starters}頭立て</span>
                </div>
              </div>
              <div className="race-arrow">›</div>
            </div>
          )
        })}
      </div>
    </>
  )
}

// ── メインアプリ ─────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView]                   = useState<View>('date')
  const [dates, setDates]                 = useState<string[]>([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [selectedDate, setSelectedDate]   = useState<string | null>(null)
  const [dayData, setDayData]             = useState<DayData | null>(null)
  const [selectedVenue, setSelectedVenue] = useState<Venue | null>(null)
  const [selectedRace, setSelectedRace]   = useState<Race | null>(null)

  useEffect(() => {
    fetch('/predictions/manifest.json')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<{ dates: string[] }>
      })
      .then(data => { setDates([...data.dates].reverse()); setLoading(false) })
      .catch((e: Error) => { setError(`データ一覧の取得に失敗しました: ${e.message}`); setLoading(false) })
  }, [])

  async function selectDate(date: string) {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`/predictions/${date}.json`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json() as Record<string, unknown>
      setSelectedDate(date); setDayData(json[date] as DayData)
      setSelectedVenue(null); setSelectedRace(null); setView('venue')
    } catch (e: unknown) {
      setError(`データ読み込みに失敗しました: ${String(e)}`)
    } finally {
      setLoading(false)
    }
  }

  function goHome()  { setView('date');  setSelectedDate(null); setDayData(null); setSelectedVenue(null); setSelectedRace(null) }
  function goVenue() { setView('venue'); setSelectedVenue(null); setSelectedRace(null) }
  function goRace()  { setView('race');  setSelectedRace(null) }

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
    <div>
      <header className="header">
        <div className="header-inner">
          <div className="header-logo" onClick={goHome}>
            <div className="header-logo-mark">E</div>
            競馬予想Efforia
          </div>
          <div className="header-sub">AI予想システム</div>
        </div>
      </header>

      <div className="app">
        {bc.length > 0 && (
          <div className="breadcrumb">
            {bc.map((item, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {i > 0 && <span className="bc-sep">›</span>}
                {item.onClick
                  ? <span className="bc-link" onClick={item.onClick}>{item.label}</span>
                  : <span className="bc-current">{item.label}</span>
                }
              </span>
            ))}
          </div>
        )}

        {loading && (
          <div className="loading">
            <div className="spinner" />
            <div>読み込み中...</div>
          </div>
        )}

        {!loading && error && <div className="error-msg">{error}</div>}

        {!loading && !error && view === 'date' && (
          <DateSelect dates={dates} onSelect={selectDate} />
        )}
        {!loading && view === 'venue' && dayData && (
          <VenueSelect venues={dayData.venues} onSelect={v => { setSelectedVenue(v); setView('race') }} />
        )}
        {!loading && view === 'race' && selectedVenue && (
          <RaceSelect venue={selectedVenue} onSelect={r => { setSelectedRace(r); setView('prediction') }} />
        )}
        {view === 'prediction' && selectedRace && (
          <PredictionView race={selectedRace} />
        )}
      </div>
    </div>
  )
}
