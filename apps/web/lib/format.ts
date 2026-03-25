import type { PanelLocale } from "@/lib/i18n";

const EMPTY_VALUE = "—";
const PANEL_DISPLAY_TIME_ZONE = "Asia/Shanghai";

type NumberOptions = {
  maximumFractionDigits?: number;
  minimumFractionDigits?: number;
  fallback?: string;
};

function localeTag(locale: PanelLocale) {
  return "en-US";
}

function isDateOnlyString(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value.trim());
}

function isDateTimeString(value: string) {
  const trimmed = value.trim();
  return (trimmed.includes("T") || trimmed.includes(" ")) && !Number.isNaN(Date.parse(trimmed));
}

function looksDateLike(value: string, key?: string) {
  const normalizedKey = (key ?? "").toLowerCase();
  if (
    normalizedKey === "date" ||
    normalizedKey.endsWith("_date") ||
    normalizedKey.endsWith("_at") ||
    normalizedKey.includes("date") ||
    normalizedKey.includes("time") ||
    normalizedKey.includes("updated") ||
    normalizedKey.includes("created") ||
    normalizedKey.includes("started") ||
    normalizedKey.includes("finished") ||
    normalizedKey.includes("recorded") ||
    normalizedKey.includes("generated")
  ) {
    return isDateOnlyString(value) || isDateTimeString(value);
  }
  return isDateOnlyString(value) || isDateTimeString(value);
}

function looksNumericString(value: string, key?: string) {
  const trimmed = value.trim();
  const normalizedKey = (key ?? "").toLowerCase();
  if (!/^-?\d+(\.\d+)?$/.test(trimmed)) {
    return false;
  }
  if (trimmed.includes(".")) {
    return true;
  }
  if (
    normalizedKey.includes("score") ||
    normalizedKey.includes("auc") ||
    normalizedKey.includes("accuracy") ||
    normalizedKey.includes("precision") ||
    normalizedKey.includes("recall") ||
    normalizedKey.includes("return") ||
    normalizedKey.includes("drawdown") ||
    normalizedKey.includes("rate") ||
    normalizedKey.includes("price") ||
    normalizedKey.includes("close") ||
    normalizedKey.includes("open") ||
    normalizedKey.includes("high") ||
    normalizedKey.includes("low") ||
    normalizedKey.includes("qty") ||
    normalizedKey.includes("count") ||
    normalizedKey.includes("rows") ||
    normalizedKey.includes("days") ||
    normalizedKey.includes("codes") ||
    normalizedKey.includes("value")
  ) {
    return true;
  }
  return false;
}

function hasAnyKeyword(key: string, keywords: string[]) {
  return keywords.some((keyword) => key.includes(keyword));
}

function numericDigitsForKey(key: string, value: number) {
  const normalizedKey = key.toLowerCase();
  if (
    hasAnyKeyword(normalizedKey, [
      "rank",
      "qty",
      "quantity",
      "rows",
      "cols",
      "count",
      "codes",
      "days",
      "rebalances",
      "horizon",
      "top_k",
      "top k",
      "limit"
    ])
  ) {
    return 0;
  }
  if (
    hasAnyKeyword(normalizedKey, [
      "price",
      "close",
      "open",
      "high",
      "low",
      "avg",
      "cost",
      "value",
      "cap",
      "notional",
      "pe",
      "pb",
      "ps",
      "pcf"
    ])
  ) {
    return 2;
  }
  if (
    hasAnyKeyword(normalizedKey, [
      "score",
      "auc",
      "accuracy",
      "precision",
      "recall",
      "rate",
      "return",
      "drawdown",
      "volatility",
      "bias",
      "pct",
      "turnover",
      "amplitude",
      "change",
      "pnl",
      "metric"
    ])
  ) {
    return 3;
  }
  if (Number.isInteger(value)) {
    return 0;
  }
  if (Math.abs(value) >= 1) {
    return 2;
  }
  return 3;
}

export function formatNumber(value: unknown, locale: PanelLocale, options: NumberOptions = {}) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return options.fallback ?? EMPTY_VALUE;
  }
  return new Intl.NumberFormat(localeTag(locale), {
    minimumFractionDigits: options.minimumFractionDigits ?? 0,
    maximumFractionDigits: options.maximumFractionDigits ?? 0
  }).format(value);
}

export function formatMetric(value: unknown, locale: PanelLocale, maximumFractionDigits = 3) {
  return formatNumber(value, locale, { maximumFractionDigits });
}

export function formatBytes(value: unknown, locale: PanelLocale) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return EMPTY_VALUE;
  }
  const mb = value / (1024 * 1024);
  if (mb < 1024) {
    return `${formatNumber(mb, locale, { maximumFractionDigits: 1 })} MB`;
  }
  return `${formatNumber(mb / 1024, locale, { maximumFractionDigits: 2 })} GB`;
}

export function formatDate(value: unknown, locale: PanelLocale) {
  if (!value) {
    return EMPTY_VALUE;
  }
  if (typeof value === "string" && isDateOnlyString(value)) {
    const date = new Date(`${value}T00:00:00Z`);
    return new Intl.DateTimeFormat(localeTag(locale), {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: PANEL_DISPLAY_TIME_ZONE
    }).format(date);
  }
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return typeof value === "string" ? value : EMPTY_VALUE;
  }
  return new Intl.DateTimeFormat(localeTag(locale), {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: PANEL_DISPLAY_TIME_ZONE
  }).format(date);
}

export function formatDateTime(value: unknown, locale: PanelLocale) {
  if (!value) {
    return EMPTY_VALUE;
  }
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return typeof value === "string" ? value : EMPTY_VALUE;
  }
  return new Intl.DateTimeFormat(localeTag(locale), {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: PANEL_DISPLAY_TIME_ZONE
  }).format(date);
}

export function formatDateRange(
  value:
    | {
        date_min?: string | null;
        date_max?: string | null;
      }
    | null
    | undefined,
  locale: PanelLocale,
  joiner?: string
) {
  const start = formatDate(value?.date_min, locale);
  const end = formatDate(value?.date_max, locale);
  return `${start} ${joiner ?? "to"} ${end}`;
}

export function formatDisplayValue(
  value: unknown,
  {
    locale,
    key
  }: {
    locale: PanelLocale;
    key?: string;
  }
): string {
  const normalizedKey = (key ?? "").toLowerCase();

  if (value === null || value === undefined || value === "") {
    return EMPTY_VALUE;
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => formatDisplayValue(item, { locale, key })).join(", ") : EMPTY_VALUE;
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return formatNumber(value, locale, { maximumFractionDigits: numericDigitsForKey(normalizedKey, value) });
  }
  if (value instanceof Date) {
    return formatDateTime(value, locale);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) {
      return EMPTY_VALUE;
    }
    if (looksDateLike(trimmed, normalizedKey)) {
      return isDateOnlyString(trimmed) ? formatDate(trimmed, locale) : formatDateTime(trimmed, locale);
    }
    if (looksNumericString(trimmed, normalizedKey)) {
      const numericValue = Number(trimmed);
      if (!Number.isNaN(numericValue)) {
        return formatNumber(numericValue, locale, {
          maximumFractionDigits: numericDigitsForKey(normalizedKey, numericValue)
        });
      }
    }
    return trimmed;
  }
  return JSON.stringify(value);
}
