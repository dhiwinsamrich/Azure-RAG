/**
 * Route handler proxying the chat stream.
 *
 * The browser never talks to the API directly: the token and endpoint stay on
 * the server, and the SSE body is piped through untouched so the client sees
 * the same typed event stream.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.text();

  const upstream = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(
      `event: error\ndata: ${JSON.stringify({
        message: `API returned ${upstream.status}`,
      })}\n\n`,
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    );
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
