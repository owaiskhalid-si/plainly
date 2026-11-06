// The live demo: lint the textarea through /api/lint, mark the text up, list the findings,
// apply the safe fixes. Plain JS, no build step.

const $ = (id) => document.getElementById(id);
const input = $("input");
const marked = $("marked");
const findingsList = $("findings");
const status = $("status");

const SAMPLES = {
  generated: `# Unlocking the Power of Caching: A Comprehensive Guide 🚀

In today's fast-paced digital landscape, performance is paramount. Whether you're a seasoned engineer or a curious beginner, it's important to note that caching plays a crucial role in delivering seamless user experiences. In this article, we will delve into the multifaceted world of caching.

## Why Caching Matters

Have you ever wondered why some websites feel incredibly fast while others feel sluggish? The answer is simple: caching. It's not just about speed — it's about efficiency, scalability, and reliability.

## Key Benefits

- **Speed:** Caching dramatically reduces latency, ensuring a seamless experience.
- **Scalability:** Caching allows your system to handle a myriad of requests effortlessly.
- **Reliability:** A robust caching layer serves as a safety net during traffic spikes.

Furthermore, monitoring is absolutely essential. Needless to say, a holistic approach will truly elevate your strategy — and unlock the full potential of your stack.

## Conclusion

In conclusion, caching is a pivotal tool in the ever-evolving landscape of web development. Happy coding, and stay tuned for more deep dives!`,
  plain: `# Caching the catalogue, not the cart

We put a cache in front of the product catalogue last month. This note says what we cached, what we left alone, and what it cost.

The catalogue: product pages, category listings and search results for anonymous visitors. These pages change when someone in the merchandising team edits a product, about forty times a day, and almost never at night. Each page is read thousands of times between edits, so a cache pays for itself quickly.

We did not cache the cart, the checkout or any page for a signed-in customer. Those differ for every visitor, so a shared cache would serve the wrong person's data or have a hit rate near zero.

The p95 response time for product pages went from 910 ms to 120 ms. Database load on a weekday afternoon dropped from about 2,100 queries per second to 380. Redis uses 1.4 GB, which costs us $38 a month.

Two things went wrong. A price edit did not clear the category pages, because the delete call listed the product's categories at the time of the delete, not at the last save. And staging shared Redis with production, so a load test evicted half the cache. Staging now has its own instance.`,
  readme: `# Acme SDK 🚀

Welcome to the Acme SDK! This comprehensive guide will help you unlock the full potential of our cutting-edge platform.

## ✨ Features

- **Blazing fast:** Built for performance from the ground up.
- **Robust:** Battle-tested in production environments.
- **Seamless integration:** Works with your existing stack.
- **Developer-friendly:** Intuitive API design.

## Getting started

In order to utilize the SDK, you will need to install it first. It is important to note that Node 18 or newer is required.

\`\`\`bash
npm install acme-sdk
\`\`\`

\`\`\`js
import { Acme } from "acme-sdk";
const client = new Acme({ apiKey: process.env.ACME_KEY });
await client.events.send({ name: "signup" });
\`\`\`

## Contributing

Feel free to open an issue or submit a pull request. Happy coding!`,
};

let lastReport = null;
let timer = null;
let activeIndex = -1;

