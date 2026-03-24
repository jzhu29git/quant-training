import { AutoRefresh } from "@/components/auto-refresh";
import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getPaperHistory, getPaperOrders, getPaperOverview, getPaperPositions, getPaperTargets } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

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

function flashMessage(_isZh: boolean, params: { notice?: string; error?: string; target?: string }) {
  const code = params.notice ?? params.error;
  if (!code) {
    return null;
  }

  const targetLabel = "Auto Paper Trading";
  const success = {
    started: `Start request sent for ${targetLabel}.`,
    stopped: `Stop request sent for ${targetLabel}.`
  } as const;
  const errors: Record<string, string> = {
    forbidden: "This account does not have permission to control the service.",
    already_running: `${targetLabel} is already running.`,
    not_running: `${targetLabel} is not currently running.`,
    not_found: `No run record was found for ${targetLabel}.`,
    control_unavailable: "Workflow control is not configured correctly yet.",
    invalid_action: "That control action is not valid.",
    control_failed: "Control request failed. Check the API logs.",
    docker_unavailable: "The API container cannot reach Docker right now.",
    image_missing: "A required Docker image is missing.",
    start_failed: `${targetLabel} failed to start.`,
    stop_failed: `${targetLabel} failed to stop.`
  };

  if (params.notice && code in success) {
    return { tone: "success", text: success[code as keyof typeof success] };
  }
  if (code in errors) {
    return { tone: "error", text: errors[code] };
  }
  return { tone: "error", text: errors.control_failed };
}

