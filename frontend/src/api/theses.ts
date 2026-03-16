import { ApiClient } from './request'

export interface ThesisItem {
  _id: string
  symbol: string
  symbol_name?: string
  market?: string
  status: string
  thesis_title?: string
  thesis_summary?: string
  thesis_health?: string
  health_score?: number
  watch_reason?: string | null
  signal_confidence?: number | null
  target_price?: number | null
  stop_loss?: number | null
  min_hold_days?: number | null
  updated_at?: string
  core_assumptions?: ThesisAssumption[]
  latest_verdict?: Record<string, any> | null
  latest_exit_decision?: Record<string, any> | null
}

export interface ThesisAssumption {
  id: string
  statement: string
  signal_tags?: string[]
  status?: string
  health_score?: number
  last_checked?: string | null
  weakening_evidence?: string | null
  history?: Array<Record<string, any>>
}

export interface ThesisVersionItem {
  _id: string
  version: number
  change_description: string
  health_delta?: number | null
  triggered_by?: string
  created_at?: string
}

export interface DebateRecordItem {
  _id: string
  thesis_id?: string | null
  symbol: string
  workflow_mode?: string
  bull_case?: string[]
  bear_case?: string[]
  debate_verdict?: Record<string, any>
  signal_bundle?: Record<string, any>
  exit_decision?: Record<string, any>
  macro_assessment?: Record<string, any>
  sector_rotation?: Record<string, any>
  created_at?: string
}

export interface ThesisOverview {
  active_count: number
  watchlist_count: number
  closed_count: number
  broken_count: number
  weakest_symbol?: string | null
  weakest_health?: number | null
  items: ThesisItem[]
}

export interface EdgeProfile {
  _id?: string
  generated_at?: string
  total_closed_trades?: number
  decision_type_analysis?: Array<Record<string, any>>
  key_findings?: string[]
  recommendations?: Array<Record<string, any>>
  signal_weight_config?: Record<string, number>
}

export interface CognitiveSnapshot {
  _id?: string
  generated_at?: string
  strengths?: string[]
  blind_spots?: string[]
  improvement_vs_last?: string[]
  maturity_dimensions?: Record<string, number>
}

export interface TradeImportPreview {
  columns: string[]
  rows: Array<Record<string, any>>
  sample_rows: Array<Record<string, any>>
  detected_symbol_field?: string | null
  detected_side_field?: string | null
  row_count: number
}

export const thesesApi = {
  list(params?: { status?: string; symbol?: string }) {
    return ApiClient.get<ThesisItem[]>('/api/theses/', params)
  },
  overview() {
    return ApiClient.get<ThesisOverview>('/api/theses/overview')
  },
  get(thesisId: string) {
    return ApiClient.get<ThesisItem>(`/api/theses/${thesisId}`)
  },
  create(payload: Record<string, any>) {
    return ApiClient.post<ThesisItem>('/api/theses/', payload)
  },
  update(thesisId: string, payload: Record<string, any>) {
    return ApiClient.put<ThesisItem>(`/api/theses/${thesisId}`, payload)
  },
  activate(thesisId: string, payload?: { position_id?: string }) {
    return ApiClient.post<ThesisItem>(`/api/theses/${thesisId}/activate`, payload || {})
  },
  close(thesisId: string, payload: { reason: string; close_position?: boolean }) {
    return ApiClient.post<ThesisItem>(`/api/theses/${thesisId}/close`, payload)
  },
  versions(thesisId: string) {
    return ApiClient.get<ThesisVersionItem[]>(`/api/theses/${thesisId}/versions`)
  },
  debates(thesisId: string, limit = 10) {
    return ApiClient.get<DebateRecordItem[]>(`/api/theses/${thesisId}/debates`, { limit })
  },
  active(symbol: string) {
    return ApiClient.get<ThesisItem>(`/api/theses/active/${symbol}`)
  },
  listEdgeProfiles() {
    return ApiClient.get<EdgeProfile[]>('/api/edge-profiles/')
  },
  generateEdgeProfile() {
    return ApiClient.post<EdgeProfile>('/api/edge-profiles/generate')
  },
  listCognitiveSnapshots() {
    return ApiClient.get<CognitiveSnapshot[]>('/api/cognitive-snapshots/')
  },
  generateCognitiveSnapshot() {
    return ApiClient.post<CognitiveSnapshot>('/api/cognitive-snapshots/generate')
  },
  previewTradeImport(file: File) {
    return ApiClient.upload<TradeImportPreview>('/api/imports/trades/preview', file)
  },
  commitTradeImport(rows: Array<Record<string, any>>, source = 'csv_import') {
    return ApiClient.post<{ inserted_count: number }>('/api/imports/trades/commit', { rows, source })
  }
}
