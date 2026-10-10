/* findifsjobs: small progressive enhancements. Every page works without this file. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
document.addEventListener("error", e => { if (e.target.tagName === "IMG" && e.target.closest(".logo")) e.target.remove(); }, true);

/* Job filters (home and landing pages) */
const jf = $("#filters");
if (jf) {
  const rows = $$("#jobs > li[data-text]"), total = rows.length, count = $("#count"), base = count ? count.dataset.label : "";
  const v = id => { const el = $(id); return el ? (el.type === "checkbox" ? el.checked : el.value) : ""; };
  const run = () => {
    const q = (v("#f-q") || "").trim().toLowerCase();
    let n = 0;
    rows.forEach(r => {
      const d = r.dataset;
      const ok = (!v("#f-region") || d.region === v("#f-region")) && (!v("#f-country") || d.country === v("#f-country")) &&
        (!v("#f-area") || d.area === v("#f-area")) && (!v("#f-contract") || d.contract === v("#f-contract")) && (!v("#f-type") || d.type === v("#f-type")) &&
        (!v("#f-remote") || d.remote === "1") && (!v("#f-cloud") || d.cloud === "1") && (!v("#f-pay") || d.pay === "1") && (!q || d.text.includes(q));
      r.hidden = !ok; if (ok) n++;
    });
    if (count) count.textContent = n === total ? base : `${n} of ${total} jobs`;
    const empty = $("#jobs-empty"); if (empty) empty.hidden = n > 0;
  };
  $$("#filters select, #filters input, #f-q").forEach(el => el.addEventListener("input", run));
  const go = $("#f-go"); if (go) go.addEventListener("click", () => { run(); count && count.scrollIntoView({behavior: "smooth", block: "start"}); });
  const reset = $("#f-reset"); if (reset) reset.addEventListener("click", () => { jf.reset(); const q = $("#f-q"); if (q) q.value = ""; run(); });
  const q0 = new URLSearchParams(location.search).get("q"); if (q0 && $("#f-q")) { $("#f-q").value = q0; run(); }
}

/* Partner directory */
const pl = $("#p-list");
if (pl) {
  const cells = $$("#p-list > li"), tierV = {Elite: 3, Premier: 2, Specialized: 1};
  const run = () => {
    const q = $("#p-q").value.trim().toLowerCase(), r = $("#p-region").value, k = $("#p-kind").value, s = $("#p-sort").value;
    let n = 0;
    cells.forEach(c => { const d = c.dataset, ok = (!r || d.regions.split(" ").includes(r)) && (!k || d.kind === k) && (!q || d.text.includes(q)); c.hidden = !ok; if (ok) n++; });
    const cmp = s === "az" ? (a, b) => a.dataset.name.localeCompare(b.dataset.name)
      : s === "tier" ? (a, b) => (tierV[b.dataset.tier] || 0) - (tierV[a.dataset.tier] || 0) || a.dataset.name.localeCompare(b.dataset.name)
      : (a, b) => b.dataset.score - a.dataset.score || a.dataset.name.localeCompare(b.dataset.name);
    [...cells].sort(cmp).forEach(c => pl.appendChild(c));
    $("#p-count").textContent = `${n} of ${cells.length} partners`;
  };
  ["#p-q", "#p-region", "#p-kind", "#p-sort"].forEach(x => $(x).addEventListener("input", run));
}

/* News topic pills */
const np = $("#n-pills");
if (np) np.addEventListener("click", e => {
  const b = e.target.closest(".pill"); if (!b) return;
  $$("#n-pills .pill").forEach(x => x.setAttribute("aria-pressed", x === b));
  $$("#n-list > li").forEach(li => { li.hidden = !!b.dataset.t && li.dataset.tag !== b.dataset.t; });
});

/* Forms: send to the endpoint set in site.json, or say plainly that nothing was sent. */
const ENDPOINT = document.body.dataset.form || "";
$$("form[data-kind]").forEach(f => f.addEventListener("submit", async e => {
  e.preventDefault();
  const m = f.querySelector(".msg") || f.parentElement.querySelector(".msg"); if (m) m.hidden = false;
  if (!ENDPOINT) { if (m) m.textContent = "Nothing was sent. This form is not connected yet."; return; }
  const data = Object.fromEntries(new FormData(f)); data.form = f.dataset.kind; data.page = location.pathname;
  if (m) m.textContent = "Sending...";
  try {
    const r = await fetch(ENDPOINT, {method: "POST", headers: {"Content-Type": "application/json", "Accept": "application/json"}, body: JSON.stringify(data)});
    if (!r.ok) throw new Error(r.status);
    if (m) m.textContent = f.dataset.done || "Received. Thank you."; f.reset();
  } catch (_) { if (m) m.textContent = "That didn't send. Check your connection and try again."; }
}));
