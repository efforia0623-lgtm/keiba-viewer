import type { Scores } from '../types'

interface Props { scores: Scores }

const AXES: { key: keyof Scores; label: string }[] = [
  { key: 'ability',     label: '①能力' },
  { key: 'bloodline',   label: '②血統' },
  { key: 'environment', label: '③環境' },
  { key: 'bias',        label: '④バイアス' },
  { key: 'keshi',       label: '⑤照合' },
  { key: 'training',    label: '⑥調教' },
]

const N  = 6
const CX = 130
const CY = 130
const R  = 82
const LR = 112

function toRad(deg: number) { return (deg * Math.PI) / 180 }
function axisPoint(i: number, scale: number): [number, number] {
  const a = toRad(i * 60 - 90)
  return [CX + R * scale * Math.cos(a), CY + R * scale * Math.sin(a)]
}
function dataPoint(i: number, val: number): [number, number] {
  const a = toRad(i * 60 - 90)
  const r = R * (val / 10)
  return [CX + r * Math.cos(a), CY + r * Math.sin(a)]
}
function labelPoint(i: number): [number, number] {
  const a = toRad(i * 60 - 90)
  return [CX + LR * Math.cos(a), CY + LR * Math.sin(a)]
}

export default function RadarChart({ scores }: Props) {
  const rings = [0.25, 0.5, 0.75, 1.0]
  const ringPolygons = rings.map(s =>
    Array.from({ length: N }, (_, i) => axisPoint(i, s).join(',')).join(' ')
  )
  const dataPts = AXES.map((a, i) => dataPoint(i, scores[a.key]))
  const polyPts = dataPts.map(([x, y]) => `${x},${y}`).join(' ')

  return (
    <svg
      viewBox="0 0 260 260"
      width="100%"
      style={{ maxWidth: 260, display: 'block', margin: '0 auto' }}
      aria-hidden="true"
    >
      {ringPolygons.map((pts, i) => (
        <polygon
          key={i} points={pts} fill="none"
          stroke={i === rings.length - 1 ? '#D1D5DB' : '#EAECEF'}
          strokeWidth={i === rings.length - 1 ? 1.5 : 0.8}
        />
      ))}

      {Array.from({ length: N }, (_, i) => {
        const [ox, oy] = axisPoint(i, 1)
        return <line key={i} x1={CX} y1={CY} x2={ox} y2={oy} stroke="#EAECEF" strokeWidth={0.8} />
      })}

      <polygon
        points={polyPts}
        fill="rgba(0,102,204,.15)"
        stroke="#0066CC"
        strokeWidth={2}
        strokeLinejoin="round"
      />

      {dataPts.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={3.5} fill="#0066CC" />
      ))}

      {AXES.map((a, i) => {
        const [lx, ly] = labelPoint(i)
        const anchor = lx < CX - 10 ? 'end' : lx > CX + 10 ? 'start' : 'middle'
        return (
          <text
            key={i} x={lx} y={ly}
            textAnchor={anchor} dominantBaseline="middle"
            fontSize={12} fontWeight="700" fill="#4B5563"
          >
            {a.label}
          </text>
        )
      })}
    </svg>
  )
}
