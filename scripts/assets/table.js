const APPLIED = new Set(["applied", "interviewing", "offer", "rejected"]);

// Which group the table is filtered to. Count chips + checkboxes are two synced
// controls for this one value: active (default) | applied | hidden | closed | all.
let view = "active";

// Table-owned sort state. null => server's default order (priority, then match desc).
let sortKey = null;
let sortDir = "desc";

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window.__tt);
  window.__tt = setTimeout(() => t.classList.remove("show"), 2200);
}

// Shared filter state (search + toggles + prep) plus the active column sort, so a
// hop to the Board view and back preserves everything.
function currentParams() {
  const p = new URLSearchParams();
  const q = document.getElementById("search").value.trim();
  if (q) p.set("q", q);
  if (view !== "active") p.set("view", view);
  const prep = document.getElementById("prepFilter").value;
  if (prep && prep !== "all") p.set("prep", prep);
  if (sortKey) { p.set("sort", sortKey); p.set("dir", sortDir); }
  return p;
}

function refreshViewToggle() {
  const link = document.getElementById("boardLink");
  if (!link) return;
  const qs = currentParams().toString();
  link.href = "/" + (qs ? "?" + qs : "");
}

function initFromParams() {
  const url = new URLSearchParams(location.search);
  if (url.has("q")) document.getElementById("search").value = url.get("q");
  const prep = url.get("prep");
  if (prep) document.getElementById("prepFilter").value = prep;
  view = url.get("view") ||
    (url.get("applied") === "1" ? "applied" : url.get("hidden") === "1" ? "hidden" : "active");
  if (url.get("sort")) { sortKey = url.get("sort"); sortDir = url.get("dir") || "desc"; }
  syncControls();
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
  let shown = 0;
  document.querySelectorAll("tr.row").forEach(r => {
    const st = r.dataset.status;
    const isApplied = APPLIED.has(st);
    const isHidden = st === "hidden";
    const isClosed = r.dataset.closed === "1";
    let inView;
    if (view === "all") inView = true;
    else if (view === "applied") inView = isApplied;  // applied stays visible even if the listing closed
    else if (view === "hidden") inView = isHidden;
    else if (view === "closed") inView = isClosed;
    else inView = !isApplied && !isHidden && !isClosed;  // active: actionable roles only
    let visible = inView && (!q || r.dataset.search.includes(q));
    if (prepFilter === "has" && r.dataset.prep !== "1") visible = false;
    if (prepFilter === "none" && r.dataset.prep === "1") visible = false;
    r.style.display = visible ? "" : "none";
    if (visible) shown++;
  });
  document.getElementById("shownCount").textContent = shown;
  refreshViewToggle();
}

function cellVal(row, key) {
  if (key === "score") return parseFloat(row.dataset.score) || 0;
  if (key === "salary") return parseFloat(row.dataset.salary) || 0;
  if (key === "posted") return row.dataset.posted || "";
  if (key === "added") return row.dataset.added || "";
  if (key === "company") return row.dataset.company || "";
  if (key === "title") return row.dataset.title || "";
  return 0;
}

function applySort() {
  if (!sortKey) return;
  const tbody = document.getElementById("rows");
  const rows = Array.from(tbody.querySelectorAll("tr.row"));
  const numeric = (sortKey === "score" || sortKey === "salary");
  rows.sort((a, b) => {
    const va = cellVal(a, sortKey), vb = cellVal(b, sortKey);
    let cmp;
    if (numeric) {
      cmp = va - vb;
    } else {
      // Push empty values (e.g. missing posted date) to the bottom regardless of direction.
      if (va === "" && vb !== "") return 1;
      if (vb === "" && va !== "") return -1;
      cmp = va < vb ? -1 : (va > vb ? 1 : 0);
    }
    return sortDir === "asc" ? cmp : -cmp;
  });
  rows.forEach(r => tbody.appendChild(r));
}

function updateSortIndicators() {
  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.classList.remove("sorted-asc", "sorted-desc");
    if (th.dataset.sort === sortKey) {
      th.classList.add(sortDir === "asc" ? "sorted-asc" : "sorted-desc");
    }
  });
}

function sortByKey(key) {
  if (sortKey === key) {
    sortDir = sortDir === "asc" ? "desc" : "asc";
  } else {
    sortKey = key;
    // Text columns default ascending (A–Z); numeric columns default descending (high first).
    sortDir = (key === "company" || key === "title") ? "asc" : "desc";
  }
  applySort();
  updateSortIndicators();
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
    const data = await res.json();
    const row = el.closest("tr.row");
    row.dataset.status = status;
    row.classList.toggle("row-hidden", status === "hidden");
    row.classList.toggle("row-applied", APPLIED.has(status));
    el.className = "t-status-select status-" + status;
    // Reflect the applied date the server stamped, in the status cell.
    const cell = el.closest(".c-status");
    let ao = cell.querySelector(".t-applied");
    if (APPLIED.has(status) && data.appliedDate) {
      if (!ao) { ao = document.createElement("div"); ao.className = "t-applied"; cell.appendChild(ao); }
      ao.textContent = "Applied " + data.appliedDate;
    } else if (ao) {
      ao.remove();
    }
    toast(status === "new" ? "Restored" : ("Marked " + status));
    applyFilters();
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

document.querySelectorAll("th[data-sort]").forEach(th => {
  th.addEventListener("click", () => sortByKey(th.dataset.sort));
});

initFromParams();
if (sortKey) applySort();
updateSortIndicators();
applyFilters();
