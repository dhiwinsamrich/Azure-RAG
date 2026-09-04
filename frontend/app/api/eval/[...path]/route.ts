/**
 * Proxies evaluation requests to the backend API.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const url = new URL(request.url);
  const search = url.search;
  const subpath = path.map(encodeURIComponent).join("/");

  try {
    const upstream = await fetch(`${API_BASE}/api/eval/${subpath}${search}`, {
      cache: "no-store",
    });
    const text = await upstream.text();
    return new Response(text, {
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
