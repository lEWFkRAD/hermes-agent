import type { LocalCatalogModel, LocalHardware, LocalModelsStatus, LocalRuntimeJob } from '@/types/hermes'

import { hermesApi, profileScoped } from './client'

// The desktop surface of the managed llama.cpp runtime: status/catalog
// reads, download/install/activate jobs, and server control.

export function getLocalModelsStatus(): Promise<LocalModelsStatus> {
  return hermesApi<LocalModelsStatus>({
    ...profileScoped(),
    path: '/api/local-models/status'
  })
}

export function getLocalHardware(): Promise<LocalHardware> {
  return hermesApi<LocalHardware>({
    ...profileScoped(),
    path: '/api/local-models/hardware'
  })
}

export function getLocalCatalog(): Promise<{ models: LocalCatalogModel[] }> {
  return hermesApi<{ models: LocalCatalogModel[] }>({
    ...profileScoped(),
    path: '/api/local-models/catalog'
  })
}

/** Install the configured engine, or an explicit compatible build selected for a staged model. */
export function installLocalRuntime(
  backend?: string,
  tag?: string
): Promise<{ backend: string; job_id: string; tag: string }> {
  return hermesApi<{ backend: string; job_id: string; tag: string }>({
    ...profileScoped(),
    body: { backend: backend ?? null, tag: tag ?? null },
    method: 'POST',
    path: '/api/local-models/runtime/install'
  })
}

export interface QuickstartResponse {
  display_name: string
  download_bytes: number
  job_id: string
  model_id: string
  needs_download: boolean
  needs_runtime: boolean
}

export function quickstartLocalModels(modelId?: string): Promise<QuickstartResponse> {
  return hermesApi<QuickstartResponse>({
    ...profileScoped(),
    body: { model_id: modelId ?? null },
    method: 'POST',
    path: '/api/local-models/quickstart'
  })
}

export function downloadLocalModel(modelId: string): Promise<{ already_downloaded?: boolean; job_id: null | string }> {
  return hermesApi<{ already_downloaded?: boolean; job_id: null | string }>({
    ...profileScoped(),
    body: { model_id: modelId },
    method: 'POST',
    path: '/api/local-models/download'
  })
}

export function deleteLocalModel(modelId: string): Promise<{ ok: boolean }> {
  return hermesApi<{ ok: boolean }>({
    ...profileScoped(),
    method: 'DELETE',
    path: `/api/local-models/models/${encodeURIComponent(modelId)}`
  })
}

export function getLocalRuntimeJob(jobId: string): Promise<LocalRuntimeJob> {
  return hermesApi<LocalRuntimeJob>({
    ...profileScoped(),
    path: `/api/local-models/jobs/${encodeURIComponent(jobId)}`
  })
}

export function getLocalModelsJobs(): Promise<{ jobs: LocalRuntimeJob[] }> {
  return hermesApi<{ jobs: LocalRuntimeJob[] }>({
    ...profileScoped(),
    path: '/api/local-models/jobs'
  })
}

export function activateLocalModel(modelId: string): Promise<{ job_id: string }> {
  return hermesApi<{ job_id: string }>({
    ...profileScoped(),
    body: { model_id: modelId },
    method: 'POST',
    path: '/api/local-models/activate'
  })
}

export function ejectLocalModel(modelId: string): Promise<{ ok: boolean }> {
  return hermesApi<{ ok: boolean }>({
    ...profileScoped(),
    body: { model_id: modelId },
    method: 'POST',
    path: '/api/local-models/eject'
  })
}

export function setLocalServer(action: 'start' | 'stop'): Promise<{ ok: boolean }> {
  return hermesApi<{ ok: boolean }>({
    ...profileScoped(),
    body: { action },
    method: 'POST',
    path: '/api/local-models/server'
  })
}

// ── Explicit local benchmark contribution ───────────────────
// This is deliberately not telemetry state: a person runs the local test,
// reviews this closed payload, and confirms each submission themselves.

export interface LocalModelBenchmarkReport {
  schema_version: 'hermes.local_model_benchmark.v1'
  package_id: string
  created_at: string
  model: {
    family: string
    quant: string
    weights_bytes: number
    lookup_placement: 'disk_backed' | 'none' | 'resident' | 'unknown'
    lookup_table_bytes: number
  }
  runtime: {
    engine: 'llama.cpp'
    engine_tag: string
    backend: 'cpu' | 'cuda' | 'hip' | 'metal' | 'unknown' | 'vulkan'
    context_tokens: number
    slots: number
    kv_cache: 'f16' | 'q8_0' | 'unknown'
    speculation: 'auto' | 'mtp' | 'off' | 'unknown'
    ordinary_memory_spill: boolean
  }
  hardware: {
    device_memory_bytes: number
    system_memory_bytes: number
    unified_memory: boolean
  }
  benchmark: {
    request: 'short-generation-v1'
    wall_time_ms: number
    prompt_tokens: number
    completion_tokens: number
    prompt_tokens_per_second: null | number
    completion_tokens_per_second: null | number
  }
}

