import { useEffect, useRef } from 'react'
import type { Race, Horse, Scores, Caution, TicketPatterns } from '../types'
import RadarChart from './RadarChart'

interface Props { race: Race }

const SCORE_LABELS: Record<keyof Scores, string> = {
  ability:     '能力',
  bloodline:   '血統',
  environment: '環境',
  pace:        '展開',
  history:     '過去',
  training:    '調教',
}
const SCORE_KEYS = Object.keys(SCORE_LABELS) as Array<keyof Scores>

function useReveal() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current; if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { el.classList.add('in'); obs.disconnect() } },
      { threshold: 0.05, rootMargin: '0px 0px -20px 0px' }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return ref
}

function PosBadge({ pos }: { pos: number | null }) {
  if (pos === null) return <span className="pos-badge pos-n">–</span>
  const cls = pos === 1 ? 'pos-1' : pos === 2 ? 'pos-2' : pos === 3 ? 'pos-3' : 'pos-n'
  return <span className={`pos-badge ${cls}`}>{pos}</span>
}

// ── 2. 注意書きセクション ─────────────────────────────────────────────────────
function CautionSection({ caution }: { caution: Caution }) {
  const ref = useReveal()
  return (
    <div ref={ref} className="reveal caution-section">
      <div className="sub-section-label">Race Conditions · Analysis</div>
      <div className="caution-meta-row">
        <span className="caution-badge caution-weather">天候: {caution.weather}</span>
        <span className="caution-badge caution-track">馬場: {caution.track_condition}</span>
      </div>
      <div className="caution-grid">
        <div className="caution-block">
          <div className="caution-block-title">トラックバイアス想定</div>
          <p className="caution-text">{caution.track_bias}</p>
        </div>
        <div className="caution-block caution-block-wide">
          <div className="caution-block-title">展開予想</div>
          <p className="caution-text">{caution.pace_prediction}</p>
        </div>
        <div className="caution-block caution-block-lineup">
          <div className="caution-block-title">隊列図</div>
          <pre className="caution-lineup">{caution.lineup}</pre>
        </div>
      </div>
    </div>
  )
}

// ── 3. コース解説セクション ────────────────────────────────────────────────────
function CourseDesc({ description, distance }: { description: string; distance: number }) {
  const ref = useReveal()
  return (
    <div ref={ref} className="reveal course-desc-section">
      <div className="sub-section-label">Course Guide · {distance}m</div>
      <p className="course-desc-text">{description}</p>
    </div>
  )
}

