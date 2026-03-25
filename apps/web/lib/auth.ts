import { createHmac, scryptSync, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { NextRequest } from "next/server";

import { PanelLocale, normalizeLocale } from "@/lib/i18n";

export const SESSION_COOKIE = "aistockcn_panel_session";

type StoredPanelUser = {
  username: string;
  password_hash?: string;
  password?: string;
  locale?: string;
  display_name?: string;
  role?: string;
};

type LoadedPanelUser = {
  username: string;
  password_hash: string;
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

function tokenMatches(a: string | Buffer, b: string | Buffer) {
  const left = typeof a === "string" ? Buffer.from(a) : a;
  const right = typeof b === "string" ? Buffer.from(b) : b;
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

function sanitizeUser(user: LoadedPanelUser): PanelUser {
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

function normalizeStoredUser(user: StoredPanelUser): LoadedPanelUser | null {
  const username = String(user?.username ?? "").trim();
  const passwordHash = String(user?.password_hash ?? "").trim();
  if (!username || !passwordHash) {
    return null;
  }
  return {
    username,
    password_hash: passwordHash,
    locale: user.locale,
    display_name: user.display_name,
    role: user.role
  };
}

function loadUsers(): LoadedPanelUser[] {
  const filePath = usersFilePath();
  if (filePath && existsSync(filePath)) {
    const parsed = JSON.parse(readFileSync(filePath, "utf8")) as StoredPanelUser[];
    if (!Array.isArray(parsed)) {
      throw new Error(`Panel users file ${filePath} must contain a JSON array.`);
    }
    if (parsed.some((user) => user?.username && user?.password && !user?.password_hash)) {
      throw new Error(`Panel users file ${filePath} still uses plaintext passwords. Replace password with password_hash.`);
    }
    const users = parsed
      .map((user) => normalizeStoredUser(user))
      .filter((user): user is LoadedPanelUser => user !== null);
    if (users.length === 0) {
      throw new Error(`No panel users configured in ${filePath}. Provide username plus password_hash entries.`);
    }
    return users;
  }

  const fallbackUsername = process.env.PANEL_USERNAME?.trim();
  const fallbackPasswordHash = process.env.PANEL_PASSWORD_HASH?.trim();
  if (fallbackUsername && process.env.PANEL_PASSWORD && !fallbackPasswordHash) {
    throw new Error("Legacy PANEL_PASSWORD is no longer supported. Use PANEL_PASSWORD_HASH.");
  }
  if (!fallbackUsername || !fallbackPasswordHash) {
    throw new Error("No panel users configured. Provide PANEL_USERS_FILE or fallback PANEL_USERNAME/PANEL_PASSWORD_HASH.");
  }

  return [
    {
      username: fallbackUsername,
      password_hash: fallbackPasswordHash,
      locale: "en",
      display_name: fallbackUsername,
      role: "admin"
    }
  ];
}

function findStoredUser(username: string) {
  return loadUsers().find((user) => user.username === username);
}

function passwordMatches(candidate: string, expectedHash: string) {
  const [algorithm, saltHex, digestHex] = expectedHash.split("$");
  if (algorithm !== "scrypt" || !saltHex || !digestHex) {
    return false;
  }

  try {
    const salt = Buffer.from(saltHex, "hex");
    const expectedDigest = Buffer.from(digestHex, "hex");
    if (salt.length === 0 || expectedDigest.length === 0) {
      return false;
    }
    const candidateDigest = scryptSync(candidate, salt, expectedDigest.length, {
      N: 16384,
      r: 8,
      p: 1
    });
    return tokenMatches(candidateDigest, expectedDigest);
  } catch {
    return false;
  }
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

  return passwordMatches(password, storedUser.password_hash) ? sanitizeUser(storedUser) : null;
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
