// Run real searches against a deployed (or locally served) mirror.
//
// Usage: node test_search.mjs [base-url]
//   node test_search.mjs http://127.0.0.1:8642     (npx http-server@14.1.1 public -p 8642)
//   node test_search.mjs https://taxacom.org
//
// Loads the site's own pagefind.js over HTTP, so it exercises exactly what
// a browser would download. Needs nothing but the URL: the recall check
// picks message pages from the site's own month indexes. Exits non-zero if
// any check fails; checks tied to an open issue are reported as KNOWN.

const base = (process.argv[2] || "http://127.0.0.1:8642").replace(/\/$/, "");

// Minimal browser stand-ins so the browser bundle runs under Node.
globalThis.window = globalThis;
globalThis.location = new URL(base + "/");
globalThis.document = { querySelector: () => ({ getAttribute: () => "en" }), currentScript: null };
const realFetch = fetch;
const get = async (u, o) => {
  // Retry: Pagefind fires many parallel requests and simple servers drop some.
  for (let i = 0; ; i++) {
    try {
      return await realFetch(new URL(u, base + "/"), o);
    } catch (e) {
      if (i >= 4) throw e;
      await new Promise((r) => setTimeout(r, 200 * (i + 1)));
    }
  }
};
globalThis.fetch = get;

let failed = 0;
const check = (name, ok, detail = "", knownIssue = null) => {
  const status = ok ? "PASS" : knownIssue ? "KNOWN" : "FAIL";
  console.log(`${status.padEnd(5)} ${name}${knownIssue && !ok ? ` (${knownIssue})` : ""}` +
    `${ok || !detail ? "" : `\n        ${detail}`}`);
  if (!ok && !knownIssue) failed++;
};

const page = await get(base + "/");
check("landing page responds 200", page.ok, `got ${page.status}`);
check("landing page loads the search UI", (await page.text()).includes("pagefind-ui.js"));
const old = await get(base + "/pipermail/taxacom/2024-November/137850.html");
check("an original lists.ku.edu path still resolves", old.ok, `got ${old.status}`);
const regen = await get(base + "/pipermail/taxacom/2025-December/138421.html");
check("a regenerated month's page resolves", regen.ok && (await regen.text()).includes("the long goodbye"),
  `got ${regen.status}`);

const src = await (await get(base + "/pagefind/pagefind.js")).text();
const pagefind = await import("data:text/javascript," + encodeURIComponent(src));
await pagefind.options({ basePath: base + "/pagefind/", baseUrl: "/" });

// Load result data in small batches; thousands of parallel fetches overwhelm servers.
const urlsOf = async (results, limit = Infinity, stopAt = null) => {
  const urls = [];
  for (let i = 0; i < Math.min(results.length, limit); i += 25) {
    const batch = await Promise.all(results.slice(i, Math.min(i + 25, limit)).map((x) => x.data()));
    urls.push(...batch.map((d) => d.url));
    if (stopAt && urls.includes(stopAt)) break;
  }
  return urls;
};

// Known messages, original and regenerated, are found.
const cases = [
  ["Cardon Belgian missionary", "/pipermail/taxacom/2024-November/137849.html"],
  ["NAGPRA webinar", "/pipermail/taxacom/2024-November/137850.html"],
  ["long goodbye", "/pipermail/taxacom/2025-December/138421.html"],
];
for (const [q, url] of cases) {
  const r = await pagefind.search(q);
  const urls = await urlsOf(r.results, 50, url);
  check(`"${q}" finds ${url}`, urls.includes(url), `${r.results.length} results, top: ${urls.slice(0, 3).join(", ")}`);
}

// Common words return thousands of results. Pagefind 1.3 returned ~1% of these.
for (const [q, min] of [["history", 10000], ["published", 10000], ["natural history collections", 3000]]) {
  const r = await pagefind.search(q);
  check(`"${q}" returns at least ${min} results`, r.results.length >= min, `got ${r.results.length}`);
}

// Recall: messages picked from month indexes are found by a distinctive word they contain.
const months = ["1994-May", "1999-March", "2003-October", "2008-December", "2012-June", "2019-February", "2025-February"];
const sample = [];
for (const m of months) {
  const idx = await (await get(`${base}/pipermail/taxacom/${m}/date.html`)).text();
  const files = [...idx.matchAll(/HREF="(\d+\.html)"/g)].map((x) => x[1]);
  for (const f of [files[1], files[Math.floor(files.length / 2)], files[files.length - 2]]) {
    const h = await (await get(`${base}/pipermail/taxacom/${m}/${f}`)).text();
    const body = h.slice(h.indexOf("<!--beginarticle-->"), h.indexOf("<!--endarticle-->"))
      .replace(/<A [^>]*>.*?<\/A>/gis, " ") // Pagefind indexes URLs as whole tokens; sample prose only
      .replace(/<[^>]+>/g, " ");
    // Standalone prose words only: not parts of URLs, paths or identifiers.
    const words = [...body.matchAll(/(?<=[\s(])[A-Za-z]{9,14}(?=[\s.,;:!?)])/g)].map((x) => x[0]);
    const canon = (h.match(/rel="canonical" href="https?:\/\/[^/]+([^"]+)"/) || [])[1];
    if (words.length && canon) sample.push({ word: words[Math.floor(words.length / 2)], url: canon });
  }
}
const missed = [];
for (const s of sample) {
  const r = await pagefind.search(s.word);
  if (!(await urlsOf(r.results, Infinity, s.url)).includes(s.url)) missed.push(`${s.word} -> ${s.url}`);
}
check(`recall: ${sample.length - missed.length}/${sample.length} sampled messages found by a word they contain`,
  sample.length >= 15 && missed.length === 0, missed.join("; "));

// Results carry the metadata the UI shows.
const meta = await Promise.all((await pagefind.search("lectotype designation")).results.slice(0, 5).map((x) => x.data()));
check("results have title, author and date", meta.length && meta.every((d) => d.meta.title && d.meta.author && d.meta.date),
  JSON.stringify(meta.map((d) => d.meta)));

// Year filter restricts results.
const y2001 = await pagefind.search("lectotype", { filters: { year: "2001" } });
const yUrls = await urlsOf(y2001.results, 20);
check("year filter returns only that year", yUrls.length > 0 && yUrls.every((u) => u.includes("/2001-")), yUrls.join(", "));

// Index/sort pages must never appear.
const idxUrls = await urlsOf((await pagefind.search("Messages sorted by thread")).results, 20);
check("index pages are not in results", idxUrls.every((u) => /\/\d+\.html$/.test(u)), idxUrls.join(", "));

// Copies from repeat imports must not appear as separate results.
const dz = await Promise.all((await pagefind.search("Botanical Latin Zander")).results.slice(0, 20).map((x) => x.data()));
const keys = dz.map((d) => `${d.meta.title}|${d.meta.author}|${d.meta.date}`);
check("no duplicate messages in top 20 results", new Set(keys).size === keys.length,
  keys.filter((k, i) => keys.indexOf(k) !== i).slice(0, 3).join("; "));

console.log(failed ? `\n${failed} check(s) failed` : "\nAll checks passed");
process.exit(failed ? 1 : 0);
