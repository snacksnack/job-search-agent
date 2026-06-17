const APPLIED = new Set(["applied", "interviewing", "offer", "rejected"]);

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window.__tt);
  window.__tt = setTimeout(() => t.classList.remove("show"), 2200);
}

// Serialize the current filter state to a query string so it survives a hop to
// the Table view (and back). `sort`/`dir` are owned by the table; we carry them
// through untouched so a round-trip preserves the chosen column sort.
function currentParams() {
  const p = new URLSearchParams();
  const q = document.getElementById("search").value.trim();
  if (q) p.set("q", q);
  if (document.getElementById("showApplied").checked) p.set("applied", "1");
  if (document.getElementById("showHidden").checked) p.set("hidden", "1");
  const prep = document.getElementById("prepFilter").value;
  if (prep && prep !== "all") p.set("prep", prep);
  const url = new URLSearchParams(location.search);
  if (url.get("sort")) p.set("sort", url.get("sort"));
  if (url.get("dir")) p.set("dir", url.get("dir"));
  return p;
}

function refreshViewToggle() {
  const link = document.getElementById("tableLink");
  if (!link) return;
  const qs = currentParams().toString();
  link.href = "/table" + (qs ? "?" + qs : "");
}

function initFromParams() {
  const url = new URLSearchParams(location.search);
  if (url.has("q")) document.getElementById("search").value = url.get("q");
  document.getElementById("showApplied").checked = url.get("applied") === "1";
  document.getElementById("showHidden").checked = url.get("hidden") === "1";
  const prep = url.get("prep");
  if (prep) document.getElementById("prepFilter").value = prep;
}

function applyFilters() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const showApplied = document.getElementById("showApplied").checked;
  const showHidden = document.getElementById("showHidden").checked;
  const prepFilter = document.getElementById("prepFilter").value;
  let shown = 0;
  document.querySelectorAll(".card").forEach(c => {
    const st = c.dataset.status;
    let visible = !q || c.dataset.search.includes(q);
    if (st === "hidden" && !showHidden) visible = false;
    if (APPLIED.has(st) && !showApplied) visible = false;
    if (prepFilter === "has" && c.dataset.prep !== "1") visible = false;
    if (prepFilter === "none" && c.dataset.prep === "1") visible = false;
    c.style.display = visible ? "" : "none";
    if (visible) shown++;
  });
  document.getElementById("shownCount").textContent = shown;
  refreshViewToggle();
}

async function decide(id, status, el) {
  try {
    const res = await fetch("/api/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, status })
    });
    if (!res.ok) throw new Error(await res.text());
    const card = el.closest(".card");
    card.dataset.status = status;
    card.classList.toggle("hidden-card", status === "hidden");
    card.classList.toggle("applied-card", APPLIED.has(status));
    const badge = card.querySelector(".status");
    badge.className = "status status-" + status;
    badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    toast(status === "new" ? "Restored" : ("Marked " + status));
    applyFilters();
  } catch (e) { toast("Error: " + e.message); }
}

async function queueCover(id, btn) {
  try {
    const res = await fetch("/api/queue-cover-letter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    btn.textContent = "Queued ✓";
    toast("Cover letter queued (" + data.queued + " in queue). Run 'draft my queued cover letters' in Cowork.");
  } catch (e) { toast("Error: " + e.message); }
}

async function queuePrep(id, btn) {
  try {
    const res = await fetch("/api/queue-interview-prep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    btn.textContent = "Queued ✓";
    toast("Interview prep queued (" + data.queued + " in queue). Run 'do my queued interview prep' in Cowork.");
  } catch (e) { toast("Error: " + e.message); }
}

async function resetState() {
  if (!confirm("Clear ALL applied/hidden decisions? This rewrites data/state.json.")) return;
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    toast("State cleared");
    setTimeout(() => location.reload(), 600);
  } catch (e) { toast("Error: " + e.message); }
}

initFromParams();
applyFilters();
