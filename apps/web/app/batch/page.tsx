import { AutoRefresh } from "@/components/auto-refresh";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { getBatchStatus, getModelOverview, getPipelineRunStatus, getWorkflowStatus, type WorkflowRuntimeStep } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatBytes, formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

function statusPillClass(status: string) {
  if (status === "running" || status === "completed") {
    return "live";
  }
  if (status === "failed" || status === "stopped") {
    return "warn";
  }
  return "";
}

function stepArtifact(runtime?: WorkflowRuntimeStep | null) {
  if (!runtime) {
    return null;
  }
  if (runtime.artifact_path) {
    return runtime.artifact_path;
  }
  if (runtime.latest_log_file) {
    return runtime.latest_log_file;
  }
  return "—";
}

function flashMessage(
  isZh: boolean,
  params: { notice?: string; error?: string; target?: string },
  stepLabels: Record<string, string>
) {
  const code = params.notice ?? params.error;
  if (!code) {
    return null;
  }

  const targetLabel = stepLabels[params.target ?? ""] ?? (isZh ? "目前控制項" : "this control");
  const success = {
    started: isZh ? `${targetLabel} 已送出啟動要求。` : `Start request sent for ${targetLabel}.`,
    stopped: isZh ? `${targetLabel} 已送出停止要求。` : `Stop request sent for ${targetLabel}.`
  } as const;
  const errors: Record<string, string> = {
    forbidden: isZh ? "這個帳號沒有控制權限。" : "This account does not have permission to control the workflow.",
    already_running: isZh ? `${targetLabel} 已經在執行中。` : `${targetLabel} is already running.`,
    not_running: isZh ? `${targetLabel} 目前沒有在執行。` : `${targetLabel} is not currently running.`,
    not_found: isZh ? `找不到 ${targetLabel} 的執行紀錄。` : `No run record was found for ${targetLabel}.`,
    control_unavailable: isZh ? "後台控制功能尚未正確設定。" : "Workflow control is not configured correctly yet.",
    invalid_action: isZh ? "這個控制動作無效。" : "That control action is not valid.",
    control_failed: isZh ? "控制要求失敗，請查看 API 日誌。" : "Control request failed. Check the API logs.",
    docker_unavailable: isZh ? "API 容器目前無法連到 Docker。" : "The API container cannot reach Docker right now.",
    image_missing: isZh ? "需要的 Docker image 不存在。" : "A required Docker image is missing.",
    start_failed: isZh ? `${targetLabel} 啟動失敗。` : `${targetLabel} failed to start.`,
    stop_failed: isZh ? `${targetLabel} 停止失敗。` : `${targetLabel} failed to stop.`,
    pipeline_running: isZh ? "Daily pipeline 執行中，請先停止它再手動啟動單一步驟。" : "Daily pipeline is running. Stop it before starting a single step manually.",
    invalid_step: isZh ? "這個 workflow step 不支援控制。" : "That workflow step is not supported by the control layer."
  };

  if (params.notice && code in success) {
    return { tone: "success", text: success[code as keyof typeof success] };
  }
  if (code in errors) {
    return { tone: "error", text: errors[code] };
  }
  if (params.notice) {
    return {
      tone: "success",
      text: isZh ? `${targetLabel} 控制作業已完成。` : `${targetLabel} control action completed.`
    };
  }
  return { tone: "error", text: errors.control_failed };
}

function renderControlButtons({
  target,
  isAdmin,
  canStart,
  canStop,
  startLabel,
  stopLabel
}: {
  target: string;
  isAdmin: boolean;
  canStart: boolean;
  canStop: boolean;
  startLabel: string;
  stopLabel: string;
}) {
  if (!isAdmin) {
    return null;
  }

  return (
    <div className="action-row">
      {canStart ? (
        <form action="/batch/control" method="post">
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="action" value="start" />
          <button className="auth-submit action-button" type="submit">
            {startLabel}
          </button>
        </form>
      ) : null}
      {canStop ? (
        <form action="/batch/control" method="post">
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="action" value="stop" />
          <button className="action-button danger-button" type="submit">
            {stopLabel}
          </button>
        </form>
      ) : null}
    </div>
  );
}

