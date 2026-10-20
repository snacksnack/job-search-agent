const APPLIED = new Set(["applied", "interviewing", "offer", "rejected"]);

// Which group the board is filtered to. The count chips and the two checkboxes are
// two synced controls for this one value: active (default) | applied | hidden | closed | all.
let view = "active";

// Default board view (RC1-523): open showing only the freshest, high-scoring active
// roles so the page is fast and focused. Every card is still in the DOM (instant
// search/sort/toggles), so the rest are one click away via the "show all" control.
// capLifted is set by that control and reset whenever the view changes.
const DEFAULT_CAP = 200;
const DEFAULT_SCORE_FLOOR = 60;
let capLifted = false;

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
  if (view !== "active") p.set("view", view);
  const prep = document.getElementById("prepFilter").value;
  if (prep && prep !== "all") p.set("prep", prep);
  // The board owns the date-added sort (its select); other column sorts belong to
  // the table and are carried through untouched so a round-trip preserves them.
  const sortSel = document.getElementById("sortSelect").value;
  const url = new URLSearchParams(location.search);
  if (sortSel !== "default") {
    p.set("sort", "added");
    p.set("dir", sortSel.endsWith("asc") ? "asc" : "desc");
  } else if (url.get("sort") && url.get("sort") !== "added") {
    p.set("sort", url.get("sort"));
    if (url.get("dir")) p.set("dir", url.get("dir"));
  }
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
  const prep = url.get("prep");
  if (prep) document.getElementById("prepFilter").value = prep;
  if (url.get("sort") === "added") {
    document.getElementById("sortSelect").value =
      url.get("dir") === "asc" ? "added-asc" : "added-desc";
  } else if (!url.get("sort")) {
    // RC1-523: default to newest-added so the capped default view is "the most
    // recent N" (best match breaks within-day ties, per applySortSelect).
    document.getElementById("sortSelect").value = "added-desc";
  }
  // Prefer explicit view; fall back to legacy applied=1/hidden=1 links.
  view = url.get("view") ||
    (url.get("applied") === "1" ? "applied" : url.get("hidden") === "1" ? "hidden" : "active");
  syncControls();
}

// Board sorting: default is the server-rendered order (priority, then match desc);
// the select re-orders cards by data-added, empties last (like the table's posted
// column). The original order is captured once for restore.
//
// foundDate is day-granularity and a sweep can add ~100 roles at once, so a date
// sort alone leaves one big same-date block in no defined order. Match percent
// breaks the tie, descending in BOTH directions — "oldest added" still wants the
// best match first inside a day. Sorting from initialCardOrder rather than live DOM
// keeps that deterministic: reading the DOM meant the input was the previous
// sort's output, so within-date order survived only by stable-sort accident.
let initialCardOrder = null;
function applySortSelect() {
  const wrap = document.getElementById("cards");
  if (!initialCardOrder) initialCardOrder = Array.from(wrap.querySelectorAll(".card"));
  const v = document.getElementById("sortSelect").value;
  let cards;
  if (v === "default") {
    cards = initialCardOrder;
  } else {
    const dir = v.endsWith("asc") ? 1 : -1;
    cards = initialCardOrder.slice().sort((a, b) => {
      const va = a.dataset.added || "", vb = b.dataset.added || "";
      if (va === "" && vb !== "") return 1;      // undated cards sink either way
      if (vb === "" && va !== "") return -1;
      const cmp = va < vb ? -1 : (va > vb ? 1 : 0);
      if (cmp !== 0) return dir === 1 ? cmp : -cmp;
      return (+b.dataset.score || 0) - (+a.dataset.score || 0);
    });
  }
  cards.forEach(c => wrap.appendChild(c));
  applyFilters();   // re-apply the cap in the new order
}

// Reflect the current view in the checkboxes (mutually exclusive) and highlight the
// matching count chip.
function syncControls() {
  document.getElementById("showApplied").checked = view === "applied";
  document.getElementById("showHidden").checked = view === "hidden";
  document.querySelectorAll(".cfilter").forEach(b =>
    b.classList.toggle("active", b.dataset.view === view));
}

function setView(v) {
  view = v;
  capLifted = false;   // returning to a view re-applies the default cap
  syncControls();
  applyFilters();
}

// Checkbox handler: checking a box focuses that group; unchecking returns to active.
function onToggle(group, checked) {
  setView(checked ? group : "active");
}

function applyFilters() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const prepFilter = document.getElementById("prepFilter").value;
  // The capped default view applies only to the plain active view: no search, no
  // prep filter, cap not lifted. Any explicit filtering shows all matches.
  const capped = view === "active" && !q && prepFilter === "all" && !capLifted;
  const candidates = [];
  document.querySelectorAll(".card").forEach(c => {
    const st = c.dataset.status;
    const isApplied = APPLIED.has(st);
    const isHidden = st === "hidden";
    const isClosed = c.dataset.closed === "1";
    // Group visibility follows the active view.
    let inView;
    if (view === "all") inView = true;
    else if (view === "applied") inView = isApplied;  // applied stays visible even if the listing closed
    else if (view === "hidden") inView = isHidden;
    else if (view === "closed") inView = isClosed;
    else inView = !isApplied && !isHidden && !isClosed;  // active: actionable roles only
    let visible = inView && matchesSearch(c.dataset.search, q);
    if (prepFilter === "has" && c.dataset.prep !== "1") visible = false;
    if (prepFilter === "none" && c.dataset.prep === "1") visible = false;
    // Default view floors out weak matches (RC1-523).
    if (capped && visible && (+c.dataset.score || 0) <= DEFAULT_SCORE_FLOOR) visible = false;
    c.style.display = visible ? "" : "none";
    if (visible) candidates.push(c);
  });
  // Cards are in newest-first order (default sort); in the capped view hide the
  // overflow past DEFAULT_CAP so the page opens fast and focused.
  let hiddenByCap = 0;
  if (capped && candidates.length > DEFAULT_CAP) {
    candidates.slice(DEFAULT_CAP).forEach(c => { c.style.display = "none"; });
    hiddenByCap = candidates.length - DEFAULT_CAP;
  }
  document.getElementById("shownCount").textContent =
    capped ? Math.min(candidates.length, DEFAULT_CAP) : candidates.length;
  const showAllBtn = document.getElementById("showAll");
  if (showAllBtn) {
    showAllBtn.style.display = hiddenByCap > 0 ? "" : "none";
    if (hiddenByCap > 0) showAllBtn.textContent = "+" + hiddenByCap + " more · show all";
  }
  refreshViewToggle();
}

function showAllActive() {
  capLifted = true;
  applyFilters();
}

async function decide(id, status, el) {
  try {
    const res = await fetch("/api/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, status })
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const card = el.closest(".card");
    card.dataset.status = status;
    card.classList.toggle("hidden-card", status === "hidden");
    card.classList.toggle("applied-card", APPLIED.has(status));
    const badge = card.querySelector(".status");
    badge.className = "status status-" + status;
    badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    // Reflect the applied date the server stamped (added/updated/removed in place).
    const meta = card.querySelector(".meta");
    let ao = card.querySelector(".applied-on");
    if (APPLIED.has(status) && data.appliedDate) {
      if (!ao) { ao = document.createElement("span"); ao.className = "applied-on"; meta.appendChild(ao); }
      ao.innerHTML = '<span class="mk">applied</span>' + data.appliedDate;
    } else if (ao) {
      ao.remove();
    }
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
applySortSelect();
