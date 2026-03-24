import { MetricCard, Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import { Shell } from "@/components/shell";
import { getPipelineSummary, getBatchStatus, getDataSummary, getModelOverview, getPicks, getWorkflowStatus } from "@/lib/api";
import { requireAdmin } from "@/lib/auth";
import { getAdminCatalog } from "@/lib/admin";
import { formatBytes, formatDate, formatDateRange, formatDateTime, formatDisplayValue, formatMetric, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

function runtimePillClass(status: string) {
  if (status === "running" || status === "completed") {
    return "live";
  }
  if (status === "failed") {
    return "warn";
  }
  return "";
}

function workflowArtifact(step: number, context: {
  data: Awaited<ReturnType<typeof getDataSummary>>;
  status: Awaited<ReturnType<typeof getBatchStatus>>;
  pipeline: Awaited<ReturnType<typeof getPipelineSummary>>;
  picks: Awaited<ReturnType<typeof getPicks>>;
  training: Record<string, unknown>;
  backtest: Record<string, unknown>;
}, locale: "en" | "zh-Hant") {
  const { data, status, pipeline, picks, training, backtest } = context;
  const inferenceHasLegacyFields = Boolean(
    pipeline.inference_features?.columns.some((column) => column === "pe_static" || column === "peg")
  );
  const scoreHasLegacyFields = Boolean(
    pipeline.inference_scores?.columns.some((column) => column === "pe_static" || column === "peg")
  );
  const modelHasLegacyFields = Boolean(
    Array.isArray(training.feature_cols) &&
      training.feature_cols.some((column) => column === "pe_static" || column === "peg")
  );
  if (step === 1) {
    return `${formatNumber(data.active_stock_count, locale)} active · ${formatNumber(data.paired_file_count, locale)} paired files · ${formatNumber(data.total_size_mb, locale, { maximumFractionDigits: 1 })} MB`;
  }
  if (step === 2) {
    return pipeline.training_features
      ? `${formatNumber(pipeline.training_features.rows, locale)} rows · ${formatNumber(pipeline.training_features.code_count, locale)} codes · ${formatDateRange(pipeline.training_features, locale)}`
      : "Missing";
  }
  if (step === 3) {
    return pipeline.inference_features
      ? `${formatNumber(pipeline.inference_features.rows, locale)} rows · ${formatNumber(pipeline.inference_features.code_count, locale)} codes · ${formatDate(pipeline.inference_features.date_max, locale)}${inferenceHasLegacyFields ? " · legacy cols present" : ""}`
      : "Missing";
  }
  if (step === 4) {
    return `${formatNumber(picks.rows, locale)} scored rows · valid AUC ${formatMetric((training.metrics as Record<string, unknown> | undefined)?.auc, locale)}${scoreHasLegacyFields || modelHasLegacyFields ? " · legacy cols present" : ""}`;
  }
  if (step === 5) {
    return `${formatNumber(backtest.num_rebalances as number | undefined, locale)} rebalances · ${formatNumber(backtest.num_codes as number | undefined, locale)} codes · OOS AUC ${formatMetric((backtest.oos_metrics as Record<string, unknown> | undefined)?.auc, locale)}`;
  }
  return `${status.is_running ? "Live batch monitor" : "Idle monitor"} · progress ${typeof status.progress_pct === "number" ? `${formatNumber(status.progress_pct, locale, { maximumFractionDigits: 1 })}%` : "—"}`;
}

export default async function AdminPage() {
  const user = await requireAdmin();
  const copy = getMessages(user.locale);
  const admin = getAdminCatalog(user.locale);

  const [status, data, model, picks, pipeline, workflow] = await Promise.all([
    getBatchStatus(),
    getDataSummary(),
    getModelOverview(),
    getPicks(10),
    getPipelineSummary(),
    getWorkflowStatus()
  ]);

  const training = (model.training_metadata ?? {}) as Record<string, unknown>;
  const trainingMetrics = (training.metrics ?? {}) as Record<string, unknown>;
  const backtest = (model.backtest_summary ?? {}) as Record<string, unknown>;
  const backtestMetrics = (backtest.oos_metrics ?? {}) as Record<string, unknown>;
  const modelFeatureCols = Array.isArray(training.feature_cols) ? (training.feature_cols as string[]) : [];
  const modelUsesLegacyFields = modelFeatureCols.includes("pe_static") || modelFeatureCols.includes("peg");
  const inferenceUsesLegacyFields = Boolean(
    pipeline.inference_features?.columns.some((column) => column === "pe_static" || column === "peg")
  );
  const scoreUsesLegacyFields = Boolean(
    pipeline.inference_scores?.columns.some((column) => column === "pe_static" || column === "peg")
  );
  const trainingArtifactCodes = pipeline.training_features?.code_count ?? null;
  const inferenceArtifactCodes = pipeline.inference_features?.code_count ?? null;
  const scoreArtifactCodes = pipeline.inference_scores?.code_count ?? null;
  const backtestCodes = typeof backtest.num_codes === "number" ? backtest.num_codes : null;
  const universeAligned = typeof trainingArtifactCodes === "number" ? trainingArtifactCodes === data.active_stock_count : null;
  const inferenceAligned =
    typeof inferenceArtifactCodes === "number" ? inferenceArtifactCodes === scoreArtifactCodes : null;
  const modelAligned =
    typeof trainingArtifactCodes === "number" && typeof backtestCodes === "number"
      ? trainingArtifactCodes === backtestCodes
      : null;
  const runtimeByStep = new Map(workflow.steps.map((step) => [step.step, step]));

  return (
    <Shell
      title={admin.title}
      subtitle={admin.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label="Active Universe" value={formatNumber(data.active_stock_count, user.locale)} hint="stock_list.parquet" />
        <MetricCard label="Registry History" value={formatNumber(data.registry_stock_count, user.locale)} hint="stock_registry.parquet" />
        <MetricCard label="Raw File Pairs" value={formatNumber(data.paired_file_count, user.locale)} hint={`${formatNumber(data.kline_file_count, user.locale)} kline / ${formatNumber(data.valuation_file_count, user.locale)} valuation`} />
        <MetricCard label="Step 2 Codes" value={formatNumber(trainingArtifactCodes, user.locale)} hint={pipeline.training_features?.path ?? "ml_features_ready.parquet"} />
        <MetricCard label="Step 3 Codes" value={formatNumber(inferenceArtifactCodes, user.locale)} hint={formatDate(pipeline.inference_features?.date_max, user.locale)} />
        <MetricCard label="Step 4 Codes" value={formatNumber(scoreArtifactCodes ?? picks.rows, user.locale)} hint={formatDate(pipeline.inference_scores?.date_max ?? picks.latest_date, user.locale)} />
        <MetricCard label={copy.overview.validationAuc} value={formatMetric(trainingMetrics.auc, user.locale)} hint={`valid rows ${formatNumber(training.valid_rows as number | undefined, user.locale)}`} />
        <MetricCard label="Backtest OOS AUC" value={formatMetric(backtestMetrics.auc, user.locale)} hint={`${formatNumber(backtestCodes, user.locale)} codes`} />
      </section>

      <section className="two-col-grid">
        <Panel title={admin.labels.runtime} aside={<span className={`pill ${status.is_running ? "live" : "warn"}`}>{status.is_running ? copy.common.live : copy.common.idle}</span>}>
          <div className="status-meta">
            <span>{copy.common.lastStateUpdate}: {formatDateTime(status.updated_at, user.locale)}</span>
            <span>{copy.overview.progress}: {typeof status.progress_pct === "number" ? `${formatNumber(status.progress_pct, user.locale, { maximumFractionDigits: 1 })}%` : "—"}</span>
            <span>{copy.common.lastCode}: {status.last_code ?? "—"}</span>
            <span>Latest inference: {formatDate(data.latest_inference_snapshot?.latest_date, user.locale)} / {formatNumber(data.latest_inference_snapshot?.code_count, user.locale)}</span>
            <span>Saved scores: {formatDate(pipeline.inference_scores?.date_max ?? picks.latest_date, user.locale)} / {formatNumber(scoreArtifactCodes ?? picks.rows, user.locale)}</span>
            <span>Saved model features: {formatNumber(modelFeatureCols.length, user.locale)}</span>
          </div>
        </Panel>

        <Panel title={admin.labels.currentGuardrails}>
          <div className="stack">
            <div className="inline-pill-row">
              <span className={`pill ${universeAligned ? "live" : "warn"}`}>
                Universe vs Step 2: {universeAligned ? admin.labels.aligned : admin.labels.checkNeeded}
              </span>
              <span className={`pill ${inferenceAligned ? "live" : "warn"}`}>
                Step 3 vs Step 4: {inferenceAligned ? admin.labels.aligned : admin.labels.checkNeeded}
              </span>
              <span className={`pill ${modelAligned ? "live" : "warn"}`}>
                Step 2 vs Backtest: {modelAligned ? admin.labels.aligned : admin.labels.checkNeeded}
              </span>
            </div>
            <div className="status-meta">
              <span>Active universe codes: {formatNumber(data.active_stock_count, user.locale)}</span>
              <span>Current step 2 feature codes: {formatNumber(trainingArtifactCodes, user.locale)}</span>
              <span>Current step 3 inference codes: {formatNumber(inferenceArtifactCodes, user.locale)}</span>
              <span>Current step 4 score codes: {formatNumber(scoreArtifactCodes ?? picks.rows, user.locale)}</span>
              <span>Saved backtest codes: {formatNumber(backtestCodes, user.locale)}</span>
            </div>
            <p className="panel-copy">
              {modelUsesLegacyFields ? admin.labels.modelStillLegacy : admin.labels.modelClean}
            </p>
            {(inferenceUsesLegacyFields || scoreUsesLegacyFields) ? (
              <p className="panel-copy">
                Current step 3 or step 4 artifacts still carry legacy `pe_static` / `peg` columns. They should disappear after step 3 and step 4 are rebuilt on the cleaned schema.
              </p>
            ) : null}
            <p className="panel-copy">
              {modelAligned
                ? "Saved model, scores, and backtest are aligned with the latest feature artifact."
                : "The latest step 2 artifact can be newer than the saved model/backtest. This panel makes that drift visible so admin can decide whether step 4 and Backtest need to rerun."}
            </p>
          </div>
        </Panel>
      </section>

      <Panel
        title="Workflow Live Monitor"
        aside={<span className="pill">{formatDateTime(workflow.generated_at, user.locale)}</span>}
      >
        <div className="workflow-runtime-grid">
          {admin.workflowSteps.map((step) => {
            const runtime = runtimeByStep.get(step.step);
            return (
              <section key={step.step} className="workflow-step-card">
                <div className="panel-header">
                  <div>
                    <p className="workflow-step-kicker">{step.step === 5 ? "Backtest" : `Step ${step.step}`}</p>
                    <h3>{step.title}</h3>
                  </div>
                  <div className="panel-aside">
                    <span className={`pill ${runtime ? runtimePillClass(runtime.status) : ""}`}>
                      {runtime?.status_label ?? "Unknown"}
                    </span>
                  </div>
                </div>
                <p className="panel-copy">{step.summary}</p>
                <div className="status-meta">
                  <span>Runner: {runtime?.runner_script ?? "—"}</span>
                  <span>Command: {runtime?.command_hint ?? "—"}</span>
                  <span>Container: {runtime?.container_name ?? "—"}</span>
                  <span>Container status: {runtime?.container_status ?? "—"}</span>
                  <span>Artifact: {runtime?.artifact_path ?? "—"}</span>
                  <span>Artifact updated: {formatDateTime(runtime?.artifact_updated_at, user.locale)}</span>
                  <span>Artifact size: {formatBytes(runtime?.artifact_size_bytes, user.locale)}</span>
                  <span>Log source: {runtime?.latest_log_source ?? "—"}</span>
                  <span>Log file: {runtime?.latest_log_file ?? "—"}</span>
                  <span>Log updated: {formatDateTime(runtime?.latest_log_updated_at, user.locale)}</span>
                  {runtime?.details.map((detail) => (
                    <span key={`${step.step}-${detail.label}`}>{detail.label}: {formatDisplayValue(detail.value, { locale: user.locale, key: detail.label })}</span>
                  ))}
                </div>
                {runtime?.log_lines.length ? (
                  <pre className="log-console">{runtime.log_lines.join("\n")}</pre>
                ) : (
                  <p className="panel-copy">No live log captured for this step yet.</p>
                )}
              </section>
            );
          })}
        </div>
      </Panel>

      <Panel title={admin.labels.workflow}>
        <div className="workflow-grid">
          {admin.workflowSteps.map((step) => (
            <section key={step.step} className="workflow-step-card">
              <p className="workflow-step-kicker">Step {step.step}</p>
              <h3>{step.title}</h3>
              <p className="panel-copy">{step.summary}</p>
              <div className="status-meta">
                <span>{admin.labels.inputs}: {step.inputs.join(", ")}</span>
                <span>{admin.labels.outputs}: {step.outputs.join(", ")}</span>
                <span>{admin.labels.liveArtifact}: {workflowArtifact(step.step, { data, status, pipeline, picks, training, backtest }, user.locale)}</span>
                <span>Runtime: {runtimeByStep.get(step.step)?.status_label ?? "—"}</span>
                <span>Code anchor: {step.anchor}</span>
              </div>
            </section>
          ))}
        </div>
      </Panel>

      <Panel title={admin.labels.catalog}>
        <div className="catalog-grid">
          {admin.fieldSections.map((section) => (
            <section key={section.key} className="catalog-panel">
              <div className="stack">
                <div>
                  <p className="workflow-step-kicker">{section.title}</p>
                  <p className="panel-copy">{section.summary}</p>
                </div>
                <DataTable
                  rows={section.rows}
                  columns={[
                    { key: "field", label: admin.labels.field },
                    { key: "meaning", label: admin.labels.meaning },
                    { key: "note", label: admin.labels.note }
                  ]}
                  emptyLabel={copy.common.noRows}
                  locale={user.locale}
                />
              </div>
            </section>
          ))}
        </div>
      </Panel>
    </Shell>
  );
}