export default async function BatchPage({
  searchParams
}: {
  searchParams?: Promise<{ notice?: string; error?: string; target?: string }>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const isZh = user.locale === "zh-Hant";
  const [batchStatus, workflow, pipeline] = await Promise.all([
    getBatchStatus(),
    getWorkflowStatus(),
    getPipelineRunStatus()
  ]);
  const modelOverview = await getModelOverview();
  const modelProfiles = Array.isArray(modelOverview.model_profiles)
    ? modelOverview.model_profiles as Array<Record<string, unknown>>
    : [];
  const isAdmin = user.role === "admin";
  const params = (await searchParams) ?? {};
  const stepLabels: Record<string, string> = {
    pipeline: isZh ? "Daily Pipeline" : "Daily Pipeline",
    step1: isZh ? "Step 1 資料準備" : "Step 1 Data Prepare",
    step2: isZh ? "Step 2 特徵工程" : "Step 2 Feature Engineering",
    step3: isZh ? "Step 3 推論特徵" : "Step 3 Inference Features",
    step4: isZh ? "Step 4 訓練與打分" : "Step 4 Train and Score",
    step5: isZh ? "Backtest" : "Backtest",
    step6: isZh ? "自動模擬交易" : "Auto Paper Trading",
    paper: isZh ? "自動模擬交易" : "Auto Paper Trading"
  };
  const flash = flashMessage(isZh, params, stepLabels);
  const runtimeByStep = new Map(workflow.steps.map((step) => [step.step, step]));
  const runningSteps = workflow.steps.filter((step) => step.is_running).length;
  const completedStepsLabel = pipeline.completed_steps.map((key) => stepLabels[key] ?? key).join(" -> ");
  const stepCards = [
    {
      key: "step1",
      title: stepLabels.step1,
      description: isZh
        ? "股票池同步、industry metadata 與 raw download 會合併在同一個 data-prepare batch 中執行。"
        : "Universe sync, industry metadata, and raw download run together in one data-prepare batch.",
      runtime: runtimeByStep.get(1),
      canStart: !batchStatus.is_running && !pipeline.is_running,
      canStop: batchStatus.is_running,
      startLabel: isZh ? "啟動 Step 1" : "Start Step 1",
      stopLabel: isZh ? "停止 Step 1" : "Stop Step 1"
    },
    {
      key: "step2",
      title: stepLabels.step2,
      description: isZh ? "把原始資料轉成訓練特徵表。" : "Build the step 2 training feature matrix.",
      runtime: runtimeByStep.get(2),
      canStart: !runtimeByStep.get(2)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(2)?.is_running),
      startLabel: isZh ? "啟動 Step 2" : "Start Step 2",
      stopLabel: isZh ? "停止 Step 2" : "Stop Step 2"
    },
    {
      key: "step3",
      title: stepLabels.step3,
      description: isZh ? "建立最新推論用的特徵快照。" : "Build the latest inference feature snapshot.",
      runtime: runtimeByStep.get(3),
      canStart: !runtimeByStep.get(3)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(3)?.is_running),
      startLabel: isZh ? "啟動 Step 3" : "Start Step 3",
      stopLabel: isZh ? "停止 Step 3" : "Stop Step 3"
    },
    {
      key: "step4",
      title: stepLabels.step4,
      description: isZh ? "重新訓練模型並產出最新 scores。" : "Retrain the model and score the latest inference snapshot.",
      runtime: runtimeByStep.get(4),
      canStart: !runtimeByStep.get(4)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(4)?.is_running),
      startLabel: isZh ? "啟動 Step 4" : "Start Step 4",
      stopLabel: isZh ? "停止 Step 4" : "Stop Step 4"
    },
    {
      key: "step5",
      title: stepLabels.step5,
      description: isZh ? "獨立執行 Backtest，回測不同模型 profile，並把結果存成可比較的 run。" : "Run backtests as a separate tool, save comparable runs, and compare model profiles over time.",
      runtime: runtimeByStep.get(5),
      canStart: !runtimeByStep.get(5)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(5)?.is_running),
      startLabel: isZh ? "啟動 Backtest" : "Run Backtest",
      stopLabel: isZh ? "停止 Backtest" : "Stop Backtest"
    },
    {
      key: "paper",
      title: stepLabels.step6,
      description: isZh ? "監看最新 score snapshot，透過既有 Futu gateway 自動同步模擬交易委託。" : "Watch the latest score snapshot and auto-sync simulated orders through the existing Futu gateway.",
      runtime: runtimeByStep.get(6),
      canStart: !runtimeByStep.get(6)?.is_running,
      canStop: Boolean(runtimeByStep.get(6)?.is_running),
      startLabel: isZh ? "啟動模擬交易" : "Start Paper Trading",
      stopLabel: isZh ? "停止模擬交易" : "Stop Paper Trading"
    }
  ];

  return (
    <Shell
      title={isZh ? "Pipeline Control Center" : "Pipeline Control Center"}
      subtitle={
        isZh
          ? "這裡直接操作每日資料刷新與獨立 Backtest，並即時看到每一步的容器、artifact 與 live log。"
          : "Operate the daily data-refresh pipeline and separate backtests here, with live containers, artifacts, and logs."
      }
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <AutoRefresh intervalSeconds={15} />
      {flash ? <p className={`banner banner-${flash.tone}`}>{flash.text}</p> : null}

      <section className="metrics-grid">
        <MetricCard label={isZh ? "Daily Pipeline" : "Daily Pipeline"} value={pipeline.status_label} hint={pipeline.current_step_label ?? (isZh ? "待機中" : "Idle")} />
        <MetricCard label={isZh ? "正在執行的步驟" : "Running Steps"} value={formatNumber(runningSteps, user.locale)} hint={formatDateTime(workflow.generated_at, user.locale)} />
        <MetricCard label={isZh ? "Step 1 進度" : "Step 1 Progress"} value={`${formatNumber(batchStatus.done_count, user.locale)}/${formatNumber(batchStatus.total_codes, user.locale)}`} hint={typeof batchStatus.progress_pct === "number" ? `${formatNumber(batchStatus.progress_pct, user.locale, { maximumFractionDigits: 1 })}%` : "—"} />
        <MetricCard label={isZh ? "目前步驟" : "Current Step"} value={pipeline.current_step_label ?? "—"} hint={formatDateTime(pipeline.updated_at, user.locale)} />
        <MetricCard label={isZh ? "最新代碼" : "Last Code"} value={batchStatus.last_code ?? "—"} hint={formatDateTime(batchStatus.updated_at, user.locale)} />
        <MetricCard label={isZh ? "Backtest 產物" : "Backtest Artifact"} value={formatBytes(runtimeByStep.get(5)?.artifact_size_bytes, user.locale)} hint={formatDateTime(runtimeByStep.get(5)?.artifact_updated_at, user.locale)} />
      </section>

      <section className="control-center-grid">
        <Panel
          title={isZh ? "Daily Pipeline" : "Daily Pipeline"}
          aside={<span className={`pill ${statusPillClass(pipeline.status)}`}>{pipeline.status_label}</span>}
        >
          <div className="stack">
            <p className="panel-copy">
              {isZh
                ? "這個控制項只跑每日需要的 Step 1、2、3、4。Backtest 已經獨立拆出去，不再卡在 nightly 流程裡。"
                : "This control now runs only the daily trading steps: 1, 2, 3, and 4. Backtest is separate and no longer blocks the nightly flow."}
            </p>
            <div className="status-meta">
              <span className="meta-item"><span className="meta-label">{isZh ? "目前步驟" : "Current step"}:</span> <span className="meta-value">{pipeline.current_step_label ?? "—"}</span></span>
              <span className="meta-item"><span className="meta-label">{isZh ? "已完成" : "Completed"}:</span> <span className="meta-value">{completedStepsLabel || "—"}</span></span>
              <span className="meta-item"><span className="meta-label">{isZh ? "容器" : "Container"}:</span> <span className="meta-value">{pipeline.container_name ?? "—"}</span></span>
              <span className="meta-item"><span className="meta-label">{isZh ? "狀態更新" : "Updated"}:</span> <span className="meta-value">{formatDateTime(pipeline.updated_at, user.locale)}</span></span>
              <span className="meta-item"><span className="meta-label">{isZh ? "日誌來源" : "Log source"}:</span> <span className="meta-value">{pipeline.log_source ?? "—"}</span></span>
            </div>
            {pipeline.error_message ? (
              <p className="panel-copy status-warn">{isZh ? `錯誤: ${pipeline.error_message}` : `Error: ${pipeline.error_message}`}</p>
            ) : null}
            {renderControlButtons({
              target: "pipeline",
              isAdmin,
              canStart: pipeline.can_start,
              canStop: pipeline.can_stop,
              startLabel: isZh ? "啟動 Daily Pipeline" : "Run Daily Pipeline",
              stopLabel: isZh ? "停止 Daily Pipeline" : "Stop Daily Pipeline"
            })}
            {!isAdmin ? (
              <span className="pill">{isZh ? "只讀帳號" : "Read-only account"}</span>
            ) : (
              <span className="pill">{isZh ? "自動刷新每 15 秒" : "Auto-refresh every 15s"}</span>
            )}
            <pre className="log-console compact-log">{pipeline.log_lines.join("\n") || copy.common.noLogs}</pre>
          </div>
        </Panel>

        {stepCards.map((card) => (
          <Panel
            key={card.key}
            title={card.title}
            aside={<span className={`pill ${statusPillClass(card.runtime?.status ?? "idle")}`}>{card.runtime?.status_label ?? "Idle"}</span>}
          >
            <div className="stack">
              <p className="panel-copy">{card.description}</p>
              <div className="inline-pill-row">
                <span className="pill pill-wrap pill-primary">
                  <span className="pill-label">{isZh ? "Artifact" : "Artifact"}:</span>
                  <span className="pill-value">{stepArtifact(card.runtime)}</span>
                </span>
                <span className="pill pill-wrap">
                  <span className="pill-label">{isZh ? "Size" : "Size"}:</span>
                  <span className="pill-value">{formatBytes(card.runtime?.artifact_size_bytes, user.locale)}</span>
                </span>
                <span className="pill pill-wrap">
                  <span className="pill-label">{isZh ? "Log" : "Log"}:</span>
                  <span className="pill-value">{card.runtime?.latest_log_source ?? "—"}</span>
                </span>
              </div>
              <div className="status-meta">
                <span className="meta-item"><span className="meta-label">{isZh ? "容器" : "Container"}:</span> <span className="meta-value">{card.runtime?.container_name ?? "—"}</span></span>
                <span className="meta-item"><span className="meta-label">{isZh ? "容器狀態" : "Container status"}:</span> <span className="meta-value">{card.runtime?.container_status ?? "—"}</span></span>
                <span className="meta-item"><span className="meta-label">{isZh ? "開始時間" : "Started"}:</span> <span className="meta-value">{formatDateTime(card.runtime?.container_started_at, user.locale)}</span></span>
                <span className="meta-item"><span className="meta-label">{isZh ? "完成時間" : "Finished"}:</span> <span className="meta-value">{formatDateTime(card.runtime?.container_finished_at, user.locale)}</span></span>
              </div>
              <div className="detail-list">
                {(card.runtime?.details ?? []).map((detail) => (
                  <div key={`${card.key}-${detail.label}`} className="detail-row">
                    <span className="detail-label">{detail.label}</span>
                    <strong className="detail-value">{formatDisplayValue(detail.value, { locale: user.locale, key: detail.label })}</strong>
                  </div>
                ))}
              </div>
              {card.key === "step5" ? (
                <div className="action-row">
                  {isAdmin && card.canStart
                    ? modelProfiles.map((profile) => {
                        const profileName = String(profile.name ?? "").trim();
                        const profileLabel = String(profile.label ?? profileName).trim() || profileName;
                        if (!profileName) {
                          return null;
                        }
                        return (
                          <form key={profileName} action="/batch/control" method="post">
                            <input type="hidden" name="target" value={card.key} />
                            <input type="hidden" name="action" value="start" />
                            <input type="hidden" name="profile" value={profileName} />
                            <button className="auth-submit action-button" type="submit">
                              {isZh ? `回測 ${profileLabel}` : `Backtest ${profileLabel}`}
                            </button>
                          </form>
                        );
                      })
                    : null}
                  {isAdmin && card.canStop ? (
                    <form action="/batch/control" method="post">
                      <input type="hidden" name="target" value={card.key} />
                      <input type="hidden" name="action" value="stop" />
                      <button className="action-button danger-button" type="submit">
                        {card.stopLabel}
                      </button>
                    </form>
                  ) : null}
                </div>
              ) : renderControlButtons({
                target: card.key,
                isAdmin,
                canStart: card.canStart,
                canStop: card.canStop,
                startLabel: card.startLabel,
                stopLabel: card.stopLabel
              })}
              <pre className="log-console compact-log">{card.runtime?.log_lines.join("\n") || copy.common.noLogs}</pre>
            </div>
          </Panel>
        ))}
      </section>
    </Shell>
  );
}
