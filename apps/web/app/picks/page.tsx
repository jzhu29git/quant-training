import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPicks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export default async function PicksPage() {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const picks = await getPicks(30);

  return (
    <Shell
      title={copy.picks.title}
      subtitle={copy.picks.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label={copy.picks.rows} value={formatNumber(picks.rows, user.locale)} hint={copy.picks.rowsHint} />
        <MetricCard label={copy.picks.latestDate} value={formatDate(picks.latest_date, user.locale)} hint={copy.picks.latestSnapshot} />
        <MetricCard label={copy.picks.displayedPicks} value={formatNumber(picks.picks.length, user.locale)} hint={copy.picks.topRankedRows} />
      </section>

      <Panel title={copy.picks.rankedSignals}>
        <DataTable
          rows={picks.picks}
          columns={
            user.locale === "zh-Hant"
              ? [
                  { key: "rank", label: "排名" },
                  { key: "date", label: "預測時間" },
                  { key: "code", label: "代碼" },
                  { key: "name", label: "名稱" },
                  { key: "industry", label: "產業" },
                  { key: "score", label: "模型分數" },
                  { key: "close", label: "當時股價" },
                  { key: "bias_20", label: "20 日乖離" },
                  { key: "pe_ttm", label: "PE TTM" },
                  { key: "pb", label: "PB" }
                ]
              : [
                  { key: "rank", label: "Rank" },
                  { key: "date", label: "Prediction Time" },
                  { key: "code", label: "Code" },
                  { key: "name", label: "Name" },
                  { key: "industry", label: "Industry" },
                  { key: "score", label: "Model Score" },
                  { key: "close", label: "Price At Signal" },
                  { key: "bias_20", label: "20D Bias" },
                  { key: "pe_ttm", label: "PE TTM" },
                  { key: "pb", label: "PB" }
                ]
          }
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>
    </Shell>
  );
}