// ── 4. 買い目パターン ──────────────────────────────────────────────────────────
function TicketSection({ tickets }: { tickets: TicketPatterns }) {
  const patterns = [
    { label: '馬連 パターンA', items: tickets.umaren_a },
    { label: '馬連 パターンB', items: tickets.umaren_b },
    { label: '3連複 パターンA', items: tickets.sanrenpuku_a },
    { label: '3連複 パターンB', items: tickets.sanrenpuku_b },
  ]
  return (
    <div className="ticket-patterns">
      {patterns.map(p => (
        <div key={p.label} className="ticket-pattern-group">
          <div className="ticket-pattern-label">
            {p.label}
            <span className="ticket-count">{p.items.length}点</span>
          </div>
          <div className="ticket-chips">
            {p.items.map((t, i) => (
              <span key={i} className="ticket-chip">{t.desc.replace(/^\S+\s/, '')}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── 5. レーダーカード ──────────────────────────────────────────────────────────
function HorseRadarCard({ horse, delay }: { horse: Horse; delay: number }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current; if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setTimeout(() => el.classList.add('in'), delay)
          obs.disconnect()
        }
      },
      { threshold: 0.04 }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [delay])

  return (
    <div
      ref={ref}
      className={`radar-card reveal${horse.model_rank <= 3 ? ' top-horse' : ''}`}
    >
      <div className="radar-card-header">
        {horse.mark
          ? <span className={`radar-horse-mark mark-${horse.mark}`}>{horse.mark}</span>
          : <span className="radar-horse-mark" style={{ color: '#BEBEBE' }}>—</span>
        }
        <span className="radar-horse-num">{horse.horse_num}番</span>
        <span className="radar-horse-name">{horse.horse_name}</span>
        <span className="radar-prob">{horse.prob}%</span>
      </div>

      <RadarChart scores={horse.scores} />

      <div className="radar-scores-grid">
        {SCORE_KEYS.map(k => (
          <div key={k} className="radar-axis">
            <span className="radar-axis-label">{SCORE_LABELS[k]}</span>
            <div className="radar-axis-bar">
              <div className="radar-axis-fill" style={{ width: `${horse.scores[k] * 10}%` }} />
            </div>
            <span className="radar-axis-val">{horse.scores[k]}</span>
          </div>
        ))}
      </div>

      <div className="radar-total-score">{horse.total_score}点/60点中</div>

      {horse.comment && <p className="radar-comment">{horse.comment}</p>}
    </div>
  )
}

// ── 6. 出走馬テーブル ──────────────────────────────────────────────────────────
function HorseTableRow({ horse }: { horse: Horse }) {
  const top3 = horse.model_rank <= 3
  return (
    <tr>
      <td>
        <span style={{ fontWeight: 900, fontSize: 15, color: top3 ? '#0066CC' : undefined }}>
          {horse.model_rank}
        </span>
        {horse.mark && (
          <span className={`mark-${horse.mark}`} style={{ marginLeft: 6, fontWeight: 900, fontSize: 14 }}>
            {horse.mark}
          </span>
        )}
      </td>
      <td style={{ color: '#8C8C8C' }}>{horse.gate_num}</td>
      <td style={{ fontWeight: 700 }}>{horse.horse_num}</td>
      <td>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#111' }}>{horse.horse_name}</div>
        <div style={{ fontSize: 11, color: '#8C8C8C', fontWeight: 400 }}>{horse.sex}{horse.horse_age}歳</div>
      </td>
      <td style={{ color: '#8C8C8C', fontWeight: 300 }}>{horse.jockey_name}</td>
      <td><span style={{ fontWeight: 800, color: '#0066CC' }}>{horse.prob}%</span></td>
      <td>
        <div className="score-wrap">
          <div className="score-bar">
            <div className="score-fill" style={{ width: `${(horse.total_score / 60) * 100}%` }} />
          </div>
          <span className="score-val">{horse.total_score}/60</span>
        </div>
      </td>
      <td>
        <div className="past-pos-list">
          {horse.past_5.map((p, i) => <PosBadge key={i} pos={p.pos} />)}
        </div>
      </td>
    </tr>
  )
}

// ── メイン ─────────────────────────────────────────────────────────────────────
export default function PredictionView({ race }: Props) {
  const sorted = [...race.horses].sort((a, b) => a.model_rank - b.model_rank)
  const { marks, tickets } = race.recommendations

  const recsRef  = useReveal()
  const radarRef = useReveal()
  const tableRef = useReveal()

  return (
    <div className="pred-page">

      {/* 1. レースヘッダー */}
      <div className="pred-race-header">
        <div className="pred-race-eyebrow">Race {race.race_num} · Prediction</div>
        <div className="pred-race-name">{race.race_name}</div>
        <div className="pred-race-meta">
          <span className={`tag tag-${race.track_type}`}>{race.track_type}</span>
          <span className="pred-meta-item">{race.distance}m</span>
          <span className="pred-meta-item">·</span>
          <span className="pred-meta-item">{race.starters}頭立て</span>
          {['A', 'B', 'C'].includes(race.grade_code) && (
            <span className="pred-grade-pill">重賞</span>
          )}
        </div>
      </div>

      {/* Race divider banner */}
      <div
        className="race-banner"
        style={{ backgroundImage: `url(https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1920&q=80)` }}
      >
        <div className="race-banner-overlay" />
        <div className="race-banner-text">{race.race_name}</div>
      </div>

      {/* 2. 注意書き（天候・馬場・バイアス・展開・隊列） */}
      {race.caution && <CautionSection caution={race.caution} />}

      {/* 3. コース・距離解説 */}
      {race.course_description && (
        <CourseDesc description={race.course_description} distance={race.distance} />
      )}

      {/* 4. おすすめ馬（◎○▲△×4）＋買い目 */}
      <div ref={recsRef} className="recs-section reveal">
        <div>
          <div className="rec-panel-label">Recommended Horses · ◎○▲△×4</div>
          {marks.map(m => (
            <div key={m.horse_num} className="rec-row">
              <span className={`rec-mark mark-${m.mark}`}>{m.mark}</span>
              <span className="rec-num">{m.horse_num}番</span>
              <span className="rec-name">{m.horse_name}</span>
              <span className="rec-label">{m.label}</span>
              <span className="rec-prob">{m.prob}%</span>
            </div>
          ))}
        </div>
        <div>
          <div className="rec-panel-label">Recommended Tickets</div>
          {tickets && <TicketSection tickets={tickets} />}
        </div>
      </div>

      {/* 5. 全馬レーダーチャート＋解説文 */}
      <div ref={radarRef} className="reveal">
        <div className="sub-section-label">Radar Analysis · All Horses</div>
        <div className="radar-grid">
          {sorted.map((h, i) => (
            <HorseRadarCard key={h.horse_num} horse={h} delay={i * 45} />
          ))}
        </div>
      </div>

      {/* 6. 出走馬一覧テーブル */}
      <div ref={tableRef} className="reveal">
        <div className="sub-section-label">All Runners · Overview</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>AI Rank</th>
                <th>枠</th>
                <th>馬番</th>
                <th>馬名</th>
                <th>騎手</th>
                <th>確率</th>
                <th>評価</th>
                <th>過去5走</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(h => <HorseTableRow key={h.horse_num} horse={h} />)}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  )
}
