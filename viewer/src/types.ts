export interface PastResult {
  pos: number | null
  agari: number | null
}

export interface Scores {
  ability: number      // ①能力
  bloodline: number    // ②血統
  environment: number  // ③環境
  bias: number         // ④バイアス
  keshi: number        // ⑤照合
  training: number     // ⑥調教
}

export interface Caution {
  weather: string
  track_condition: string
  track_bias: string
  pace_prediction: string
  lineup: string
}

export interface TicketItem {
  type: string
  desc: string
}

export interface TicketPatterns {
  umaren_a: TicketItem[]
  umaren_b: TicketItem[]
  sanrenpuku_a: TicketItem[]
  sanrenpuku_b: TicketItem[]
}

export interface RecMark {
  mark: string
  label: string
  horse_num: string
  horse_name: string
  prob: number
}

export interface Horse {
  model_rank: number
  horse_num: string
  gate_num: string
  horse_name: string
  jockey_name: string
  trainer_name: string
  sex: string
  horse_age: number | string
  mark: string
  prob: number
  scores: Scores
  total_score: number
  comment: string
  past_5: PastResult[]
}

export interface Race {
  race_num: string
  race_name: string
  distance: number
  track_type: string
  grade_code: string
  starters: number
  caution?: Caution
  course_description?: string
  horses: Horse[]
  recommendations: {
    marks: RecMark[]
    tickets: TicketPatterns
  }
}

export interface Venue {
  venue_code: string
  venue_name: string
  races: Race[]
}

export interface DayData {
  venues: Venue[]
}
