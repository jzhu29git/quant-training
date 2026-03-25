import { NextRequest, NextResponse } from "next/server";

import { appOrigin, getCurrentUser } from "@/lib/auth";
import { API_BASE_URL } from "@/lib/api";

function controlRedirect(request: NextRequest, target: string, query: string) {
  const path = target === "paper" ? "/paper" : "/batch";
  return NextResponse.redirect(new URL(`${path}${query}`, appOrigin(request)), { status: 303 });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.redirect(new URL("/login", appOrigin(request)), { status: 303 });
  }
  if (user.role !== "admin") {
    return controlRedirect(request, "batch", "?error=forbidden");
  }

  const formData = await request.formData();
  const action = String(formData.get("action") ?? "").trim();
  const rawTarget = String(formData.get("target") ?? "step1").trim();
  // Keep bookmarked forms from the pre-renumbered UI working.
  const target = rawTarget === "step12" ? "step1" : rawTarget;
  const profile = String(formData.get("profile") ?? "").trim();

  const adminKey = process.env.PANEL_ADMIN_KEY?.trim();
  if (!adminKey) {
    return controlRedirect(request, target, "?error=control_unavailable");
  }

  if (action !== "start" && action !== "stop") {
    return controlRedirect(request, target, "?error=invalid_action");
  }

  let endpoint: string | null = null;
  if (target === "pipeline") {
    endpoint = `/api/control/pipeline/${action}`;
  } else if (["step1", "step2", "step3", "step4", "step5"].includes(target)) {
    endpoint = `/api/control/step/${target}/${action}${profile ? `?profile=${encodeURIComponent(profile)}` : ""}`;
  } else if (target === "paper") {
    endpoint = `/api/control/paper/${action}`;
  } else if (target === "batch") {
    endpoint = `/api/control/batch/${action}`;
  }
  if (!endpoint) {
    return controlRedirect(request, target, "?error=invalid_action");
  }

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: "POST",
      headers: {
        "x-panel-admin-key": adminKey
      },
      cache: "no-store"
    });

    const payload = (await response.json()) as { code?: string; detail?: { code?: string } };
    if (!response.ok) {
      const code = payload.detail?.code ?? payload.code ?? "control_failed";
      return controlRedirect(request, target, `?error=${encodeURIComponent(code)}&target=${encodeURIComponent(target)}`);
    }

    const code = payload.code ?? (action === "start" ? "started" : "stopped");
    return controlRedirect(request, target, `?notice=${encodeURIComponent(code)}&target=${encodeURIComponent(target)}`);
  } catch {
    return controlRedirect(request, target, "?error=control_failed");
  }
}
