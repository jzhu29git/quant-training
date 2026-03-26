import type { PanelRole } from "@/lib/auth";
import type { Route } from "next";
import Link from "next/link";
import { ReactNode } from "react";

import { PanelLocale, getMessages } from "@/lib/i18n";
import { ShanghaiTime } from "@/components/shanghai-time";

function localeTag(locale: PanelLocale) {
  return locale === "zh-Hant" ? "zh-Hant-HK" : "en-US";
}

export function Shell({
  title,
  subtitle,
  children,
  locale,
  username,
  role
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  locale: PanelLocale;
  username: string;
  role: PanelRole;
}) {
  const copy = getMessages(locale);
  const resolvedRoleLabel = role === "admin" ? copy.shell.admin : copy.shell.viewer;
  const shanghaiTimeNow = new Intl.DateTimeFormat(localeTag(locale), {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
    timeZoneName: "short"
  }).format(new Date());
  const navItem = (href: Route, label: string) => ({ href, label });
  const navItems: Array<{ href: Route; label: string }> = [
    navItem("/overview", copy.shell.nav.overview),
    navItem("/batch", copy.shell.nav.batch),
    navItem("/data", copy.shell.nav.data),
    navItem("/models", copy.shell.nav.models),
    navItem("/picks", copy.shell.nav.picks),
    navItem("/paper", copy.shell.nav.paper),
    ...(role === "admin" ? [navItem("/admin", copy.shell.nav.admin)] : [])
  ];

  return (
    <div className="shell">
      <header className="hero">
        <div className="hero-copy">
          <p className="eyebrow">{copy.brand}</p>
          <h1>{title}</h1>
          <p className="hero-subtitle">{subtitle}</p>
          <p className="hero-subtitle">
            {copy.shell.signedInAs}: {username} · {copy.localeLabel} · {resolvedRoleLabel} ·{" "}
            <ShanghaiTime locale={locale} label={copy.shell.shanghaiTime} initialValue={shanghaiTimeNow} />
          </p>
        </div>
        <nav className="nav">
          {navItems.map((item) => (
            <Link key={item.href} href={item.href} className="nav-link">
              {item.label}
            </Link>
          ))}
          <form action="/auth/logout" method="post">
            <button type="submit" className="nav-link nav-button">
              {copy.shell.logout}
            </button>
          </form>
        </nav>
      </header>
      <main className="page-content">{children}</main>
    </div>
  );
}
