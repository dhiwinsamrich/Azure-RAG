/**
 * Proxies corpus uploads to the API.
 *
 * The multipart body is streamed through unchanged so the browser never needs
 * the API's address or credentials. `mode` selects preview (parse + chunk
 * only, free) or upload (also embed and index).
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function POST(request: Request) {
  const incoming = await request.formData();
  const mode = String(incoming.get("mode") ?? "preview");
  const file = incoming.get("file");

  if (!(file instanceof File)) {
    return Response.json({ detail: "no file supplied" }, { status: 400 });
  }

  const body = new FormData();
  body.append("file", file, file.name);
  if (mode === "upload") body.append("index", "true");

  const path = mode === "upload" ? "/api/ingest/upload" : "/api/ingest/preview";

  try {
    const upstream = await fetch(`${API_BASE}${path}`, { method: "POST", body });
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

export async function GET() {
  try {
    const upstream = await fetch(`${API_BASE}/api/documents`, { cache: "no-store" });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json([], { status: 200 });
  }
}
