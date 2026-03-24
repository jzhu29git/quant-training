import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { appOrigin, getCurrentUser } from "@/lib/auth";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.redirect(new URL("/login", appOrigin(request)), { status: 303 });
  }

  const url = new URL(request.url);
  const query = url.searchParams.toString();

  const response = await fetch(`${API_BASE_URL}/api/data/explorer/export?${query}`, {
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    return NextResponse.json({ error: body || "Export failed." }, { status: response.status });
  }

  const headers = new Headers();
  const contentType = response.headers.get("content-type");
  const contentDisposition = response.headers.get("content-disposition");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  if (contentDisposition) {
    headers.set("content-disposition", contentDisposition);
  }

  return new NextResponse(response.body, {
    status: 200,
    headers
  });
}
