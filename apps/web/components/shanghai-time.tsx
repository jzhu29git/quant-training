"use client";

import { useEffect, useState } from "react";

import type { PanelLocale } from "@/lib/i18n";

const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

function localeTag(locale: PanelLocale) {
  return locale === "zh-Hant" ? "zh-Hant-HK" : "en-US";
}

function formatShanghaiTime(value: Date, locale: PanelLocale) {
  return new Intl.DateTimeFormat(localeTag(locale), {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: SHANGHAI_TIME_ZONE,
    timeZoneName: "short"
  }).format(value);
}

export function ShanghaiTime({
  locale,
  label,
  initialValue
}: {
  locale: PanelLocale;
  label: string;
  initialValue: string;
}) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    const updateValue = () => setValue(formatShanghaiTime(new Date(), locale));
    updateValue();
    const timerId = window.setInterval(updateValue, 1000);
    return () => window.clearInterval(timerId);
  }, [locale]);

  return (
    <span className="shell-time">
      <span className="shell-time-label">{label}:</span>{" "}
      <time className="shell-time-value" suppressHydrationWarning>
        {value}
      </time>
    </span>
  );
}
