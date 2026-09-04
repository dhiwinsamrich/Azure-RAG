/** Fetches or deletes a document: its chunks, their embeddings, and its store record. */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string }> },
) {
  const { docId } = await params;
  try {
    const upstream = await fetch(
      `${API_BASE}/api/documents/${encodeURIComponent(docId)}/chunks`,
      { cache: "no-store" },
    );
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

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ docId: string }> },
) {
  const { docId } = await params;
  try {
    const upstream = await fetch(
      `${API_BASE}/api/documents/${encodeURIComponent(docId)}`,
      { method: "DELETE" },
    );
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

