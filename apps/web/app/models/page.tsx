import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getModelOverview } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDateRange, formatMetric, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const overview = await getModelOverview();
  const training = (overview.training_metadata ?? {}) as Record<string, unknown>;
  const metrics = (training.metrics ?? {}) as Record<string, number>;
  const backtest = (overview.backtest_summary ?? {}) as Record<string, unknown>;
  const backtestRuns = Array.isArray(overview.backtest_runs)
    ? overview.backtest_runs as Array<Record<string, unknown>>
    : [];
  const profiles = Array.isArray(overview.model_profiles)
    ? overview.model_profiles as Array<Record<string, unknown>>
    : [];
  const isZh = user.locale === "zh-Hant";

  return (
    <Shell
      title={copy.models.title}
      subtitle={copy.models.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label={copy.models.auc} value={formatMetric(metrics.auc, user.locale)} hint={copy.models.validationMetric} />
        <MetricCard label={copy.models.accuracy} value={formatMetric(metrics.accuracy, user.locale)} hint={copy.models.thresholdValidation} />
        <MetricCard label={copy.models.trainRows} value={formatNumber(training.train_rows as number | undefined, user.locale)} hint={formatDateRange({ date_min: training.train_date_min as string | null | undefined, date_max: training.train_date_max as string | null | undefined }, user.locale, copy.common.to)} />
        <MetricCard label={copy.models.validRows} value={formatNumber(training.valid_rows as number | undefined, user.locale)} hint={formatDateRange({ date_min: training.valid_date_min as string | null | undefined, date_max: training.valid_date_max as string | null | undefined }, user.locale, copy.common.to)} />
      </section>

      <section className="two-col-grid">
        <Panel title={copy.models.trainingSnapshot}>
          <div className="status-meta">
            <span>{isZh ? "目前模型" : "Current model"}: {String(training.profile_name ?? "short_5d")}</span>
            <span>{isZh ? "標籤天數" : "Label horizon"}: {formatNumber(training.label_horizon as number | undefined, user.locale)}</span>
            <span>{copy.models.features}: {Array.isArray(training.feature_cols) ? formatNumber(training.feature_cols.length, user.locale) : "—"}</span>
            <span>{copy.models.categoricals}: {Array.isArray(training.categorical_cols) ? training.categorical_cols.join(", ") : "—"}</span>
            <span>{copy.models.threshold}: {formatMetric(training.threshold, user.locale)}</span>
            <span>{copy.models.validationDays}: {formatNumber(training.valid_days as number | undefined, user.locale)}</span>
          </div>
        </Panel>

        <Panel title={copy.models.backtestSnapshot}>
          <div className="status-meta">
            <span>{copy.models.totalReturn}: {formatMetric(backtest.portfolio_total_return, user.locale)}</span>
            <span>{copy.models.cagr}: {formatMetric(backtest.portfolio_cagr, user.locale)}</span>
            <span>{copy.models.maxDrawdown}: {formatMetric(backtest.portfolio_max_drawdown, user.locale)}</span>
            <span>{copy.models.rebalances}: {formatNumber(backtest.num_rebalances as number | undefined, user.locale)}</span>
          </div>
        </Panel>
      </section>

      <Panel title={isZh ? "模型 Profiles" : "Model Profiles"}>
        <DataTable
          rows={profiles}
          columns={[
            { key: "name", label: isZh ? "名稱" : "Name" },
            { key: "label", label: isZh ? "顯示名稱" : "Label" },
            { key: "label_horizon", label: isZh ? "標籤天數" : "Label Horizon" },
            { key: "label_threshold", label: isZh ? "標籤門檻" : "Label Threshold" },
            { key: "backtest_rebalance_every", label: isZh ? "回測調倉頻率" : "Rebalance Every" },
            { key: "backtest_top_k", label: isZh ? "回測持倉數" : "Backtest Top K" }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>

      <Panel title={isZh ? "Backtest 比較" : "Backtest Comparison"}>
        <DataTable
          rows={backtestRuns}
          columns={[
            { key: "run_id", label: isZh ? "Run" : "Run" },
            { key: "profile_label", label: isZh ? "模型" : "Model" },
            { key: "generated_at", label: isZh ? "產生時間" : "Generated" },
            { key: "portfolio_total_return", label: isZh ? "總報酬" : "Total Return" },
            { key: "portfolio_cagr", label: isZh ? "CAGR" : "CAGR" },
            { key: "portfolio_max_drawdown", label: isZh ? "最大回撤" : "Max Drawdown" },
            { key: "portfolio_win_rate", label: isZh ? "勝率" : "Win Rate" },
            { key: "num_rebalances", label: isZh ? "調倉次數" : "Rebalances" },
            { key: "backtest_end", label: isZh ? "回測結束" : "Backtest End" }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>

      <Panel title={copy.models.topFeatureImportance}>
        <DataTable
          rows={overview.top_features}
          columns={[
            { key: "feature", label: copy.models.feature },
            { key: "importance_gain", label: copy.models.importanceGain },
            { key: "importance_split", label: copy.models.importanceSplit }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>
    </Shell>
  );
}
