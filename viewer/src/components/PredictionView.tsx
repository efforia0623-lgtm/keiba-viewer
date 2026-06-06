import type { Race, Horse, Scores } from '../types'
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

function scoreColor(v: number): string {
  if (v >= 8) return '#047857'
  if (v >= 5) return '#0066CC'
  return '#D97706'
}

function PosBadge({ pos }: { pos: number | null }) {
  if (pos === null) return <span className="pos-badge pos-n">-</span>
  const cls = pos === 1 ? 'pos-1' : pos === 2 ? 'pos-2' : pos === 3 ? 'pos-3' : 'pos-n'
  return <span className={`pos-badge ${cls}`}>{pos}</span>
}

function HorseRadarCard({ horse }: { horse: Horse }) {
  const isTop = horse.model_rank <= 3
  return (
    <div className={`radar-card${isTop ? ' top-horse' : ''}`}>
      <div className="radar-card-header">
        {horse.mark
          ? <span className={`radar-horse-mark mark-${horse.mark}`}>{horse.mark}</span>
          : <span className="radar-horse-mark" style={{ color: '#9CA3AF' }}>—</span>
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
              <div className="radar-axis-fill" style={{ width: `${horse.scores[k] * 10}%`, background: scoreColor(horse.scores[k]) }} />
            </div>
            <span className="radar-axis-val" style={{ color: scoreColor(horse.scores[k]) }}>{horse.scores[k]}</span>
          </div>
        ))}
      </div>

      {horse.comment && <p className="radar-comment">{horse.comment}</p>}
    </div>
  )
}

function HorseTableRow({ horse }: { horse: Horse }) {
  const isTop3 = horse.model_rank <= 3
  return (
    <tr>
      <td>
        <span style={{ fontWeight: 800, fontSize: 16, color: isTop3 ? '#0066CC' : undefined }}>
          {horse.model_rank}
        </span>
        {horse.mark && (
          <span className={`mark-${horse.mark}`} style={{ marginLeft: 6, fontWeight: 900, fontSize: 15 }}>
            {horse.mark}
          </span>
        )}
      </td>
      <td style={{ color: '#6B7280' }}>{horse.gate_num}</td>
      <td style={{ fontWeight: 700 }}>{horse.horse_num}</td>
      <td>
        <div style={{ fontWeight: 700 }}>{horse.horse_name}</div>
        <div style={{ fontSize: 11, color: '#6B7280' }}>{horse.sex}{horse.horse_age}歳</div>
      </td>
      <td style={{ fontSize: 13, color: '#6B7280', whiteSpace: 'nowrap' }}>{horse.jockey_name}</td>
      <td><span style={{ fontWeight: 800, color: '#0066CC' }}>{horse.prob}%</span></td>
      <td>
        <div className="score-wrap">
          <div className="score-bar">
            <div className="score-fill" style={{ width: `${(horse.total_score / 60) * 100}%` }} />
          </div>
          <span className="score-val">{horse.total_score}</span>
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

export default function PredictionView({ race }: Props) {
  const sorted = [...race.horses].sort((a, b) => a.model_rank - b.model_rank)
  const { marks, himo, tickets } = race.recommendations

  return (
    <div>
      {/* ── レースヘッダー ── */}
      <div className="pred-header">
        <div className="pred-header-content">
          <div className="pred-eyebrow">RACE PREDICTION · {race.race_num}R</div>
          <div className="pred-title">{race.race_name}</div>
          <div className="pred-meta">
            <span className="pred-meta-item">
              <span className={`tag tag-${race.track_type}`} style={{ marginRight: 6 }}>{race.track_type}</span>
              {race.distance}m
            </span>
            <span className="pred-meta-item">{race.starters}頭立て</span>
            {['A','B','C'].includes(race.grade_code) && (
              <span className="pred-meta-item" style={{ background: 'rgba(212,160,23,.3)', color: '#FEF3C7' }}>重賞</span>
            )}
          </div>
        </div>
      </div>

      {/* ── おすすめ馬 ＋ 買い目 ── */}
      <div className="recs-row">
        <div className="rec-box">
          <div className="rec-box-title">おすすめ馬</div>
          {marks.map(m => (
            <div key={m.horse_num} className="rec-row">
              <span className={`rec-mark mark-${m.mark}`}>{m.mark}</span>
              <span className="rec-num">{m.horse_num}番</span>
              <span className="rec-name">{m.horse_name}</span>
              <span className="rec-prob">{m.prob}%</span>
            </div>
          ))}
          {himo.length > 0 && (
            <>
              <div className="himo-label">ひも候補</div>
              {himo.map(h => (
                <div key={h.horse_num} className="rec-row">
                  <span className="rec-mark mark-△">△</span>
                  <span className="rec-num">{h.horse_num}番</span>
                  <span className="rec-name">{h.horse_name}</span>
                  <span className="rec-prob">{h.prob}%</span>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="rec-box">
          <div className="rec-box-title">推奨買い目</div>
          <div className="tickets">
            {tickets.map((t, i) => (
              <div key={i} className="ticket">
                <span className="ticket-type">{t.type}</span>
                <span className="ticket-desc">{t.desc.replace(/^\S+\s/, '')}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── レーダーチャート ── */}
      <div className="section-h">
        <span className="section-h-bar" />
        全馬レーダーチャート
      </div>
      <div className="radar-grid">
        {sorted.map(h => <HorseRadarCard key={h.horse_num} horse={h} />)}
      </div>

      {/* ── 出走馬一覧 ── */}
      <div className="section-h">
        <span className="section-h-bar" />
        出走馬一覧
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>AI順</th>
              <th>枠</th>
              <th>馬番</th>
              <th>馬名</th>
              <th>騎手</th>
              <th>AI確率</th>
              <th>評価点/60</th>
              <th>過去5走</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(h => <HorseTableRow key={h.horse_num} horse={h} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}
