// Session recorder for the staging site. It records this page (clicks, mouse movement, and
// DOM changes) in whatever browser opens it, including the OpenAI-hosted browser, and sends
// the events to /api/rec on this same host, so the network allowlist still needs one entry.
(() => {
  const lib = window.rrwebRecord;
  const record = lib && (lib.record || (lib.default && lib.default.record));
  if (!record) return;

  const build = location.pathname.split("/")[2] || "root";
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const id = `${stamp}-${build}-${Math.random().toString(36).slice(2, 8)}`;
  let buffer = [];
  let seq = 0;

  record({ emit: (event) => buffer.push(event), maskAllInputs: true });

  function flush() {
    if (buffer.length === 0) return;
    const body = JSON.stringify({ id, seq: seq++, events: buffer });
    buffer = [];
    fetch("/api/rec", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      keepalive: body.length < 60000,
    }).catch(() => {});
  }

  setInterval(flush, 2000);
  addEventListener("pagehide", flush);
})();
