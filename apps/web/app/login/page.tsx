import { redirect } from "next/navigation";

import { isAuthenticated } from "@/lib/auth";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams
}: {
  searchParams?: Promise<{ error?: string }>;
}) {
  if (await isAuthenticated()) {
    redirect("/overview");
  }

  const params = (await searchParams) ?? {};
  const showError = params.error === "invalid";
  const en = getMessages("en");

  return (
    <div className="auth-shell">
      <section className="auth-card">
        <form action="/auth/login" method="post" className="auth-form">
          <label className="auth-label" htmlFor="username">
            {en.login.username}
          </label>
          <input
            className="auth-input"
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            placeholder={en.login.username}
            required
          />

          <label className="auth-label" htmlFor="password">
            {en.login.password}
          </label>
          <input
            className="auth-input"
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder={en.login.password}
            required
          />

          {showError ? (
            <p className="auth-error">{en.login.error}</p>
          ) : null}

          <button className="auth-submit" type="submit">
            {en.login.submit}
          </button>
        </form>
      </section>
    </div>
  );
}
