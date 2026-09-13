import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  type LocalModelBenchmarkReport,
  runLocalModelBenchmark,
  setLocalModelBenchmarkConsent,
  submitLocalModelBenchmark
} from '@/hermes'
import { useI18n } from '@/i18n'
import { BarChart3, Send, StopFilled } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'
import type { LocalModelsStatus } from '@/types/hermes'

import { ListRow, Pill, SettingsSection } from './primitives'

interface LocalModelBenchmarkSubmissionProps {
  status: LocalModelsStatus
}

type LocalModelsCopy = ReturnType<typeof useI18n>['t']['settings']['localModels']

function gibibytes(bytes: number, copy: LocalModelsCopy): string {
  return copy.benchmarkMemory(bytes / (1 << 30))
}

function rate(value: null | number, copy: LocalModelsCopy): string {
  return value === null ? copy.benchmarkUnavailable : copy.benchmarkRate(value)
}

function contextLabel(tokens: number, copy: LocalModelsCopy): string {
  return tokens > 0 ? copy.benchmarkContext(tokens) : copy.benchmarkUnavailable
}

function lookupLabel(report: LocalModelBenchmarkReport, copy: LocalModelsCopy): string {
  switch (report.model.lookup_placement) {
    case 'disk_backed':
      return copy.placementDiskBacked

    case 'resident':
      return copy.lookupResident

    case 'none':
      return copy.benchmarkNoLookup

    default:
      return copy.lookupUnknown
  }
}

/**
 * A deliberately local-first, post-install contribution flow.  It only renders
 * for an active staged model; no report is created, retained, or sent until the
 * person explicitly runs the test.
 */
export function LocalModelBenchmarkSubmission({ status }: LocalModelBenchmarkSubmissionProps) {
  const { t } = useI18n()
  const copy = t.settings.localModels
  const activeModelId = status.active_model_id
  const installedActiveModel = activeModelId && status.models.some(model => model.id === activeModelId)
  const [report, setReport] = useState<LocalModelBenchmarkReport | null>(null)
  const [running, setRunning] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submissionEnabled, setSubmissionEnabled] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  if (!installedActiveModel || !activeModelId) {
    return null
  }

  async function run() {
    if (running || submitting || confirmOpen || !status.server_running) {
      return
    }

    const modelId = activeModelId
    setRunning(true)
    setReport(null)
    setSubmissionEnabled(false)

    try {
      const result = await runLocalModelBenchmark(modelId)
      setReport(result.report)
      setSubmissionEnabled(result.submission_enabled)
    } catch (error) {
      notifyError(error, copy.benchmarkFailed)
    } finally {
      setRunning(false)
    }
  }

  async function submit() {
    if (!report || submitting) {
      return
    }

    setSubmitting(true)

    try {
      await submitLocalModelBenchmark(report, !submissionEnabled)
      setSubmissionEnabled(true)
      notify({ durationMs: 3_000, kind: 'success', message: copy.benchmarkSubmitted, title: copy.benchmarkTitle })
    } finally {
      setSubmitting(false)
    }
  }

  async function revokeConsent() {
    try {
      await setLocalModelBenchmarkConsent(false)
      setConfirmOpen(false)
      setReport(null)
      setSubmissionEnabled(false)
      notify({ durationMs: 3_000, kind: 'info', message: copy.benchmarkConsentStopped, title: copy.benchmarkTitle })
    } catch (error) {
      notifyError(error, copy.benchmarkFailed)
    }
  }

  const runtime = report
    ? copy.benchmarkReportConfig(
        `${report.runtime.engine} ${report.runtime.engine_tag} · ${report.runtime.backend}`,
        contextLabel(report.runtime.context_tokens, copy),
        report.runtime.slots,
        report.runtime.kv_cache,
        report.runtime.speculation
      )
    : ''

  const model = report
    ? copy.benchmarkReportModel(
        report.model.family,
        report.model.quant,
        gibibytes(report.model.weights_bytes, copy),
        gibibytes(report.model.lookup_table_bytes, copy)
      )
    : ''

  const hardware = report
    ? copy.benchmarkReportHardware(
        gibibytes(report.hardware.device_memory_bytes, copy),
        gibibytes(report.hardware.system_memory_bytes, copy),
        report.hardware.unified_memory
      )
    : ''

  const placement = report
    ? copy.benchmarkReportPlacement(lookupLabel(report, copy), report.runtime.ordinary_memory_spill)
    : ''

  const results = report
    ? copy.benchmarkReportResult(
        report.benchmark.wall_time_ms,
        rate(report.benchmark.prompt_tokens_per_second, copy),
        rate(report.benchmark.completion_tokens_per_second, copy)
      )
    : ''

  const workload = report
    ? copy.benchmarkReportWorkload(
        report.benchmark.request,
        report.benchmark.prompt_tokens,
        report.benchmark.completion_tokens
      )
    : ''

  return (
    <SettingsSection
      aside={report && submissionEnabled ? <Pill tone="success">{copy.benchmarkSharingEnabled}</Pill> : undefined}
      icon={BarChart3}
      title={copy.benchmarkTitle}
    >
      <p className="text-[0.75rem] text-muted-foreground">{copy.benchmarkSubtitle}</p>
      <ListRow
        action={
          <Button
            disabled={running || submitting || confirmOpen || !status.server_running}
            onClick={() => void run()}
            size="sm"
            type="button"
          >
            <BarChart3 />
            {running ? copy.benchmarkRunning : copy.benchmarkRun}
          </Button>
        }
        description={status.server_running ? copy.benchmarkRunDetail(activeModelId) : copy.benchmarkServerNeeded}
        title={copy.benchmarkRunTitle}
      />

      {report && (
        <div className="mt-2 grid gap-1">
          <ListRow description={model} title={copy.benchmarkReportModelTitle} />
          <ListRow description={runtime} title={copy.benchmarkReportRuntime} />
          <ListRow description={hardware} title={copy.benchmarkReportHardwareTitle} />
          <ListRow description={placement} title={copy.benchmarkReportPlacementTitle} />
          <ListRow description={results} title={copy.benchmarkReportResultsTitle} />
          <ListRow description={workload} title={copy.benchmarkReportWorkloadTitle} />
          <ListRow
            description={copy.benchmarkReportMeta(
              report.package_id,
              new Date(report.created_at).toLocaleString(),
              report.schema_version
            )}
            title={copy.benchmarkReportMetaTitle}
          />
          <ListRow
            action={
              <div className="flex flex-wrap justify-end gap-2">
                {submissionEnabled && (
                  <Button
                    disabled={submitting}
                    onClick={() => void revokeConsent()}
                    size="sm"
                    type="button"
                    variant="text"
                  >
                    <StopFilled />
                    {copy.benchmarkStopSharing}
                  </Button>
                )}
                <Button disabled={submitting} onClick={() => setConfirmOpen(true)} size="sm" type="button">
                  <Send />
                  {submitting ? copy.benchmarkSubmitting : copy.benchmarkSubmit}
                </Button>
              </div>
            }
            description={copy.benchmarkPrivacy}
            title={copy.benchmarkReviewTitle}
            wide
          />
        </div>
      )}

      <ConfirmDialog
        busyLabel={copy.benchmarkSubmitting}
        confirmLabel={copy.benchmarkSubmit}
        description={copy.benchmarkSubmitDescription}
        onClose={() => setConfirmOpen(false)}
        onConfirm={submit}
        open={confirmOpen}
        title={copy.benchmarkSubmitTitle}
      />
    </SettingsSection>
  )
}
