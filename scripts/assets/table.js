const APPLIED = new Set(["applied", "interviewing", "offer", "rejected"]);

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
  if (document.getElementById("showApplied").checked) p.set("applied", "1");
  if (document.getElementById("showHidden").checked) p.set("hidden", "1");
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
  document.getElementById("showApplied").checked = url.get("applied") === "1";
  document.getElementById("showHidden").checked = url.get("hidden") === "1";
  const prep = url.get("prep");
  if (prep) document.getElementById("prepFilter").value = prep;
  if (url.get("sort")) { sortKey = url.get("sort"); sortDir = url.get("dir") || "desc"; }
}

function applyFilters() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const showApplied = document.getElementById("showApplied").checked;
  const showHidden = document.getElementById("showHidden").checked;
  const prepFilter = document.getElementById("prepFilter").value;
  let shown = 0;
  document.querySelectorAll("tr.row").forEach(r => {
    const st = r.dataset.status;
    let visible = !q || r.dataset.search.includes(q);
    if (st === "hidden" && !showHidden) visible = false;
    if (APPLIED.has(st) && !showApplied) visible = false;
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
    const row = el.closest("tr.row");
    row.dataset.status = status;
    row.classList.toggle("row-hidden", status === "hidden");
    row.classList.toggle("row-applied", APPLIED.has(status));
    el.className = "t-status-select status-" + status;
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
