// Shared client-side search matcher for the board and table views (RC1-510).
//
// A query matches a role when EVERY whitespace-delimited token appears at the
// START of some word in the role's lowercased search blob. Matching at word
// starts (via \b<token>) rather than anywhere in the string stops "cisco" from
// matching "san francisco", while still allowing a prefix within a word so that
// "eng" keeps matching "engineering". The blob is already lowercased by
// render.py (_search_blob); we lowercase the query here to match.
//
// Pure and DOM-free so board.js and table.js share one implementation and the
// behavior can be unit-tested (see tests/test_board_search.py).
function matchesSearch(blob, query) {
  var q = (query || "").trim().toLowerCase();
  if (!q) return true;
  return q.split(/\s+/).every(function (tok) {
    if (!tok) return true;
    var escaped = tok.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("\\b" + escaped).test(blob);
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { matchesSearch };
}
