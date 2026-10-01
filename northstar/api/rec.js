// Stores and serves session recordings from the private Blob store connected to this project.
// POST /api/rec            one batch of rrweb events from rec.js
// GET  /api/rec            list of recording ids, newest first
// GET  /api/rec?id=<id>    every event of one recording, in order
import { get, list, put } from "@vercel/blob";

const PREFIX = "recordings/";
const MAX_BODY = 5_000_000;
const ID_PATTERN = /^[\w-]{10,100}$/;

export async function POST(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) return new Response("Batch too large", { status: 413 });

  let batch;
  try {
    batch = JSON.parse(text);
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }
  const { id, seq, events } = batch;
  if (!ID_PATTERN.test(id || "") || !Number.isInteger(seq) || seq < 0 || !Array.isArray(events)) {
    return new Response("Invalid batch", { status: 400 });
  }

  const pathname = `${PREFIX}${id}/${String(seq).padStart(5, "0")}.json`;
  await put(pathname, JSON.stringify(events), {
    access: "private",
    contentType: "application/json",
    addRandomSuffix: false,
    allowOverwrite: true,
  });
  return Response.json({ ok: true });
}

export async function GET(request) {
  const id = new URL(request.url).searchParams.get("id");

  if (!id) {
    const { folders } = await list({ prefix: PREFIX, mode: "folded" });
    const ids = folders.map((folder) => folder.slice(PREFIX.length).replace(/\/$/, ""));
    return Response.json({ recordings: ids.sort().reverse() }, { headers: { "cache-control": "no-store" } });
  }

  if (!ID_PATTERN.test(id)) return new Response("Invalid id", { status: 400 });

  const parts = [];
  let cursor;
  do {
    const page = await list({ prefix: `${PREFIX}${id}/`, cursor });
    parts.push(...page.blobs.map((blob) => blob.pathname));
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);
  if (parts.length === 0) return new Response("Recording not found", { status: 404 });

  const events = [];
  for (const pathname of parts.sort()) {
    const result = await get(pathname, { access: "private", useCache: false });
    if (result && result.statusCode === 200) {
      events.push(...JSON.parse(await new Response(result.stream).text()));
    }
  }
  events.sort((a, b) => a.timestamp - b.timestamp);
  return Response.json({ id, events }, { headers: { "cache-control": "no-store" } });
}
