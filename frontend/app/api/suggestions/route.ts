/** Proxies starter-question requests to the API. */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function GET(request: Request) {
  const { search } = new URL(request.url);
  try {
    const upstream = await fetch(`${API_BASE}/api/suggestions${search}`, { cache: "no-store" });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return Response.json(
      { detail: `API unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }
}