export default async function PaperPage({
  searchParams
}: {
  searchParams?: Promise<{ notice?: string; error?: string; target?: string }>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const [overview, targets, positions, orders, history] = await Promise.all([
    getPaperOverview(),
    getPaperTargets(20),
    getPaperPositions(20),
    getPaperOrders(20),
    getPaperHistory(20)
  ]);
  const isAdmin = user.role === "admin";
  const params = (await searchParams) ?? {};
  const flash = flashMessage(false, params);
  const daemon = overview.daemon;
  const gateway = overview.gateway;
  const liveSummary = (overview.live_summary ?? {}) as Record<string, unknown>;
  const state = overview.state ?? {};
  const priceLimitErrorLabel = "price outside CN daily limit band";
  const recentOrders = orders.orders as Array<Record<string, unknown>>;
  const ordersBySymbol = new Map<string, Record<string, unknown>>();
  for (const order of recentOrders) {
    const symbol = String(order.symbol ?? "");
    if (symbol && !ordersBySymbol.has(symbol)) {
      ordersBySymbol.set(symbol, order);
    }
  }
  const targetRows = targets.targets.map((row) => {
    const symbol = String(row.code ?? "");
    const liveOrder = ordersBySymbol.get(symbol);
    return {
      ...row,
      sent_order_id: row.sent_order_id ?? liveOrder?.broker_order_id ?? null,
      sent_status: row.sent_status ?? liveOrder?.order_status ?? (String(row.action ?? "").startsWith("SKIP_") ? row.action : null),
      sent_price: row.sent_price ?? liveOrder?.price ?? null,
      dealt_qty: liveOrder?.dealt_qty ?? null,
      dealt_avg_price: liveOrder?.dealt_avg_price ?? null,
      order_updated_at: liveOrder?.updated_at ?? null,
      order_remark: liveOrder?.remark ?? null,
      order_type: liveOrder?.order_type ?? null,
      sent_error: row.sent_error ?? (String(row.action ?? "") === "SKIP_PRICE_LIMIT" ? priceLimitErrorLabel : null)
    };
  });
  const targetColumns = [
    { key: "signal_date", label: "Signal Date" },
    { key: "rank", label: "Rank" },
    { key: "code", label: "Code" },
    { key: "name", label: "Name" },
    { key: "close", label: "Snapshot Close" },
    { key: "buy_order_qty", label: "Planned Buy Qty" },
    { key: "buy_limit_price", label: "Planned Buy Price" },
    { key: "sent_price", label: "Sent Price" },
    { key: "sent_status", label: "Sent Status" },
    { key: "sent_order_id", label: "Order ID" },
    { key: "dealt_qty", label: "Dealt Qty" },
    { key: "order_updated_at", label: "Order Updated" },
    { key: "sent_error", label: "Error" }
  ];
  const orderColumns = [
    { key: "broker_order_id", label: "Order ID" },
    { key: "market", label: "Market" },
    { key: "symbol", label: "Symbol" },
    { key: "side", label: "Side" },
    { key: "order_type", label: "Type" },
    { key: "order_status", label: "Status" },
    { key: "quantity", label: "Qty" },
    { key: "price", label: "Price" },
    { key: "dealt_qty", label: "Dealt Qty" },
    { key: "dealt_avg_price", label: "Dealt Avg Price" },
    { key: "created_at", label: "Created At" },
    { key: "updated_at", label: "Updated At" },
    { key: "remark", label: "Remark" }
  ];
  const historyColumns = [
    { key: "recorded_at", label: "Recorded At" },
    { key: "status", label: "Status" },
    { key: "score_signal_date", label: "Signal Date" },
    { key: "placed_order_ids", label: "Placed Order IDs" },
    { key: "skipped_symbols", label: "Skipped Symbols" },
    { key: "message", label: "Message" }
  ];
  const pricingHint =
    "Snapshot close and planned buy price come from the current signal snapshot. If the gateway accepts a different fallback price, the actual sent price and order status are shown in the same row.";

  return (
    <Shell
      title={copy.paper.title}
      subtitle={copy.paper.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <AutoRefresh intervalSeconds={15} />
      {flash ? <p className={`banner banner-${flash.tone}`}>{flash.text}</p> : null}
      {!gateway.healthy ? <p className="banner banner-error">{copy.paper.gatewayOffline}</p> : null}
      {overview.live_error ? <p className="banner banner-error">{String(overview.live_error)}</p> : null}

      <section className="metrics-grid">
        <MetricCard label={copy.paper.daemon} value={daemon.status_label} hint={daemon.container_name ?? "—"} />
        <MetricCard label={copy.paper.gateway} value={gateway.healthy ? copy.common.live : copy.common.checkNeeded} hint={gateway.base_url} />
        <MetricCard label={copy.paper.latestSignal} value={formatDate(state.score_signal_date, user.locale)} hint={formatDate(overview.targets.latest_signal_date, user.locale)} />
        <MetricCard label={copy.paper.lastSync} value={String(state.last_status ?? "—")} hint={formatDateTime(state.last_success_at ?? state.last_attempt_at, user.locale)} />
        <MetricCard label={copy.paper.targetRows} value={formatNumber(targets.rows, user.locale)} hint={copy.paper.targetsHint} />
        <MetricCard label={copy.paper.openPositions} value={formatNumber(overview.live_positions_count, user.locale)} hint={formatDisplayValue(liveSummary.open_positions, { locale: user.locale, key: "open_positions" })} />
        <MetricCard label={copy.paper.openOrders} value={formatNumber(overview.live_orders_count, user.locale)} hint={formatDisplayValue(state.active_order_count, { locale: user.locale, key: "active_order_count" })} />
        <MetricCard label={copy.paper.totalPnl} value={formatDisplayValue(liveSummary.total_pnl, { locale: user.locale, key: "total_pnl" })} hint={formatDisplayValue(liveSummary.market_value, { locale: user.locale, key: "market_value" })} />
      </section>

      <section className="two-col-grid">
        <Panel title={copy.paper.controls} aside={<span className={`pill ${daemon.is_running ? "live" : "warn"}`}>{daemon.status_label}</span>}>
          <div className="stack">
            <p className="panel-copy">{copy.paper.controlHint}</p>
            <div className="status-meta">
              <span>{copy.common.lastStateUpdate}: {formatDateTime(state.updated_at, user.locale)}</span>
              <span>{copy.paper.latestSignal}: {formatDate(state.score_signal_date, user.locale)}</span>
              <span>{copy.paper.gateway}: {gateway.healthy ? copy.common.live : copy.common.checkNeeded}</span>
              <span>Agent: {gateway.agent_id}</span>
            </div>
            {renderControlButtons({
              target: "paper",
              isAdmin,
              canStart: daemon.can_start,
              canStop: daemon.can_stop,
              startLabel: copy.paper.startAction,
              stopLabel: copy.paper.stopAction
            })}
          </div>
        </Panel>

        <Panel title={copy.paper.daemonLog} aside={<span className="pill">{daemon.log_source ?? "—"}</span>}>
          <pre className="log-console">{daemon.log_lines.join("\n") || copy.common.noLogs}</pre>
        </Panel>
      </section>

      <Panel title={copy.paper.strategyTargets}>
        <p className="panel-copy">{pricingHint}</p>
        <DataTable
          rows={targetRows}
          columns={targetColumns}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>

      <section className="two-col-grid">
        <Panel title={copy.paper.livePositions}>
          <DataTable
            rows={positions.positions}
            columns={["market", "symbol", "quantity", "avg_cost", "last_price", "market_value", "realized_pnl", "unrealized_pnl"]}
            emptyLabel={positions.error ?? copy.common.noRows}
            locale={user.locale}
          />
        </Panel>

        <Panel title={copy.paper.recentOrders}>
          <DataTable
            rows={orders.orders}
            columns={orderColumns}
            emptyLabel={orders.error ?? copy.common.noRows}
            locale={user.locale}
          />
        </Panel>
      </section>

      <Panel title={copy.paper.syncHistory} aside={<span className="pill">{copy.paper.historyHint}</span>}>
        <DataTable
          rows={history.history}
          columns={historyColumns}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>
    </Shell>
  );
}
