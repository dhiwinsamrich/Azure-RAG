/**
 * Minimal SSE reader over fetch.
 *
 * EventSource cannot POST, and this stream carries four distinct event types
 * the UI renders differently - tokens, citations, validation verdicts and the
 * trace - so a bare token reader would not be enough.
 */
export type SseHandler = (event: string, data: unknown) => void;

export async function readSse(
  response: Response,
  onEvent: SseHandler,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("response has no body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    if (signal?.aborted) {
      await reader.cancel();
      return;
    }
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Events are separated by a blank line; a partial tail stays buffered.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let name = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
      }
      if (dataLines.length === 0) continue;
      try {
        onEvent(name, JSON.parse(dataLines.join("\n")));
      } catch {
        onEvent(name, dataLines.join("\n"));
      }
    }
  }
}
