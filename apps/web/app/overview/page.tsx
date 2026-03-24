import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { getBatchLogs, getBatchStatus, getDataSummary, getModelOverview, getPicks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatMetric, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const user = await requireAuth();
  const copy = getMessages(user.locale);

  const [status, logs, data, model, picks] = await Promise.all([
    getBatchStatus(),
    getBatchLogs(24),
    getDataSummary(),
    getModelOverview(),
    getPicks(10)
  ]);

  const trainingMetrics = (model.training_metadata?.metrics ?? {}) as Record<string, number>;
  const latestLines = logs.lines.slice(-12);

  return (
    <Shell
      title={copy.overview.title}
      subtitle={copy.overview.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label={copy.overview.batchStatus} value={status.is_running ? copy.common.live : copy.common.idle} hint={status.container_name ?? copy.overview.stateFileOnly} />
        <MetricCard label={copy.overview.progress} value={typeof status.progress_pct === "number" ? `${formatNumber(status.progress_pct, user.locale, { maximumFractionDigits: 1 })}%` : "—"} hint={`${formatNumber(status.done_count, user.locale)}/${formatNumber(status.total_codes, user.locale)} ${copy.overview.doneHint}`} />
        <MetricCard label={copy.overview.dataFiles} value={formatNumber(data.paired_file_count, user.locale)} hint={`${formatNumber(data.total_size_mb, user.locale, { maximumFractionDigits: 1 })} MB ${copy.common.localStore}`} />
        <MetricCard label={copy.overview.topPicks} value={formatNumber(picks.rows, user.locale)} hint={picks.latest_date ? `${copy.overview.latestDateHint} ${formatDate(picks.latest_date, user.locale)}` : copy.overview.noInference} />
        <MetricCard label={copy.overview.validationAuc} value={formatMetric(trainingMetrics.auc, user.locale)} hint={copy.overview.latestTraining} />
      </section>

      <section className="two-col-grid">
        <Panel title={copy.overview.pulse} aside={<span className={`pill ${status.is_running ? "live" : "warn"}`}>{status.is_running ? copy.common.live : copy.common.checkNeeded}</span>}>
          <div className="status-meta">
            <span>{copy.common.lastStateUpdate}: {formatDateTime(status.updated_at, user.locale)}</span>
            <span>{copy.common.lastCode}: {status.last_code ?? "—"}</span>
            <span>{copy.common.remaining}: {formatNumber(status.remaining_count, user.locale)}</span>
            <span>{copy.common.logSource}: {logs.source}</span>
          </div>
          <pre className="log-console">{latestLines.join("\n") || copy.common.noLogs}</pre>
        </Panel>

        <Panel title={copy.overview.snapshot}>
          <div className="status-meta">
            <span>{copy.overview.stocksInUniverse}: {formatNumber(data.stock_count, user.locale)}</span>
            <span>{copy.overview.klineFiles}: {formatNumber(data.kline_file_count, user.locale)}</span>
            <span>{copy.overview.valuationFiles}: {formatNumber(data.valuation_file_count, user.locale)}</span>
            <span>{copy.overview.latestInference}: {formatDate(data.latest_inference_snapshot?.latest_date, user.locale)}</span>
            <span>{copy.overview.topSavedFeatures}: {formatNumber(model.top_features.length, user.locale)}</span>
          </div>
        </Panel>
      </section>
    </Shell>
  );
}
