import { createHmac, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { NextRequest } from "next/server";

import { PanelLocale, normalizeLocale } from "@/lib/i18n";

export const SESSION_COOKIE = "aistockcn_panel_session";

type StoredPanelUser = {
  username: string;
  password: string;
  locale?: string;
  display_name?: string;
  role?: string;
};

export type PanelRole = "admin" | "viewer";

export type PanelUser = {
  username: string;
  locale: PanelLocale;
  displayName: string;
  role: PanelRole;
};

function requiredEnv(name: string) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required auth env: ${name}`);
  }
  return value;
}

function authSecret() {
  return requiredEnv("PANEL_AUTH_SECRET");
}

function tokenMatches(a: string, b: string) {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  if (left.length !== right.length) {
    return false;
  }
  return timingSafeEqual(left, right);
}

function signedValue(value: string, secret: string) {
  return createHmac("sha256", secret).update(value).digest("hex");
}

function normalizeRole(value?: string): PanelRole {
  return value === "admin" ? "admin" : "viewer";
}

function sanitizeUser(user: StoredPanelUser): PanelUser {
  return {
    username: user.username,
    locale: normalizeLocale(user.locale),
    displayName: user.display_name?.trim() || user.username,
    role: normalizeRole(user.role)
  };
}

function usersFilePath() {
  return process.env.PANEL_USERS_FILE?.trim();
}

function loadUsers(): StoredPanelUser[] {
  const filePath = usersFilePath();
  if (filePath && existsSync(filePath)) {
    const parsed = JSON.parse(readFileSync(filePath, "utf8")) as StoredPanelUser[];
    return parsed.filter((user) => user?.username && user?.password);
  }

  const fallbackUsername = process.env.PANEL_USERNAME;
  const fallbackPassword = process.env.PANEL_PASSWORD;
  if (!fallbackUsername || !fallbackPassword) {
    throw new Error("No panel users configured. Provide PANEL_USERS_FILE or fallback PANEL_USERNAME/PANEL_PASSWORD.");
  }

  return [
    {
      username: fallbackUsername,
      password: fallbackPassword,
      locale: "en",
      display_name: fallbackUsername,
      role: "admin"
    }
  ];
}

function findStoredUser(username: string) {
  return loadUsers().find((user) => user.username === username);
}

function passwordMatches(candidate: string, expected: string) {
  return tokenMatches(candidate, expected);
}

export function createSessionToken(username: string, secret: string) {
  const payload = Buffer.from(username, "utf8").toString("base64url");
  const signature = signedValue(payload, secret);
  return `${payload}.${signature}`;
}

function usernameFromSessionToken(token: string, secret: string) {
  const [payload, signature] = token.split(".");
  if (!payload || !signature) {
    return null;
  }

  const expected = signedValue(payload, secret);
  if (!tokenMatches(signature, expected)) {
    return null;
  }

  try {
    return Buffer.from(payload, "base64url").toString("utf8");
  } catch {
    return null;
  }
}

export async function getCurrentUser() {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) {
    return null;
  }

  const username = usernameFromSessionToken(session, authSecret());
  if (!username) {
    return null;
  }

  const storedUser = findStoredUser(username);
  return storedUser ? sanitizeUser(storedUser) : null;
}

export async function isAuthenticated() {
  return (await getCurrentUser()) !== null;
}

export async function requireAuth() {
  const user = await getCurrentUser();
  if (!user) {
    redirect("/login");
  }
  return user;
}

export async function requireAdmin() {
  const user = await requireAuth();
  if (user.role !== "admin") {
    redirect("/batch?error=forbidden");
  }
  return user;
}

export function authenticateUser(username: string, password: string) {
  const storedUser = findStoredUser(username);
  if (!storedUser) {
    return null;
  }

  return passwordMatches(password, storedUser.password) ? sanitizeUser(storedUser) : null;
}

function firstHeaderValue(value: string | null) {
  return value?.split(",")[0]?.trim() || null;
}

function normalizeOrigin(origin: string) {
  return origin.replace(/\/+$/, "");
}

function normalizeHostname(value: string) {
  return value.trim().replace(/^\[/, "").replace(/\]$/, "").split(":")[0].toLowerCase();
}

function isLocalHostname(value: string) {
  const hostname = normalizeHostname(value);
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function requestOrigin(request: NextRequest) {
  const forwardedHost = firstHeaderValue(request.headers.get("x-forwarded-host"));
  const host = forwardedHost ?? request.headers.get("host") ?? "localhost:3030";
  const forwardedProto = firstHeaderValue(request.headers.get("x-forwarded-proto"));
  const proto = forwardedProto ?? (isLocalHostname(host) ? "http" : "https");
  return normalizeOrigin(`${proto}://${host}`);
}

export function appOrigin(request: NextRequest) {
  const origin = requestOrigin(request);
  const configuredUrl = process.env.PANEL_PUBLIC_URL?.trim();
  if (!configuredUrl) {
    return origin;
  }

  const configuredOrigin = normalizeOrigin(configuredUrl);
  try {
    const requestHostname = new URL(origin).hostname;
    const configuredHostname = new URL(configuredOrigin).hostname;
    if (isLocalHostname(requestHostname) && !isLocalHostname(configuredHostname)) {
      return origin;
    }
  } catch {
    return configuredOrigin;
  }

  return configuredOrigin;
}

export function useSecureCookies(request: NextRequest) {
  return appOrigin(request).startsWith("https://");
}

export function sessionSecret() {
  return authSecret();
}