export function runLocalModelBenchmark(
  modelId: string
): Promise<{ report: LocalModelBenchmarkReport; submission_enabled: boolean }> {
  return hermesApi({
    ...profileScoped(),
    body: { model_id: modelId },
    method: 'POST',
    path: '/api/local-models/benchmark'
  })
}

export function submitLocalModelBenchmark(
  report: LocalModelBenchmarkReport,
  enableSubmission = false
): Promise<{ ok: boolean; package_id: string }> {
  return hermesApi({
    ...profileScoped(),
    body: { enable_submission: enableSubmission, report },
    method: 'POST',
    path: '/api/local-models/benchmark/submit'
  })
}

export function setLocalModelBenchmarkConsent(enabled: boolean): Promise<{ enabled: boolean }> {
  return hermesApi({
    ...profileScoped(),
    body: { enabled },
    method: 'POST',
    path: '/api/local-models/benchmark/consent'
  })
}

export interface LocalAdvancedLaunchRequest {
  context_tokens: number | null
  slots: number
  kv_cache: 'f16' | 'q8_0'
  mtp_draft_depth: number | null
  speculation: 'auto' | 'off' | 'mtp'
}

export interface LocalAdvancedLaunchPlan {
  aggregate_context_tokens: number
  available_bytes: number
  effective_context_tokens: number
  estimated_bytes: number
  fits: boolean
  mtp_draft_depth: number | null
  mtp_enabled: boolean
  reasons: string[]
  request: LocalAdvancedLaunchRequest
}

export function previewLocalAdvancedLaunch(modelId: string, request: LocalAdvancedLaunchRequest): Promise<LocalAdvancedLaunchPlan> {
  return hermesApi<LocalAdvancedLaunchPlan>({
    ...profileScoped(),
    body: { ...request, model_id: modelId },
    method: 'POST',
    path: '/api/local-models/advanced/plan'
  })
}

export function applyLocalAdvancedLaunch(
  modelId: string,
  request: LocalAdvancedLaunchRequest
): Promise<{ model_id: string; ok: boolean; plan: LocalAdvancedLaunchPlan; restarted: boolean }> {
  return hermesApi({
    ...profileScoped(),
    body: { ...request, model_id: modelId },
    method: 'POST',
    path: '/api/local-models/advanced/apply'
  })
}

export type LocalGatewayRouteMode = 'agent' | 'raw'

export interface LocalGatewayRoute {
  alias: string
  mode: LocalGatewayRouteMode
  model_id: string
}

export function getLocalGatewayRoutes(): Promise<{ routes: LocalGatewayRoute[] }> {
  return hermesApi({ ...profileScoped(), path: '/api/local-models/gateway-routes' })
}

export function publishLocalGatewayRoute(
  alias: string,
  modelId: string,
  mode: LocalGatewayRouteMode
): Promise<{ alias: string; mode: LocalGatewayRouteMode; ok: boolean; restart_required: boolean }> {
  return hermesApi({
    ...profileScoped(), body: { alias, mode, model_id: modelId }, method: 'POST',
    path: '/api/local-models/gateway-routes'
  })
}

export function unpublishLocalGatewayRoute(alias: string): Promise<{ alias: string; ok: boolean; restart_required: boolean }> {
  return hermesApi({
    ...profileScoped(), method: 'DELETE', path: `/api/local-models/gateway-routes/${encodeURIComponent(alias)}`
  })
}

// ── Hugging Face browser + sideload ─────────────────────────────

export interface HFSearchHit {
  repo: string
  downloads: number
  likes: number
  updated: string
  gated: boolean
}

export interface HFFileGroup {
  label: string
  paths: string[]
  /** Collision-proof ID the download job and staged model will use for this repo/path choice. */
  download_model_id?: string
  total_bytes: number
  fit: 'fits-gpu' | 'needs-ram' | 'too-big' | 'unknown'
  /** File-size-only result. Hermes inspects the completed GGUF before claiming placement. */
  fit_is_estimate?: boolean
}

export function searchHFModels(q: string, limit = 20): Promise<{ hits: HFSearchHit[] }> {
  return hermesApi<{ hits: HFSearchHit[] }>({
    ...profileScoped(),
    path: `/api/local-models/search?q=${encodeURIComponent(q)}&limit=${limit}`
  })
}

export function listHFRepoFiles(repo: string): Promise<{ files: HFFileGroup[] }> {
  return hermesApi<{ files: HFFileGroup[] }>({
    ...profileScoped(),
    path: `/api/local-models/search/files?repo=${encodeURIComponent(repo)}`
  })
}

export function downloadBrowsedModel(
  repo: string,
  paths: string[]
): Promise<{ already_downloaded?: boolean; job_id: null | string; model_id: string }> {
  return hermesApi<{ already_downloaded?: boolean; job_id: null | string; model_id: string }>({
    ...profileScoped(),
    body: { paths, repo },
    method: 'POST',
    path: '/api/local-models/download-browsed'
  })
}

export function sideloadLocalModel(
  path: string
): Promise<{ already_present?: boolean; model_id: string; ok: boolean }> {
  return hermesApi<{ already_present?: boolean; model_id: string; ok: boolean }>({
    ...profileScoped(),
    body: { path },
    method: 'POST',
    path: '/api/local-models/sideload'
  })
}