function esc(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

async function lint(text, fix = false) {
  status.textContent = "linting…";
  const res = await fetch("/api/lint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, fix }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(run, 400);
}

async function run() {
  const text = input.value;
  if (!text.trim()) {
    render({ findings: [], words: 0, score: 100, verdict: "Plain", tellsPerThousand: 0, fixable: 0 }, text);
    return;
  }
  try {
    const report = await lint(text);
    render(report, text);
  } catch (e) {
    status.textContent = `error: ${e.message}`;
  }
}

function render(report, text) {
  lastReport = report;
  activeIndex = -1;
  status.textContent = `${report.findings.length} findings`;
  $("score").textContent = report.score;
  $("verdict").textContent = report.verdict;
  const dial = document.querySelector(".dial");
  dial.className = "dial " + (report.score >= 85 ? "good" : report.score >= 65 ? "mid" : "bad");
  $("words").textContent = report.words.toLocaleString();
  $("count").textContent = report.findings.length;
  $("tells").textContent = Number(report.tellsPerThousand).toFixed(1);
  $("fixable").textContent = report.fixable;
  $("fix").disabled = report.fixable === 0;
  renderMarked(report, text);
  renderList(report);
}

function renderMarked(report, text) {
  // Inline findings (short spans) get a solid underline; block findings (whole paragraphs) a dotted one.
  const spans = report.findings
    .map((f, i) => ({ ...f, i, block: f.end - f.start > 120 }))
    .sort((a, b) => a.start - b.start || b.end - a.end);
  let html = "";
  let pos = 0;
  const open = [];
  const inline = spans.filter((s) => !s.block);
  const blocks = spans.filter((s) => s.block);
  // Blocks first: wrap the whole span, inline marks nest inside.
  const events = [];
  for (const s of blocks) events.push({ at: s.start, type: "open", s }, { at: s.end, type: "close", s });
  for (const s of inline) events.push({ at: s.start, type: "open", s }, { at: s.end, type: "close", s });
  events.sort((a, b) => a.at - b.at || (a.type === "close" ? -1 : 1));
  let lastInlineEnd = -1;
  for (const ev of events) {
    html += esc(text.slice(pos, ev.at));
    pos = ev.at;
    if (ev.type === "open") {
      if (!ev.s.block && ev.at < lastInlineEnd) continue; // overlapping inline: skip
      if (!ev.s.block) lastInlineEnd = ev.s.end;
      html += `<mark class="${ev.s.rule.split("/")[0]}${ev.s.block ? " block" : ""}" data-i="${ev.s.i}">`;
      open.push(ev.s.i);
    } else if (open.includes(ev.s.i)) {
      html += "</mark>";
      open.splice(open.indexOf(ev.s.i), 1);
    }
  }
  html += esc(text.slice(pos));
  marked.innerHTML = html || '<span class="muted">Nothing to show yet.</span>';
}

function renderList(report) {
  findingsList.innerHTML = "";
  if (!report.findings.length) {
    findingsList.innerHTML = '<li class="empty">No findings. That reads like a person wrote it.</li>';
    return;
  }
  for (const [i, f] of report.findings.entries()) {
    const li = document.createElement("li");
    li.dataset.i = i;
    const cat = f.rule.split("/")[0];
    li.innerHTML =
      `<span class="where">${f.line}:${f.col}</span>` +
      `<span><span class="sev">${f.severity}</span>${esc(f.message)}` +
      (f.suggestion ? ` <span class="fix">→ ${esc(f.suggestion)}</span>` : "") +
      `<span class="rule ${cat}">${f.rule}</span></span>`;
    li.addEventListener("click", () => activate(i, true));
    findingsList.appendChild(li);
  }
}

function activate(i, scrollMark) {
  activeIndex = i;
  document.querySelectorAll("mark.active, .findings li.active").forEach((el) => el.classList.remove("active"));
  const m = marked.querySelector(`mark[data-i="${i}"]`);
  const li = findingsList.querySelector(`li[data-i="${i}"]`);
  if (m) {
    m.classList.add("active");
    if (scrollMark) m.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  if (li) li.classList.add("active");
}

// Tooltips on hover.
const tip = document.createElement("div");
tip.className = "tip";
tip.hidden = true;
document.body.appendChild(tip);
marked.addEventListener("mouseover", (e) => {
  const m = e.target.closest("mark");
  if (!m || !lastReport) return;
  const f = lastReport.findings[Number(m.dataset.i)];
  tip.innerHTML = `${esc(f.message)}${f.suggestion ? `<br><span class="fix">→ ${esc(f.suggestion)}</span>` : ""}<br><code>${f.rule}</code>`;
  tip.hidden = false;
  activate(Number(m.dataset.i), false);
});
marked.addEventListener("mousemove", (e) => {
  if (tip.hidden) return;
  const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 10);
  const y = e.clientY + 16 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 16;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
});
marked.addEventListener("mouseout", (e) => {
  if (e.target.closest("mark")) tip.hidden = true;
});

// Controls.
input.addEventListener("input", schedule);
$("fix").addEventListener("click", async () => {
  try {
    const report = await lint(input.value, true);
    if (report.fixedText != null) input.value = report.fixedText;
    const after = await lint(input.value);
    render(after, input.value);
    status.textContent = `${report.fixesApplied} fixes applied, ${after.findings.length} findings left`;
  } catch (e) {
    status.textContent = `error: ${e.message}`;
  }
});
$("reset").addEventListener("click", () => loadSample(document.querySelector(".samples button.on")?.dataset.sample || "generated"));
for (const b of document.querySelectorAll(".samples button")) {
  b.addEventListener("click", () => loadSample(b.dataset.sample));
}
function loadSample(name) {
  for (const b of document.querySelectorAll(".samples button")) b.classList.toggle("on", b.dataset.sample === name);
  input.value = SAMPLES[name];
  run();
}
document.querySelector(".pip button").addEventListener("click", async (e) => {
  const code = e.target.closest("code");
  try {
    await navigator.clipboard.writeText(code.dataset.copy);
    e.target.textContent = "copied";
    setTimeout(() => (e.target.textContent = "copy"), 1500);
  } catch {
    e.target.textContent = "select it";
  }
});

// Rule catalogue from rules.json (generated by scripts/export_rules.py).
const CATEGORY_BLURB = {
  tells: "Patterns that mark text as generated. Each one shows up in human writing too; the density is the tell.",
  padding: "Words that take up room without adding anything. Most of these fixes are safe and automatic.",
  structure: "The shape of the text: bullet style, rhythm, headings, the sign-off.",
  clarity: "Plain-English rules: jargon, long sentences, verbs hiding inside nouns.",
};
fetch("rules.json")
  .then((r) => r.json())
  .then((rules) => {
    const root = $("rule-list");
    const tpl = $("rule-card");
    for (const cat of ["tells", "padding", "structure", "clarity"]) {
      const section = document.createElement("div");
      section.className = "category";
      section.innerHTML = `<h3><i style="background:var(--${cat})"></i>${cat}</h3><p>${CATEGORY_BLURB[cat]}</p><div class="grid"></div>`;
      const grid = section.querySelector(".grid");
      for (const r of rules.filter((r) => r.category === cat)) {
        const card = tpl.content.cloneNode(true);
        card.querySelector(".id").textContent = r.id;
        const chips = card.querySelector(".chips");
        chips.innerHTML =
          `<span class="chip ${r.severity}">${r.severity}</span>` +
          (r.fixable ? '<span class="chip fix">fix</span>' : "") +
          (!r.enabled ? '<span class="chip off">off by default</span>' : "");
        card.querySelector("h3").textContent = r.name;
        card.querySelector(".summary").textContent = r.summary;
        card.querySelector(".why").textContent = r.why;
        const ex = r.examples[0];
        card.querySelector(".before").textContent = ex.before;
        card.querySelector(".after").textContent = ex.after;
        grid.appendChild(card);
      }
      root.appendChild(section);
    }
  })
  .catch(() => {
    $("rule-list").innerHTML = '<p class="muted">Run <code>plainly rules</code> to see the catalogue.</p>';
  });

loadSample("generated");
