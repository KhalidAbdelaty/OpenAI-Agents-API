const Player = window.rrwebPlayer.default || window.rrwebPlayer.Player || window.rrwebPlayer;
const pick = document.getElementById("pick");
const status = document.getElementById("status");
const target = document.getElementById("player");
const params = new URLSearchParams(location.search);

const label = (id) => {
  const build = (id.match(/ns-\d+/) || [""])[0];
  return build === "ns-1041" ? "Build ns-1041 (buggy release)" : build === "ns-1042" ? "Build ns-1042 (fix)" : id;
};

async function loadList() {
  const response = await fetch("/api/rec", { cache: "no-store" });
  const { recordings } = await response.json();
  pick.innerHTML = recordings.length
    ? recordings.map((id) => `<option value="${id}">${id}</option>`).join("")
    : "<option>No recordings yet</option>";
  const wanted = params.get("id");
  if (wanted && recordings.includes(wanted)) pick.value = wanted;
  document.getElementById("load").disabled = recordings.length === 0;
}

const sequence = (params.get("ids") || "").split(",").filter(Boolean);
if (sequence.length) {
  pick.hidden = true;
  document.getElementById("load").hidden = true;
}

async function play(id, onFinish) {
  status.textContent = "Loading...";
  const response = await fetch(`/api/rec?id=${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!response.ok) {
    status.textContent = `Could not load ${id}`;
    return;
  }
  const { events } = await response.json();
  target.innerHTML = "";
  const player = new Player({
    target,
    props: { events, width: 1180, height: 620, autoPlay: true, showController: !sequence.length, skipInactive: true },
  });
  if (onFinish) player.getReplayer().on("finish", onFinish);
  status.textContent = label(id);
}

async function playSequence(ids) {
  for (let i = 0; i < ids.length; i++) {
    await new Promise((resolve) => play(ids[i], () => setTimeout(resolve, 1500)));
  }
  status.textContent += " (end)";
}

document.getElementById("load").addEventListener("click", () => play(pick.value));
loadList().catch((error) => { status.textContent = `Could not list recordings: ${error}`; });

if (sequence.length) playSequence(sequence);
