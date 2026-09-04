import { NextResponse } from "next/server";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function GET() {
  try {
    const res = await fetch(`${API_BASE}/api/status`, { cache: "no-store" });
    if (!res.ok) {
      return NextResponse.json({ search_backend: "azure", default_config_id: "hybrid_semantic" });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ search_backend: "azure", default_config_id: "hybrid_semantic" });
  }
}
