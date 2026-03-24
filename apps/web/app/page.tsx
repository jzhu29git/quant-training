import type { Metadata } from "next";
import Link from "next/link";

import { MetricCard, Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import {
  getBatchLogs,
  getBatchStatus,
  getDataSummary,
  getModelOverview,
  getPicks,
  getStockDetail,
  getStocks
} from "@/lib/api";
import { formatBytes, formatDate, formatDateRange, formatDateTime, formatMetric, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Aistock Quant Training",
  description: "Public read-only overview for the Aistock quant training system."
};

export default async function HomePage() {
  const copy = getMessages("en");

  const [status, logs, data, model, picks, stocks] = await Promise.all([
    getBatchStatus().catch(() => null),
    getBatchLogs(24).catch(() => null),
    getDataSummary().catch(() => null),
    getModelOverview().catch(() => null),
    getPicks(10).catch(() => null),
    getStocks(12).catch(() => [])
  ]);

  const training = (model?.training_metadata ?? {}) as Record<string, unknown>;
  const trainingMetrics = (training.metrics ?? {}) as Record<string, number>;
  const latestLines = logs?.lines.slice(-12) ?? [];
  const previewCode = stocks[0]?.code ?? data?.sample_codes[0] ?? "000001";
  const detail = await getStockDetail(previewCode).catch(() => null);

  return (
    <div className="page-dark">
      <div className="shell shell-dark">
        <header className="hero-landing">
          <section className="hero-landing-panel hero-landing-panel-full">
            <div className="hero-landing-grid">
              <div className="hero-panel-copy-wrap">
                <p className="eyebrow hero-dark-eyebrow">{copy.brand}</p>
                <h1 className="text-gradient-accent">Quant Training</h1>
                <p className="hero-panel-copy hero-panel-copy-lead">
                  From local A-share data ingestion to LightGBM training, walk-forward backtests, and ranked signal
                  delivery, Aistock turns quant experimentation into an operator-grade system that feels ready on day one.
                </p>
                <p className="hero-panel-note">
                  Tech Stack: Next.js 15, React 19, TypeScript, FastAPI, Uvicorn, Pandas, PyArrow, LightGBM,
                  scikit-learn, AkShare/BaoStock data ingestion, and Docker Compose deployment.
                </p>
              </div>

              <div className="hero-visual-stack">
                <div className="hero-panel-header">
                  <div>
                    <p className="hero-panel-kicker">Live System Surface</p>
                    <h2>Quant Engine Snapshot</h2>
                  </div>
                  <Link
                    href="/login"
                    className="nav-link hero-login-button"
                    aria-label="Login to access the Aistock control panel"
                  >
                    <span className="hero-login-copy">
                      <span className="hero-login-meta">Secure Access</span>
                      <span className="hero-login-label">Login</span>
                    </span>
                    <span className="hero-login-arrow" aria-hidden="true">
                      &rarr;
                    </span>
                  </Link>
                </div>

                <div>
                  <p className="hero-panel-kicker">{copy.overview.snapshot}</p>
                  <div className="hero-panel-grid">
                    <div className="hero-panel-metric">
                      <span>{copy.overview.stocksInUniverse}</span>
                      <strong>{formatNumber(data?.stock_count, "en")}</strong>
                    </div>
                    <div className="hero-panel-metric">
                      <span>{copy.overview.klineFiles}</span>
                      <strong>{formatNumber(data?.kline_file_count, "en")}</strong>
                    </div>
                    <div className="hero-panel-metric">
                      <span>{copy.overview.valuationFiles}</span>
                      <strong>{formatNumber(data?.valuation_file_count, "en")}</strong>
                    </div>
                    <div className="hero-panel-metric">
                      <span>{copy.overview.latestInference}</span>
                      <strong>{formatDate(data?.latest_inference_snapshot?.latest_date, "en")}</strong>
                    </div>
                    <div className="hero-panel-metric">
                      <span>{copy.overview.topSavedFeatures}</span>
                      <strong>{formatNumber(model?.top_features.length, "en")}</strong>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </header>

        <main className="page-content">
          <section className="metrics-grid">
            <MetricCard
              label={copy.overview.batchStatus}
              value={status?.is_running ? copy.common.live : copy.common.idle}
              hint={status?.container_name ?? copy.overview.stateFileOnly}
            />
            <MetricCard
              label={copy.overview.progress}
              value={typeof status?.progress_pct === "number" ? `${formatNumber(status.progress_pct, "en", { maximumFractionDigits: 1 })}%` : "—"}
              hint={`${formatNumber(status?.done_count, "en")}/${formatNumber(status?.total_codes, "en")} ${copy.overview.doneHint}`}
            />
            <MetricCard
              label={copy.overview.dataFiles}
              value={formatNumber(data?.paired_file_count, "en")}
              hint={data ? `${formatBytes(data.total_size_mb * 1024 * 1024, "en")} ${copy.common.localStore}` : copy.overview.stateFileOnly}
            />
            <MetricCard
              label={copy.overview.topPicks}
              value={formatNumber(picks?.rows, "en")}
              hint={picks?.latest_date ? `${copy.overview.latestDateHint} ${formatDate(picks.latest_date, "en")}` : copy.overview.noInference}
            />
            <MetricCard
              label={copy.overview.validationAuc}
              value={formatMetric(trainingMetrics.auc, "en")}
              hint={copy.overview.latestTraining}
            />
          </section>

          <section className="two-col-grid">
            <Panel
              title={copy.overview.pulse}
              aside={<span className={`pill ${status?.is_running ? "live" : "warn"}`}>{status?.is_running ? copy.common.live : copy.common.checkNeeded}</span>}
            >
              <div className="status-meta">
                <span>{copy.common.lastStateUpdate}: {formatDateTime(status?.updated_at, "en")}</span>
                <span>{copy.common.lastCode}: {status?.last_code ?? "—"}</span>
                <span>{copy.common.remaining}: {formatNumber(status?.remaining_count, "en")}</span>
                <span>{copy.common.logSource}: {logs?.source ?? "—"}</span>
              </div>
              <pre className="log-console">{latestLines.join("\n") || copy.common.noLogs}</pre>
            </Panel>

            <Panel title={`Kline Preview · ${previewCode}`} aside={<span className="pill">Visitor Preview</span>}>
              <div className="status-meta">
                <span>{copy.common.rows}: {formatNumber(detail?.kline.rows, "en")}</span>
                <span>{copy.common.dateRange}: {formatDateRange({ date_min: detail?.kline.date_min, date_max: detail?.kline.date_max }, "en", copy.common.to)}</span>
              </div>
              <DataTable
                rows={detail?.kline.head ?? []}
                columns={detail?.kline.columns.slice(0, 8)}
                emptyLabel={copy.common.noRows}
                locale="en"
              />
            </Panel>
          </section>
        </main>
      </div>
    </div>
  );
}
