// Deutsch-Trainer front end: hash router + small render functions. No build step.

const $app = document.getElementById("app");
const $toast = document.getElementById("toast");

const api = async (path, opts = {}) => {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const pct = (x) => `${Math.round((x || 0) * 100)}%`;

function toast(msg) {
  $toast.textContent = msg;
  $toast.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => $toast.classList.remove("show"), 1800);
}

// ---- UI building blocks: icons, progress rings, skeletons, celebration ---------------------

const ICONS = {   // 24×24 line icons (stroke = currentColor)
  cards: '<rect x="3" y="6" width="14" height="14" rx="2"/><path d="M7 2h12a2 2 0 0 1 2 2v12"/>',
  book: '<path d="M2 5h7a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H2z"/><path d="M22 5h-7a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h8z"/>',
  puzzle: '<path d="M9 3h6v3a2 2 0 1 0 4 0V3h2v6h-3a2 2 0 1 0 0 4h3v8h-6v-3a2 2 0 1 0-4 0v3H3v-6h3a2 2 0 1 0 0-4H3V3z"/>',
  pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v4M8 21h8"/>',
  headphones: '<path d="M3 14v-2a9 9 0 0 1 18 0v2"/><rect x="2" y="14" width="5" height="7" rx="2"/><rect x="17" y="14" width="5" height="7" rx="2"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  flame: '<path d="M12 22c4 0 7-2.7 7-6.8 0-3.6-2.4-5.9-4-7.7-.4 2-1.4 3.2-2.7 3.8.4-3.5-1.3-6.6-4.3-8.3.3 3.4-1.2 5.3-2.7 7.1C4.1 11.6 5 13.3 5 15.2 5 19.3 8 22 12 22z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  warm: '<path d="M12 21a7 7 0 0 0 7-7c0-4-3-6-4-9-1.5 2-2 3-4 4-2-1.5-2.5-3-2.5-3C6 9 5 11.5 5 14a7 7 0 0 0 7 7z"/>',
};
function icon(name, cls = "") {
  return `<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}

function ring(value, { size = 64, stroke = 7, label = "", sub = "" } = {}) {
  const v = Math.max(0, Math.min(1, value || 0)), r = (size - stroke) / 2, c = 2 * Math.PI * r;
  return `<span class="ring ${v >= 1 ? "done" : ""}" style="width:${size}px;height:${size}px" role="img"
      aria-label="${esc(sub || "Fortschritt")}: ${Math.round(v * 100)} %">
    <svg width="${size}" height="${size}"><circle class="track" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${stroke}"/>
      <circle class="val" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${stroke}" stroke-linecap="round"
        stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - v)}"/></svg>
    <span class="ring-label">${label}${sub && size >= 80 ? `<small>${esc(sub)}</small>` : ""}</span></span>`;
}

function skeleton() {
  return `<div class="skeleton" aria-label="Lädt…"><div class="skel" style="height:28px;width:45%"></div>
    <div class="skel" style="height:170px"></div><div class="skel" style="height:90px"></div><div class="skel" style="height:90px"></div></div>`;
}

function celebrate() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const colors = ["#d48a1c", "#e9a23b", "#2f6db5", "#8e3a86", "#23744a", "#f3c77a"];
  const box = document.createElement("div");
  box.className = "confetti";
  box.innerHTML = Array.from({ length: 44 }, () => {
    const x = (Math.random() - .5) * 240, left = 10 + Math.random() * 80, d = 1.2 + Math.random() * 1.1;
    return `<i style="left:${left}%;background:${colors[Math.floor(Math.random() * colors.length)]};--x:${x}px;--d:${d}s;
      --r:${Math.round(Math.random() * 720)}deg;animation-delay:${Math.random() * .25}s"></i>`;
  }).join("");
  document.body.appendChild(box);
  setTimeout(() => box.remove(), 2800);
}

const today = () => new Date().toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" });

// ---- shared pieces ---------------------------------------------------------

function wordHTML(w) {
  const art = w.article ? `<span class="art ${w.article}">${w.article}</span> ` : "";
  const extras = [];
  if (w.pos === "NOUN" && w.plural) extras.push(w.plural === "-" ? "kein Plural" : `Pl. die ${esc(w.plural)}`);
  if (w.pos === "VERB" && w.partizip2) extras.push(`${w.aux === "sein" ? "ist" : "hat"} ${esc(w.partizip2)}`);
  return `<li class="word ${w.article ? `g-${w.article}` : ""}">
    <div><button class="state-dot ${esc(w.state)}" data-word="${w.id}" data-state="${esc(w.state)}"
      title="${w.state === "known" ? "bekannt (tippen zum Zurücksetzen)" : "Als bekannt markieren"}"
      aria-label="Status: ${esc(w.state)}"></button><span class="de">${art}${esc(w.lemma)}</span>
      ${extras.length ? `<div class="extra">${extras.join(" · ")}</div>` : ""}</div>
    <div class="es">${esc(w.gloss_es || "")}</div>
  </li>`;
}

function grammarHTML(g) {
  return `<div class="gnote">
    <h3>${esc(g.name)}</h3>
    <dl>
      <dt>Regel</dt><dd>${esc(g.rule)}</dd>
      ${g.spanish_bridge ? `<dt>Puente</dt><dd>${esc(g.spanish_bridge)}</dd>` : ""}
      ${g.example ? `<dt>Beispiel</dt><dd class="example">${esc(g.example)}</dd>` : ""}
      ${g.warning ? `<dt>Achtung</dt><dd class="warning">${esc(g.warning)}</dd>` : ""}
    </dl>
    ${g.unlocked && g.lesson_id ? `<a class="btn secondary small-btn" href="#/drill/${esc(g.code)}">Üben</a>` : ""}
  </div>`;
}

// ---- views -----------------------------------------------------------------

async function viewHome() {
  const [o, p] = await Promise.all([api("/overview"), api("/progress")]);
  const errors = p.top_errors.filter((e) => e.grammar_code);
  const l = o.current_lesson;
  const d = p.done_today;
  const minutes = o.settings.session_minutes;
  const steps = [["warmup", "Aufwärmen", "sun"], ["review", "Wortschatz", "cards"], ["text", "Lesen", "book"],
    ["drill", "Grammatik", "puzzle"], ["write", "Schreiben", "pen"]];
  const doneCount = steps.filter(([k]) => d[k]).length;
  const allDone = steps.every(([k]) => d[k] || k === "warmup");
  $app.innerHTML = `
    <header class="home-head">
      <div><p class="eyebrow">${esc(today())}</p><h1>Dein Deutsch heute</h1></div>
      <span class="streak-pill" title="Tage in Folge">${icon("flame")}${p.streak} ${p.streak === 1 ? "Tag" : "Tage"}</span>
    </header>
    <div class="card hero session-card">
      ${ring(doneCount / steps.length, { size: 92, stroke: 9, label: `${doneCount}/${steps.length}`, sub: "Schritte" })}
      <div>
        <p class="eyebrow">Session · ca. ${minutes} Minuten</p>
        <h2 style="margin:2px 0 0">${allDone ? "Heute geschafft" : doneCount ? "Weiter geht's" : "Bereit für heute?"}</h2>
        <div class="step-chips">${steps.map(([k, label, ic]) =>
          `<span class="step-chip ${d[k] ? "done" : ""}">${icon(d[k] ? "check" : ic)}${label}</span>`).join("")}</div>
      </div>
      <div class="session-actions">
        <a class="btn" href="#/session/full">${icon("sparkle")}${allDone ? "Noch eine Session" : doneCount ? "Session fortsetzen" : "Heutige Session starten"}</a>
        <a class="btn secondary" href="#/session/quick">Quick 5 · Karten + 3 Übungen</a>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><b>${o.known_words}</b><span>Wörter sicher</span></div>
      <div class="stat"><b>${o.cards_due}</b><span>Karten fällig</span></div>
      <div class="stat"><b>${p.current_check.texts_read}/3</b><span>Texte L${l.number}</span></div>
    </div>
    ${p.ready_for_next ? `<a class="card" href="#/progress" style="display:block;text-decoration:none;color:inherit">
      <h3>Bereit für Lektion ${l.number + 1}</h3>
      <p class="small muted">${pct(l.mastery)} der Wörter sitzen und 3 Texte sind gelesen. Im Fortschritt kannst du wechseln.</p></a>` : ""}
    <a class="card lesson-card" href="#/lesson/${l.number}">
      ${ring(l.mastery, { size: 64, stroke: 7, label: `L${l.number}`, sub: "Wörter sicher" })}
      <span class="body">
        <span class="eyebrow">Aktuelle Lektion · ${esc(l.theme)}</span>
        <h3>${esc(l.title)}</h3>
        <span class="small muted">${l.known_count} von ${l.word_count} Wörtern sicher · Ziel 80 %</span>
      </span>
    </a>
    ${errors.length ? `<p class="section-title">Häufige Fehler · üben</p><div class="error-chips">${errors.map((e) =>
      `<a class="error-chip" href="#/drill/${esc(e.grammar_code)}">${icon("puzzle")}<span>${esc(e.name)}</span><b>${e.count}×</b></a>`).join("")}</div>` : ""}
    <p class="section-title">Einzeln üben</p>
    <div class="tile-grid">
      ${[["#/review", "cards", "Karten"], ["#/read", "book", "Lesen"], ["#/drill", "puzzle", "Grammatik"], ["#/write", "pen", "Schreiben"],
         ["#/listen", "headphones", "Hören"], ["#/cases", "table", "Spickzettel"]].map(([href, ic, label]) =>
        `<a class="tile" href="${href}"><span class="tile-ico">${icon(ic)}</span>${label}</a>`).join("")}
    </div>`;
}

// ---- session plumbing: views accept { onDone } and show "Weiter" instead of their exit link ----

function doneButton(opts, fallback = `<a class="btn" href="#/">Zur Übersicht</a>`) {
  return opts && opts.onDone ? `<button class="btn session-next">Weiter →</button>` : fallback;
}
function wireDone(opts) {
  if (!opts || !opts.onDone) return;
  $app.querySelectorAll(".session-next").forEach((b) => b.addEventListener("click", () => opts.onDone()));
}

// ---- review (FSRS) ---------------------------------------------------------

const RATINGS = [
  [1, "Nochmal", "again"], [2, "Schwer", "hard"], [3, "Gut", "good"], [4, "Leicht", "easy"],
];

function nounHTML(c) {
  return c.article ? `<span class="art ${c.article}">${c.article}</span> ${esc(c.lemma)}` : esc(c.lemma);
}

function formsHTML(c) {
  const bits = [];
  if (c.pos === "NOUN" && c.plural) bits.push(c.plural === "-" ? "kein Plural" : `Pl. die ${esc(c.plural)}`);
  if (c.pos === "VERB" && c.partizip2) bits.push(`${c.aux === "sein" ? "ist" : "hat"} ${esc(c.partizip2)}`);
  return bits.join(" · ");
}

// letter-level diff: what you typed vs. the right spelling (red = extra/wrong, green = missing)
function charDiffHTML(given, expected) {
  const a = [...given], b = [...expected], n = a.length, m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  let i = 0, j = 0, out = "";
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { out += esc(a[i]); i++; j++; }
    else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) { out += `<ins>${esc(b[j])}</ins>`; j++; }
    else { out += `<del>${esc(a[i])}</del>`; i++; }
  }
  return out;
}

// Recognition card that flips over on "Zeigen": front = the German word, back = its meaning.
function flipCardHTML(w, sentence) {
  return `<div class="flip"><div class="flip-inner">
    <div class="flash face front">
      <div class="flash-word">${nounHTML(w)}</div>
      ${sentence ? `<p class="flash-sentence">${esc(sentence)}</p>` : ""}
    </div>
    <div class="flash face back" aria-hidden="true">
      <div class="flash-word small-word">${nounHTML(w)}</div>
      <div class="flash-answer">
        <div class="flash-gloss">${esc(w.gloss_es)}</div>
        <div class="small muted">${esc(w.gloss_en || "")}${formsHTML(w) ? ` · ${formsHTML(w)}` : ""}</div>
      </div>
      ${sentence ? `<p class="flash-sentence small">${esc(sentence)}</p>` : ""}
    </div>
  </div></div>`;
}
function flipOver() {
  const f = $app.querySelector(".flip");
  f.classList.add("flipped");
  f.querySelector(".front").setAttribute("aria-hidden", "true");
  f.querySelector(".back").removeAttribute("aria-hidden");
  // once turned, drop the 3D transform so the text renders crisp
  const settle = () => f.classList.add("settled");
  f.querySelector(".flip-inner").addEventListener("transitionend", settle, { once: true });
  setTimeout(settle, 650);
}

const POS_HINT = { NOUN: "Nomen · mit Artikel", VERB: "Verb · Infinitiv", ADJ: "Adjektiv", ADV: "Adverb",
  PHRASE: "Ausdruck", CONJ: "Konjunktion", PRON: "Pronomen", ADP: "Präposition", DET: "Artikel/Begleiter", INTJ: "Ausruf" };

async function viewReview(opts = {}) {
  $app.innerHTML = skeleton();
  const limit = opts.limit || 40;
  const start = await api("/review/start", { method: "POST", body: {
    new_words: opts.newWords ?? true, new_limit: opts.newLimit ?? null, limit } });
  let queue = start.queue;
  let done = 0, correct = 0, checksKnown = 0, checksNew = 0;

  const finish = () => {
    $app.innerHTML = `
      <div class="card hero review-done">
        <p class="eyebrow">Fertig für jetzt</p>
        <h1>Gut gemacht!</h1>
        <p>${done} Karten wiederholt${done ? ` · ${Math.round((correct / done) * 100)} % richtig` : ""}.</p>
        ${checksKnown + checksNew ? `<p class="small">Alltagswörter: ${checksKnown} kanntest du schon, ${checksNew} lernst du jetzt.</p>` : ""}
        <p class="small muted">${done ? `Neue Wörter heute: ${start.new_today}. Die nächsten Karten plant FSRS für dich.` : "Gerade ist keine Karte fällig."}</p>
        ${doneButton(opts)}
      </div>`;
    wireDone(opts);
    if (done && correct / done >= 0.6) celebrate();
  };

  const next = async () => {
    if (!queue.length) {
      // Learning steps may have brought cards back into the window.
      if (done >= limit) return finish();
      queue = (await api(`/review/queue?limit=${limit - done}`)).queue;
      // next small batch of everyday checks, if today's limit for new words allows it
      if (!queue.length) queue = (await api("/review/more", { method: "POST" })).queue.slice(0, limit - done);
      if (!queue.length) return finish();
    }
    const c = queue.shift();
    (c.direction === "produce" ? showProduce : showRecognise)(c);
  };

  const header = (c) => `
    <div class="review-top">
      <a href="#/" class="small">✕ Beenden</a>
      <span class="small muted">${done} erledigt · ${queue.length + 1} übrig</span>
    </div>
    <div class="progress"><i style="width:${pct(done / (done + queue.length + 1))}"></i></div>
    <p class="eyebrow">${c.direction === "produce" ? "Español → Deutsch" : "Deutsch → Español"}
      ${c.mode === "check" ? ' · <span class="chip amber">Alltag · Kennst du das?</span>'
        : `${c.lesson_number ? ` · Lektion ${c.lesson_number}` : c.deck ? " · Alltag" : " · A1"}${c.reps === 0 ? ' · <span class="chip amber">neu</span>' : ""}`}</p>`;

  // Each card is graded exactly once: ignore double taps and keys pressed while saving.
  const graded = new Set();
  const submit = async (c, payload) => {
    const showing = `${c.id}:${c.reps}`;  // a card can return later in the session with more reps
    if (graded.has(showing)) return null;
    graded.add(showing);
    keyHandler = null;
    $app.querySelectorAll(".rate, .produce .btn").forEach((b) => (b.disabled = true));
    let r;
    try {
      r = await api(`/review/${c.id}`, { method: "POST", body: payload });
    } finally {
      $app.querySelectorAll(".produce .btn").forEach((b) => (b.disabled = false));
    }
    done += 1;
    if (r.rating >= 3 || (r.check && r.check.correct)) correct += 1;
    if (r.produce_unlocked) toast("Neu: Schreibkarte freigeschaltet ✍️");
    return r;
  };

  function showRecognise(c) {
    const t0 = performance.now();
    $app.innerHTML = `${header(c)}
      ${flipCardHTML(c, c.source_sentence)}
      <div class="review-actions">
        <button class="btn reveal">Zeigen</button>
        <div class="rate-row" hidden>${RATINGS.map(([v, label, cls]) =>
          `<button class="rate ${cls}" data-rating="${v}">${label}</button>`).join("")}</div>
      </div>`;
    const reveal = () => {
      flipOver();
      $app.querySelector(".reveal").hidden = true;
      $app.querySelector(".rate-row").hidden = false;
    };
    $app.querySelector(".reveal").addEventListener("click", reveal);
    $app.querySelectorAll(".rate").forEach((b) => b.addEventListener("click", async () => {
      if (await submit(c, { rating: +b.dataset.rating, duration_ms: Math.round(performance.now() - t0) })) next();
    }));
    keyHandler = (e) => {
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); if ($app.querySelector(".flip.flipped")) return; reveal(); }
      if (["1", "2", "3", "4"].includes(e.key) && !$app.querySelector(".rate-row").hidden)
        $app.querySelector(`[data-rating="${e.key}"]`).click();
    };
  }

  function showProduce(c) {
    const t0 = performance.now();
    $app.innerHTML = `${header(c)}
      <div class="flash">
        <div class="flash-gloss big">${esc(c.gloss_es)}</div>
        <p class="small muted">${POS_HINT[c.pos] || ""}${c.gloss_en ? ` · ${esc(c.gloss_en)}` : ""}</p>
        <form class="produce" autocomplete="off">
          <input id="answer" type="text" lang="de" autocapitalize="off" autocorrect="off" spellcheck="false"
            enterkeyhint="done" placeholder="${c.pos === "NOUN" ? "der / die / das …" : "auf Deutsch…"}" aria-label="Antwort">
          <div class="umlauts">${["ä", "ö", "ü", "ß", "Ä", "Ö", "Ü"].map((u) =>
            `<button type="button" class="uml" data-ch="${u}">${u}</button>`).join("")}</div>
          <button class="btn" type="submit">Prüfen</button>
        </form>
        <div class="feedback" hidden></div>
      </div>`;
    const $in = $app.querySelector("#answer");
    $in.focus();
    $app.querySelectorAll(".uml").forEach((b) => b.addEventListener("click", () => {
      const s = $in.selectionStart ?? $in.value.length, e = $in.selectionEnd ?? s;
      $in.value = $in.value.slice(0, s) + b.dataset.ch + $in.value.slice(e);
      $in.focus(); $in.setSelectionRange(s + 1, s + 1);
    }));
    let answered = false, moved = false;
    $app.querySelector(".produce").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (answered) { if (!moved) { moved = true; next(); } return; }
      const r = await submit(c, { answer: $in.value, duration_ms: Math.round(performance.now() - t0) });
      if (!r) return;
      answered = true;
      const ok = r.check.correct;
      $in.readOnly = true;
      $in.classList.add(ok ? (r.check.verdict === "typo" ? "is-typo" : "is-ok") : "is-bad");
      const fb = $app.querySelector(".feedback");
      fb.hidden = false;
      fb.className = `feedback ${ok ? "ok" : "bad"}`;
      const verdictLine = {
        exact: "✓ Richtig!",
        typo: "✓ Richtig, mit kleinem Tippfehler",
        missing_article: "✗ Artikel fehlt",
        wrong_article: "✗ Falscher Artikel",
        umlaut: "✗ Achte auf den Umlaut",
      }[r.check.verdict] || "✗ Leider falsch";
      const showLetters = ["typo", "umlaut"].includes(r.check.verdict) ||
        (r.check.verdict === "wrong_article" && r.check.given.trim());
      const checkLine = r.check_result === "known"
        ? `<div class="small check-note">Kennst du! Kommt erst in ca. ${r.interval_days >= 60 ? "3 Monaten" : "3 Wochen"} wieder.</div>`
        : r.check_result === "learn" ? `<div class="small check-note">Neu für dich: wir üben es jetzt öfter.</div>` : "";
      if (r.check_result === "known") checksKnown += 1;
      if (r.check_result === "learn") checksNew += 1;
      fb.innerHTML = `<strong>${verdictLine}</strong>${checkLine}
        ${showLetters ? `<div class="typo-diff" aria-label="Unterschied">${r.check.verdict === "wrong_article"
          // whole-word swap for articles: ~~der~~ das Fenster
          ? `<del>${esc(r.check.given.trim().split(/\s+/)[0])}</del> <ins>${esc(c.article)}</ins> ${esc(c.lemma)}`
          : charDiffHTML(r.check.given.trim(), r.check.expected)}</div>` : ""}
        <div class="flash-word small-word">${nounHTML(c)}</div>
        ${formsHTML(c) ? `<div class="small muted">${formsHTML(c)}</div>` : ""}`;
      $app.querySelector(".umlauts").hidden = true;
      const btn = $app.querySelector(".produce .btn");
      btn.textContent = "Weiter";
      btn.focus();
    });
    keyHandler = null;
  }

  next();
}

let keyHandler = null;

// Word lists: tap the dot to mark a word as already known (or undo it).
document.addEventListener("click", async (e) => {
  const dot = e.target.closest("[data-word]");
  if (!dot) return;
  const next = dot.dataset.state === "known" ? "new" : "known";
  await api(`/words/${dot.dataset.word}/state`, { method: "PUT", body: { state: next } });
  dot.dataset.state = next;
  dot.className = `state-dot ${next}`;
  toast(next === "known" ? "Als bekannt markiert" : "Zurückgesetzt");
});
document.addEventListener("keydown", (e) => {
  if (keyHandler && !(e.target instanceof HTMLInputElement)) keyHandler(e);
});

// "Lektions-Check": how well the plan's ingredients are covered for one lesson
function checkHTML(c) {
  const row = (done, label, detail, href) => `<li class="${done ? "done" : ""}">
    <span class="ck">${done ? "✓" : "○"}</span>
    <span class="ck-body"><span>${label}</span><span class="small muted">${detail}</span></span>
    ${href && !done ? `<a class="btn secondary small-btn" href="${href}">Los</a>` : ""}</li>`;
  return `<div class="card lesson-check">
    <h2>Lektions-Check</h2>
    <p class="small muted">Bereit für die nächste Lektion: 80 % der Wörter sicher und ${c.texts_goal} Texte gelesen.</p>
    <ul class="check-list">
      ${row(c.texts_read >= c.texts_goal, "Texte gelesen", `${c.texts_read} von ${c.texts_goal} (mehrere Texte zum selben Thema)`, "#/read")}
      ${row(c.words_total && c.words_seen >= c.words_total * 0.8, "Wörter in Texten getroffen", `${c.words_seen} von ${c.words_total}`, "#/read")}
      ${row(c.mastery >= 0.8, "Wörter sicher", `${c.words_known} von ${c.words_total} · ${pct(c.mastery)}${c.words_learning ? ` · ${c.words_learning} in Arbeit` : ""}`, "#/review")}
      ${c.grammar.map((g) => row(g.attempts >= 6 && (g.accuracy ?? 0) >= 0.7, esc(g.name),
        `${g.attempts ? `${g.attempts}× geübt · ${pct(g.accuracy)} richtig` : "noch nicht geübt"} · in ${g.in_texts} ${g.in_texts === 1 ? "Text" : "Texten"}`,
        `#/drill/${esc(g.code)}`)).join("")}
      ${row(c.writing_tasks_done >= c.writing_tasks_goal, "Schreibaufgaben", `${c.writing_tasks_done} von ${c.writing_tasks_goal}`, "#/write")}
    </ul>
  </div>`;
}

async function viewLessons() {
  const lessons = await api("/lessons");
  $app.innerHTML = `
    <h1>Lektionen</h1>
    <ul class="lesson-list">${lessons.map((l) => `
      <li><a class="lesson-row ${l.status}" href="#/lesson/${l.number}">
        ${ring(l.mastery, { size: 44, stroke: 5, label: String(l.number), sub: `Lektion ${l.number}` })}
        <span class="body">
          <span class="title">${esc(l.title)}</span>
          <span class="meta">${esc(l.theme)} · ${l.word_count} Wörter${l.word_count ? ` · ${pct(l.mastery)}` : ""}</span>
        </span>
      </a></li>`).join("")}
    </ul>`;
}

async function viewLesson(number) {
  const d = await api(`/lessons/${number}`);
  const { lesson: l, grammar, words, exercises, book_progress: bp } = d;
  const missed = new Set(bp?.missed_exercise_ids || []);
  const exBy = { AB: [], KB: [] };
  exercises.forEach((e) => exBy[e.book].push(e));
  const exList = (items) => items.length ? `<ul class="ex-list">${items.map((e) => `
      <li><label><input type="checkbox" data-ex="${e.id}" ${missed.has(e.id) ? "checked" : ""}>
        ${esc(e.label.replace(/^(Übung|Aufgabe): /, ""))}</label></li>`).join("")}</ul>` : `<p class="muted small">Keine Einträge.</p>`;

  $app.innerHTML = `
    <p class="eyebrow"><a href="#/lessons">← Lektionen</a> · Lektion ${l.number} · ${esc(l.status)}</p>
    <h1>${esc(l.title)}</h1>
    <p class="muted">${esc(l.theme)} · Wortfeld: ${esc(l.word_field)}</p>
    <div class="progress"><i style="width:${pct(l.mastery)}"></i></div>
    <p class="small muted">${l.known_count}/${l.word_count} Wörter sicher</p>

    ${checkHTML(d.check)}

    <div class="card">
      <h2>Grammatik</h2>
      ${grammar.map(grammarHTML).join("")}
      <p class="small"><a href="#/cases">Spickzettel: der / den / dem, mich / mir, Präpositionen →</a></p>
    </div>

    <div class="card">
      <h2>Redemittel</h2>
      ${l.redemittel.map((r) => `<span class="chip">${esc(r)}</span>`).join("")}
    </div>

    <div class="card">
      <h2>Wörter</h2>
      ${words.length ? `<ul class="word-list">${words.map(wordHTML).join("")}</ul>`
        : `<p class="empty">Die Wortliste dieser Lektion ist noch nicht importiert.</p>`}
    </div>

    <div class="card">
      <h2>Buch</h2>
      <div class="toggle-row">
        <label><input type="checkbox" data-flag="kursbuch_done" ${bp?.kursbuch_done ? "checked" : ""}> Kursbuch fertig</label>
        <label><input type="checkbox" data-flag="arbeitsbuch_done" ${bp?.arbeitsbuch_done ? "checked" : ""}> Arbeitsbuch fertig</label>
      </div>
      <p class="small muted">Markiere Übungen mit Fehlern. Sie werden später stärker geübt.</p>
      <h3>Arbeitsbuch</h3>${exList(exBy.AB)}
      <h3 style="margin-top:12px">Kursbuch</h3>${exList(exBy.KB)}
      <div class="field" style="margin-top:12px">
        <label for="note">Notiz zu Fehlern</label>
        <textarea id="note" rows="3" placeholder="z. B. weil-Sätze: Verb vergessen ans Ende">${esc(bp?.missed_items_note || "")}</textarea>
      </div>
      <button class="btn secondary" id="save-note">Notiz speichern</button>
    </div>
    ${words.length ? quizletCard({ lesson: number },
      `Alle ${words.filter((w) => w.pos !== "PHRASE").length} Wörter dieser Lektion als Lernset.`) : ""}`;
  wireQuizlet();

  const save = async (body) => { await api(`/lessons/${number}/book-progress`, { method: "PUT", body }); toast("Gespeichert"); };
  $app.querySelectorAll("[data-flag]").forEach((el) =>
    el.addEventListener("change", () => save({ [el.dataset.flag]: el.checked })));
  $app.querySelectorAll("[data-ex]").forEach((el) => el.addEventListener("change", () => {
    el.checked ? missed.add(+el.dataset.ex) : missed.delete(+el.dataset.ex);
    save({ missed_exercise_ids: [...missed] });
  }));
  $app.querySelector("#save-note").addEventListener("click", () =>
    save({ missed_items_note: $app.querySelector("#note").value }));
}

// ---- Quizlet export ---------------------------------------------------------------

function quizletCard(params, label) {
  const q = new URLSearchParams(params).toString();
  return `<div class="card quizlet" data-q="${esc(q)}">
    <h3>Quizlet</h3>
    <p class="small muted">${esc(label)} In Quizlet: <em>Lernset erstellen → Importieren</em>, einfügen,
      „Zwischen Begriff und Definition: Tab“ wählen.</p>
    <div class="toolbar">
      <button class="btn secondary small-btn ql-copy">📋 Kopieren</button>
      <a class="btn secondary small-btn" href="/api/export/quizlet?${esc(q)}" download>⬇ Herunterladen</a>
    </div></div>`;
}
function wireQuizlet() {
  $app.querySelectorAll(".quizlet .ql-copy").forEach((b) => b.addEventListener("click", async () => {
    const q = b.closest(".quizlet").dataset.q;
    const res = await fetch(`/api/export/quizlet?${q}&download=false`);
    const text = await res.text();
    try { await navigator.clipboard.writeText(text); toast(`${text.split("\n").filter(Boolean).length} Karten kopiert`); }
    catch { toast("Kopieren nicht möglich, bitte herunterladen"); }
  }));
}

async function viewWords() {
  const lessons = await api("/lessons");
  $app.innerHTML = `
    <h1>Wörter</h1>
    <div class="toolbar">
      <input type="search" id="q" placeholder="Suchen (Deutsch, Español, English)…" aria-label="Suchen">
      <select id="lesson" aria-label="Lektion">
        <option value="">Alle</option>
        <option value="0">A1 Basis</option>
        <option value="-1">Alltag</option>
        ${lessons.map((l) => `<option value="${l.number}">Lektion ${l.number}</option>`).join("")}
      </select>
      <select id="pos" aria-label="Wortart">
        <option value="">Alle Wortarten</option>
        <option value="NOUN">Nomen</option><option value="VERB">Verben</option>
        <option value="ADJ">Adjektive</option><option value="ADV">Adverbien</option>
      </select>
    </div>
    <p class="small muted" id="count"></p>
    <ul class="word-list" id="list"></ul>
    ${quizletCard({ state: "learning" }, "Alle Wörter, die du gerade lernst.")}`;
  wireQuizlet();

  const $q = $app.querySelector("#q"), $l = $app.querySelector("#lesson"), $p = $app.querySelector("#pos");
  const load = async () => {
    const params = new URLSearchParams({ limit: 500 });
    if ($q.value.trim()) params.set("q", $q.value.trim());
    if ($l.value !== "") params.set("lesson", $l.value);
    if ($p.value) params.set("pos", $p.value);
    const r = await api(`/words?${params}`);
    $app.querySelector("#count").textContent = `${r.total} Wörter`;
    $app.querySelector("#list").innerHTML = r.items.length ? r.items.map(wordHTML).join("")
      : `<li class="empty">Nichts gefunden.</li>`;
  };
  let t;
  $q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 200); });
  $l.addEventListener("change", load);
  $p.addEventListener("change", load);
  load();
}

async function viewSettings() {
  const { settings: s } = await api("/overview");
  const lessons = await api("/lessons");
  $app.innerHTML = `
    <h1>Einstellungen</h1>
    <div class="card">
      <div class="field">
        <label for="cur">Aktuelle Lektion (wie im Kurs)</label>
        <select id="cur">${lessons.map((l) =>
          `<option value="${l.number}" ${l.number === s.current_lesson ? "selected" : ""}>${l.number} · ${esc(l.title)}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="minutes">Länge der täglichen Session</label>
        <select id="minutes">${[[20, "20 Minuten · kompakt"], [30, "30 Minuten · ausführlich"], [40, "40 Minuten · intensiv"]].map(([v, l]) =>
          `<option value="${v}" ${v === s.session_minutes ? "selected" : ""}>${l}</option>`).join("")}</select>
      </div>
      <div class="field">
        <label for="everyday">Neue Alltagswörter pro Tag</label>
        <select id="everyday">${[[0, "keine"], [5, "5"], [10, "10"], [15, "15"]].map(([v, l]) =>
          `<option value="${v}" ${v === s.everyday_per_day ? "selected" : ""}>${l}</option>`).join("")}</select>
        <span class="small muted">Wörter wie Tür, Heizung, Kaution. Wörter, die du schon kennst, zählen nicht mit:
          richtig beim ersten Mal = kommt erst in 3 Monaten wieder.</span>
      </div>
      <div class="field">
        <label for="cap">Neue Wörter pro Tag</label>
        <input id="cap" type="number" min="0" max="50" value="${s.daily_new_word_cap}" inputmode="numeric">
      </div>
      <div class="field">
        <label for="ret">Ziel-Behaltensrate</label>
        <select id="ret">${[0.85, 0.9, 0.93, 0.95].map((v) =>
          `<option value="${v}" ${v === s.target_retention ? "selected" : ""}>${Math.round(v * 100)} %</option>`).join("")}</select>
      </div>
      <div class="toggle-row">
        <label><input type="checkbox" id="ascii" ${s.umlaut_ascii_ok ? "checked" : ""}> „ae“ statt „ä“ akzeptieren</label>
      </div>
      <button class="btn" id="save">Speichern</button>
    </div>
    <div class="card" id="voice-card">
      <h3>Vorlese-Stimme</h3>
      <div class="field"><label for="voice">Stimme</label><select id="voice"></select></div>
      <div class="field"><label for="tts-rate">Tempo</label>
        <select id="tts-rate">${[[0.8, "langsam"], [0.9, "normal"], [1, "schnell"]].map(([v, l]) =>
          `<option value="${v}" ${v === ttsRate() ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <button class="btn secondary" id="voice-test">▶ Probehören</button>
      <p class="small muted" style="margin-top:10px">Noch natürlicher: Auf dem Mac unter <em>Systemeinstellungen →
        Bedienungshilfen → Gesprochene Inhalte → Systemstimme → Stimmen verwalten</em> eine deutsche Stimme mit
        „Premium“ oder „Erweitert“ laden (z. B. Anna oder Petra). Sie erscheint dann hier.</p>
    </div>
    <div class="card" id="fsrs"></div>`;
  const $voice = $app.querySelector("#voice");
  voicesReady().then(() => {
    const cur = chosenVoice();
    const curVal = cur?.kind === "piper" ? `piper:${cur.id}` : cur?.voice?.name;
    const piper = piperVoices.map((v, k) => `<option value="piper:${esc(v.id)}" ${curVal === `piper:${v.id}` ? "selected" : ""}>
      ${esc(v.label)}${k === 0 ? " (empfohlen)" : ""}</option>`).join("");
    const browser = germanVoices().map((v) => `<option value="${esc(v.name)}" ${curVal === v.name ? "selected" : ""}>
      ${esc(v.name.replace(/ \(German \(Germany\)\)/, ""))}${v.localService ? "" : " · online"}</option>`).join("");
    $voice.innerHTML = (piper ? `<optgroup label="Natürliche Stimmen">${piper}</optgroup>` : "")
      + (browser ? `<optgroup label="Browser-Stimmen">${browser}</optgroup>` : "")
      || `<option>Keine deutsche Stimme gefunden</option>`;
  });
  $voice.addEventListener("change", () => { prefs.set(TTS_VOICE_KEY, $voice.value); });
  $app.querySelector("#tts-rate").addEventListener("change", (e) => prefs.set(TTS_RATE_KEY, e.target.value));
  $app.querySelector("#voice-test").addEventListener("click", () =>
    speak("Hallo! Heute laufe ich mit Marco an der Spree. Danach trinken wir zusammen einen Kaffee. Das macht Spaß!"));
  const renderFsrs = async (extra = "") => {
    const f = await api("/fsrs");
    const $f = $app.querySelector("#fsrs");
    $f.innerHTML = `<h3>Wiederholungsplan an dich anpassen</h3>
      <p class="small muted">FSRS kann seine Parameter an deine eigenen Bewertungen anpassen. Dafür braucht es
        mindestens ${f.min_reviews} Bewertungen.</p>
      <div class="progress"><i style="width:${pct(Math.min(1, f.reviews / f.min_reviews))}"></i></div>
      <p class="small">${f.reviews} von ${f.min_reviews} Bewertungen gesammelt.
        ${f.optimized ? `<br>✓ Angepasst am ${esc(f.optimized_at.slice(0, 10))} mit ${f.optimized_reviews} Bewertungen.` : ""}</p>
      ${!f.installed ? `<p class="small warning-box">Der Optimierer ist nicht installiert. Im Projektordner ausführen:
        <code>uv sync --extra optimizer</code></p>` : ""}
      <div class="toolbar">
        <button class="btn secondary" id="opt" ${f.ready ? "" : "disabled"}>${f.optimized ? "Neu anpassen" : "Jetzt anpassen"}</button>
        ${f.optimized ? `<button class="btn secondary" id="opt-reset">Standard wiederherstellen</button>` : ""}
      </div>${extra}`;
    $f.querySelector("#opt")?.addEventListener("click", async (e) => {
      e.target.disabled = true; e.target.textContent = "Rechnet…";
      try {
        const r = await api("/fsrs/optimize", { method: "POST" });
        renderFsrs(`<p class="small">Fertig: Parameter aus ${r.reviews} Bewertungen.${r.suggested_retention
          ? ` Empfohlene Behaltensrate: ${Math.round(r.suggested_retention * 100)} %.` : ""}</p>`);
      } catch (err) { renderFsrs(`<p class="small warning-box">${esc(err.message.replace(/^\d+ /, ""))}</p>`); }
    });
    $f.querySelector("#opt-reset")?.addEventListener("click", async () => {
      await api("/fsrs/reset", { method: "POST" }); renderFsrs();
    });
  };
  renderFsrs();
  $app.querySelector("#save").addEventListener("click", async () => {
    await api("/settings", { method: "PUT", body: {
      current_lesson: +$app.querySelector("#cur").value,
      session_minutes: +$app.querySelector("#minutes").value,
      daily_new_word_cap: +$app.querySelector("#cap").value,
      everyday_per_day: +$app.querySelector("#everyday").value,
      target_retention: +$app.querySelector("#ret").value,
      umlaut_ascii_ok: $app.querySelector("#ascii").checked,
    }});
    toast("Gespeichert");
  });
}

// ---- reader -----------------------------------------------------------------

async function viewReadList() {
  const [o, status] = await Promise.all([api("/overview"), api("/llm/status")]);
  const n = o.current_lesson.number;
  const texts = await api("/texts");
  const mine = texts.filter((t) => t.lesson_number === n);
  const older = texts.filter((t) => t.lesson_number !== n);
  const row = (t) => `<li><a class="lesson-row" href="#/text/${t.id}">
      <span class="num">${t.lesson_number}</span>
      <span class="body"><span class="title">${esc(t.title)}</span>
        <span class="meta">${pct(t.coverage)} bekannt · ${t.read_count ? `${t.read_count}× gelesen` : "neu"}</span></span></a></li>`;
  $app.innerHTML = `
    <h1>Lesen</h1>
    <div class="card hero">
      <p class="eyebrow">Lektion ${n} · ${esc(o.current_lesson.theme)}</p>
      <p class="small">Ein neuer Text über dein Leben in Berlin, mit ca. 96–98 % bekannten Wörtern und 4 neuen Wörtern aus der Lektion.</p>
      ${status.configured ? `<button class="btn" id="gen">Neuen Text schreiben</button>`
        : `<p class="small warning-box">${esc(status.message)}</p>`}
      <p class="small muted" id="gen-status" hidden></p>
    </div>
    ${texts.length ? `<a class="btn secondary" href="#/playlist" style="margin-bottom:14px">🎧 Als Playlist hören</a>` : ""}
    <h2>Lektion ${n}</h2>
    ${mine.length ? `<ul class="lesson-list">${mine.map(row).join("")}</ul>` : `<p class="empty">Noch keine Texte für diese Lektion.</p>`}
    ${older.length ? `<h2>Frühere Lektionen</h2><ul class="lesson-list">${older.map(row).join("")}</ul>` : ""}`;
  const btn = $app.querySelector("#gen");
  if (btn) btn.addEventListener("click", async () => {
    btn.disabled = true;
    const st = $app.querySelector("#gen-status");
    st.hidden = false;
    const steps = ["Claude schreibt den Text…", "Wörter und Grammatik werden geprüft…", "Unbekannte Wörter werden ersetzt…", "Fragen werden geschrieben…"];
    let i = 0;
    st.textContent = steps[0];
    const tick = setInterval(() => { i = Math.min(i + 1, steps.length - 1); st.textContent = steps[i]; }, 15000);
    try {
      const r = await api("/texts/generate", { method: "POST", body: {} });
      location.hash = `#/text/${r.text_id}`;
    } catch (e) {
      st.textContent = `Das hat nicht geklappt: ${e.message.replace(/^\d+ /, "")}`;
      btn.disabled = false;
    } finally { clearInterval(tick); }
  });
}

// ---- voice: friendlier German text-to-speech -------------------------------------------
// Picks the most natural German voice on the device (or the one chosen in Einstellungen) and reads
// sentence by sentence with short pauses, so the reader can highlight along and long texts don't cut off.

const TTS_VOICE_KEY = "tts-voice", TTS_RATE_KEY = "tts-rate";
const prefs = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: keep defaults */ } },
};
// most natural first: downloaded premium/enhanced Mac voices, Chrome's Google voice, the newer Mac voices
const VOICE_ORDER = [/premium/i, /enhanced|verbessert/i, /^Google Deutsch/, /^Sandy/, /^Shelley/, /^Flo\b/,
  /^Reed/, /^Eddy/, /^Petra/, /^Helena/, /^Markus/, /^Yannick/, /^Anna/];

function germanVoices() {
  return "speechSynthesis" in window ? speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("de")) : [];
}
function recommendedVoice() {
  const vs = germanVoices();
  for (const re of VOICE_ORDER) { const v = vs.find((x) => re.test(x.name)); if (v) return v; }
  return vs[0] || null;
}
// Natural Piper voices (served by the app, made on this Mac) come first; browser voices are the fallback.
let piperVoices = [];
const piperReady = fetch("/api/tts/voices").then((r) => (r.ok ? r.json() : [])).then((v) => { piperVoices = v; })
  .catch(() => {});
// A voice spec is { kind: "piper", id } or { kind: "browser", voice }.
function chosenVoice() {
  const saved = prefs.get(TTS_VOICE_KEY);
  if (saved && saved.startsWith("piper:") && piperVoices.some((v) => `piper:${v.id}` === saved))
    return { kind: "piper", id: saved.slice(6) };
  if ((!saved || saved.startsWith("piper:")) && piperVoices.length) return { kind: "piper", id: piperVoices[0].id };
  const b = germanVoices().find((v) => v.name === saved) || recommendedVoice();
  return b ? { kind: "browser", voice: b } : null;
}
function ttsRate() { return +(prefs.get(TTS_RATE_KEY) || 0.9); }
function voicesReady() {
  return Promise.all([piperReady, browserVoicesReady()]);
}
function browserVoicesReady() {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window) || speechSynthesis.getVoices().length) return resolve();
    speechSynthesis.addEventListener("voiceschanged", () => resolve(), { once: true });
    setTimeout(resolve, 1500);
  });
}
function splitSentences(text) {
  return text.split(/\n+/).flatMap((para, pi) =>
    (para.match(/[^.!?…]+[.!?…]+["“”»]?|[^.!?…]+$/g) || []).map((t, k) => ({ text: t.trim(), paraStart: k === 0 && pi > 0 })))
    .filter((x) => x.text);
}

let ttsRun = 0;
const ttsAudio = new Audio();   // one element, reused: friendlier to mobile autoplay rules
function stopSpeaking() {
  ttsRun += 1;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  ttsAudio.pause();
}
const piperUrl = (text, id, rate) => `/api/tts?voice=${encodeURIComponent(id)}&rate=${rate}&text=${encodeURIComponent(text)}`;

async function speakPiper(sentences, { onSentence, onEnd, rate, startAt, voice }, run) {
  const items = sentences.map((s, i) => ({ i, text: spokenText(s.text), v: s.voice || voice, para: s.paraStart }))
    .filter((x) => x.i >= startAt && x.text);
  for (let k = 0; k < items.length; k++) {
    if (run !== ttsRun) return;
    const it = items[k], next = items[k + 1];
    if (next) fetch(piperUrl(next.text, next.v.id, rate)).catch(() => {});   // prepare the next sentence
    onSentence?.(it.i);
    ttsAudio.src = piperUrl(it.text, it.v.id, rate);
    await new Promise((done) => {
      ttsAudio.onended = done; ttsAudio.onerror = done;
      ttsAudio.play().catch(done);
    });
    if (run !== ttsRun) return;
    if (next?.para) await new Promise((r) => setTimeout(r, 350));        // breathe between paragraphs
  }
  if (run === ttsRun) { onSentence?.(-1); onEnd?.(); }
}
// What the voice should say: no quotation marks (voices read them out), dashes become a short pause.
function spokenText(t) {
  return t.replace(/["„“”‚‘’«»]/g, "").replace(/\s+[–—-]\s+/g, ", ").replace(/\s{2,}/g, " ").trim();
}

async function speakSentences(sentences, { onSentence, onEnd, rate, startAt = 0 } = {}) {
  // All sentences go into the engine's queue at once: no JS timers, so it keeps going when the
  // tab is in the background (timers get throttled there). The engine's gap between utterances
  // is the pause; each utterance's onstart drives the read-along highlight.
  if (!("speechSynthesis" in window)) { toast("Vorlesen wird hier nicht unterstützt"); onEnd?.(); return; }
  await voicesReady();
  stopSpeaking();
  const run = ttsRun, voice = chosenVoice();
  const r = rate || ttsRate();
  if (voice?.kind === "piper") return speakPiper(sentences, { onSentence, onEnd, rate: r, startAt, voice }, run);
  let lastSpoken = -1;
  sentences.forEach((sent, i) => { if (i >= startAt && spokenText(sent.text)) lastSpoken = i; });
  if (lastSpoken < 0) { onEnd?.(); return; }
  if (startAt >= sentences.length) { onEnd?.(); return; }
  sentences.forEach((sent, i) => {
    if (i < startAt) return;                       // resume: skip what was already read
    const text = spokenText(sent.text);
    if (!text) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "de-DE";
    const spec = sent.voice || voice;                         // dialogues: one voice per speaker
    if (spec?.kind === "browser") u.voice = spec.voice;
    u.rate = rate || ttsRate();
    u.onstart = () => { if (run === ttsRun) onSentence?.(i); };
    if (i === lastSpoken) {
      const finish = () => { if (run === ttsRun) { onSentence?.(-1); onEnd?.(); } };
      u.onend = finish; u.onerror = finish;
    }
    speechSynthesis.speak(u);
  });
}
function speak(text, onEnd) { speakSentences(splitSentences(text), { onEnd }); }

async function viewText(id, opts = {}) {
  const d = await api(`/texts/${id}`);
  const { text: t, tokens, lemmas, questions } = d;
  const started = Date.now();
  const paragraphs = [[]];
  tokens.forEach((tok, i) => tok.br ? (paragraphs.at(-1).length && paragraphs.push([])) : paragraphs.at(-1).push([tok, i]));
  // group tokens into sentences for read-along
  const sentOf = [], sentences = [];
  let curSent = null, newPara = false;
  tokens.forEach((tk, i) => {
    if (tk.br) { curSent = null; newPara = sentences.length > 0; return; }
    if (!curSent && /^["“”»)]$/.test(tk.t) && sentences.length) {   // closing quote belongs to the last sentence
      sentences.at(-1).text += tk.t + tk.ws; sentOf[i] = sentences.length - 1; return;
    }
    if (!curSent) { curSent = { text: "", paraStart: newPara }; sentences.push(curSent); newPara = false; }
    curSent.text += tk.t + tk.ws;
    sentOf[i] = sentences.length - 1;
    if (/[.!?…]$/.test(tk.t)) curSent = null;
  });

  $app.innerHTML = `
    <p class="eyebrow"><a href="#/read">← Lesen</a> · Lektion ${t.lesson_number} · ${pct(t.coverage)} bekannt</p>
    <h1>${esc(t.title)}</h1>
    <div class="toolbar">
      <button class="btn secondary" id="speak">▶ Vorlesen</button>
      <button class="btn secondary" id="restart" hidden>⏮ Von vorne</button>
      <span class="small muted" style="align-self:center">Tippe auf ein Wort für die Übersetzung.</span>
    </div>
    <article class="reading">${paragraphs.filter((p) => p.length).map((p) => `<p>${p.map(([tok, i]) =>
      (tok.id ? `<span class="tok${tok.target ? " target" : ""}" data-s="${sentOf[i]}" data-i="${i}" role="button" tabindex="0">${esc(tok.t)}</span>`
              : `<span data-s="${sentOf[i]}">${esc(tok.t)}</span>`)
      + (tok.ws ? `<span data-s="${sentOf[i]}">${esc(tok.ws)}</span>` : "")).join("")}</p>`).join("")}</article>
    ${opts.reread ? `<p class="small muted">⏱ Lies den Text noch einmal, ruhig und flüssig. Die Zeit läuft: <strong id="timer">0:00</strong></p>` : ""}
    <button class="btn" id="done-reading">Fertig gelesen</button>
    <section id="questions" hidden></section>
    <div class="sheet" id="sheet" hidden></div>`;

  // tap-to-gloss
  const $sheet = $app.querySelector("#sheet");
  const show = (i) => {
    const tok = tokens[i], w = lemmas[tok.id];
    if (!w) return;
    $app.querySelectorAll(".tok.on").forEach((e) => e.classList.remove("on"));
    $app.querySelector(`[data-i="${i}"]`).classList.add("on");
    $sheet.hidden = false;
    $sheet.innerHTML = `
      <button class="sheet-close" aria-label="Schließen">✕</button>
      <div class="flash-word small-word">${w.article ? `<span class="art ${w.article}">${w.article}</span> ` : ""}${esc(w.lemma)}</div>
      ${formsHTML(w) ? `<div class="small muted">${formsHTML(w)}</div>` : ""}
      <div class="flash-gloss">${esc(w.gloss_es || "—")}</div>
      <div class="small muted">${esc(w.gloss_en || "")}</div>
      ${tok.note ? `<p class="small note">${esc(tok.note)}</p>` : ""}
      ${tok.target ? `<span class="chip amber">Neues Wort dieser Lektion</span>` : `<span class="chip">${esc(w.state)}</span>`}`;
    $sheet.querySelector(".sheet-close").addEventListener("click", () => { $sheet.hidden = true; });
  };
  $app.querySelectorAll(".tok").forEach((el) => {
    el.addEventListener("click", () => show(+el.dataset.i));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") show(+el.dataset.i); });
  });

  // audio: read sentence by sentence, highlight the one being read; pause keeps the place
  const $speak = $app.querySelector("#speak"), $restart = $app.querySelector("#restart");
  let status = "idle", pos = 0;            // idle | playing | paused; pos = sentence to continue from
  const highlight = (n) => $app.querySelectorAll(".reading [data-s]").forEach((el) =>
    el.classList.toggle("speaking", +el.dataset.s === n));
  const render = () => {
    $speak.textContent = status === "playing" ? "⏸ Pause" : status === "paused" ? "▶ Weiter" : "▶ Vorlesen";
    $restart.hidden = status === "idle";
  };
  const playFrom = (from) => {
    status = "playing"; pos = from; render();
    speakSentences(sentences, {
      startAt: from,
      onSentence: (n) => { if (n >= 0) { pos = n; highlight(n); } },
      onEnd: () => { status = "idle"; pos = 0; highlight(-1); render(); },
    });
  };
  const stopReading = () => { stopSpeaking(); status = "idle"; pos = 0; highlight(-1); render(); };
  $speak.addEventListener("click", () => {
    if (status === "playing") { stopSpeaking(); status = "paused"; render(); return; }  // keep pos + highlight
    playFrom(status === "paused" ? pos : 0);
  });
  $restart.addEventListener("click", () => playFrom(0));

  // comprehension
  const $q = $app.querySelector("#questions");
  const $timer = $app.querySelector("#timer");
  const tick = $timer && setInterval(() => {
    if (!document.body.contains($timer)) return clearInterval(tick);
    const s = Math.floor((Date.now() - started) / 1000);
    $timer.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
  $app.querySelector("#done-reading").addEventListener("click", async (ev) => {
    ev.target.hidden = true;
    $sheet.hidden = true;
    stopReading();
    const seconds = (Date.now() - started) / 1000;
    if (opts.reread) {
      clearInterval(tick);
      const r = await api(`/texts/${id}/finish`, { method: "POST", body: { seconds, reread: true } });
      $q.hidden = false;
      $q.innerHTML = `<div class="card hero"><h3>Aufgewärmt!</h3>
        <p class="small">${r.wpm ? `Lesetempo: <strong>${r.wpm} Wörter/Minute</strong>.` : "Zu kurz für eine Messung."}</p>
        ${doneButton(opts)}</div>`;
      wireDone(opts);
      return;
    }
    $q.hidden = false;
    $q.innerHTML = `<h2>Verstanden?</h2>${questions.map((q, n) => `
      <div class="card question" data-q="${q.id}">
        <p><strong>${n + 1}.</strong> ${esc(q.prompt)}</p>
        ${q.type === "short_answer"
          ? `<textarea rows="2" lang="de" spellcheck="false" placeholder="Antwort auf Deutsch…"></textarea>
             <button class="btn secondary check">Lösung zeigen</button>`
          : `<div class="options">${q.options.map((o) => `<button class="opt" data-a="${esc(o)}">${esc(o)}</button>`).join("")}</div>`}
        <p class="small q-feedback" hidden></p>
      </div>`).join("")}
      <button class="btn" id="finish">Abschließen</button>`;
    $q.querySelectorAll(".question").forEach((box) => {
      const qid = box.dataset.q, fb = box.querySelector(".q-feedback");
      box.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", async () => {
        if (box.dataset.answered) return;
        box.dataset.answered = "1";
        const r = await api(`/questions/${qid}/check`, { method: "POST", body: { answer: b.dataset.a } });
        b.classList.add(r.correct ? "right" : "wrong");
        if (!r.correct) box.querySelector(`.opt[data-a="${CSS.escape(r.answer)}"]`)?.classList.add("right");
        fb.hidden = false;
        fb.textContent = r.correct ? "Richtig!" : `Richtig wäre: ${r.answer}`;
      }));
      box.querySelector(".check")?.addEventListener("click", async () => {
        const r = await api(`/questions/${qid}/check`, { method: "POST", body: { answer: box.querySelector("textarea").value } });
        fb.hidden = false;
        fb.textContent = `Mögliche Antwort: ${r.answer}`;
      });
    });
    $q.querySelector("#finish").addEventListener("click", async (e2) => {
      e2.target.disabled = true;
      const r = await api(`/texts/${id}/finish`, { method: "POST", body: { seconds } });
      $q.insertAdjacentHTML("beforeend", `<div class="card hero" style="margin-top:14px">
        <h3>Super!</h3>
        <p class="small">${r.introduced ? `${r.introduced} neue Wörter sind jetzt in deinen Karten.` : "Alle Wörter sind schon in deinen Karten."}
          ${r.wpm ? ` Lesetempo: ${r.wpm} Wörter/Minute.` : ""}</p>
        ${doneButton(opts, `<a class="btn" href="#/review">Neue Wörter üben</a>`)}</div>`);
      wireDone(opts);
    });
    $q.scrollIntoView({ behavior: "smooth" });
  });
}

// ---- grammar drills -----------------------------------------------------------

const UMLAUT_KEYS = ["ä", "ö", "ü", "ß"];

async function viewDrill(code, opts = {}) {
  $app.innerHTML = skeleton();
  const { items } = await api(`/drills/session?n=${opts.n || 8}${code ? `&code=${encodeURIComponent(code)}` : ""}`);
  let idx = 0, right = 0;
  const missed = {};

  const generateBtn = (c) => `<button class="btn secondary gen-drills" data-code="${esc(c)}">Neue Übungen erstellen</button>
    <p class="small muted gen-status" hidden></p>`;
  const wireGenerate = () => $app.querySelectorAll(".gen-drills").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    const st = b.nextElementSibling;
    st.hidden = false;
    st.textContent = "Claude schreibt neue Übungen (ca. 30 s)…";
    try {
      const r = await api("/drills/generate", { method: "POST", body: { code: b.dataset.code } });
      st.textContent = r.added ? `${r.added} neue Übungen gespeichert.` : "Keine neue Übung hat die Prüfung bestanden. Versuch es nochmal.";
      if (r.added) setTimeout(() => route(), 900);
    } catch (e) {
      st.textContent = `Das hat nicht geklappt: ${e.message.replace(/^\d+ /, "")}`;
    }
    b.disabled = false;
  }));

  if (!items.length) {
    $app.innerHTML = `<h1>Grammatik üben</h1>
      <p class="empty">Für diesen Punkt gibt es gerade keine passenden Übungen mit deinen Wörtern.</p>
      ${code ? generateBtn(code) : ""}${doneButton(opts, "")}`;
    wireGenerate();
    wireDone(opts);
    return;
  }

  const finish = () => {
    const codes = Object.entries(missed);
    $app.innerHTML = `
      <div class="card hero review-done">
        <p class="eyebrow">Grammatik</p>
        <h1>${right === items.length ? "Perfekt!" : right / items.length >= 0.6 ? "Gut gemacht!" : "Dranbleiben!"}</h1>
        <p>${right} von ${items.length} richtig.</p>
      </div>
      ${codes.length ? `<div class="card"><h3>Nochmal üben</h3>${codes.map(([c, name]) => `
        <div class="toolbar" style="align-items:center;justify-content:space-between">
          <span>${esc(name)}</span>
          <span><a class="btn secondary" href="#/drill/${encodeURIComponent(c)}">Üben</a></span>
        </div>`).join("")}</div>` : ""}
      ${code ? `<div class="card"><h3>Mehr davon?</h3>${generateBtn(code)}</div>` : ""}
      ${doneButton(opts)}`;
    wireGenerate();
    wireDone(opts);
    if (right / items.length >= 0.6) celebrate();
  };

  const header = () => `
    <div class="review-top">
      <a href="#/" class="small">✕ Beenden</a>
      <a href="#/cases" class="small">Spickzettel</a>
      <span class="small muted">${idx + 1} / ${items.length}</span>
    </div>
    <div class="progress"><i style="width:${pct(idx / items.length)}"></i></div>`;

  const feedback = (r, given) => `
    <div class="feedback ${r.correct ? "ok" : "bad"}">
      <strong>${r.correct ? "Richtig!" : r.verdict === "word_order"
        ? "Fast! Die Wörter stimmen, aber die Reihenfolge nicht." : "Leider falsch."}</strong>
      ${!r.correct && given ? `<div class="small muted" style="margin-top:6px">Dein Satz → so ist es richtig:</div>
        <div class="diff">${diffHTML(given, r.full_sentence, true)}</div>` : ""}
      <div class="drill-sentence">${esc(r.full_sentence)}</div>
      ${r.explanation ? `<div class="small">${esc(r.explanation)}</div>` : ""}
    </div>
    ${r.correct ? "" : grammarHTML(r.grammar)}`;

  const show = () => {
    if (idx >= items.length) return finish();
    const it = items[idx];
    let answered = false;
    const parts = it.prompt.split("___");
    let body = "";
    if (it.type === "gap") {
      body = `<form class="drill-gap" autocomplete="off">
          <p class="drill-sentence">${esc(parts[0])}<input class="gap-input" lang="de" autocapitalize="off"
            autocorrect="off" spellcheck="false" aria-label="Lücke" size="8">${esc(parts[1] || "")}</p>
          <div class="umlauts">${UMLAUT_KEYS.map((u) => `<button type="button" class="uml" data-ch="${u}">${u}</button>`).join("")}</div>
          <button class="btn" type="submit">Prüfen</button></form>`;
    } else if (it.type === "choice") {
      body = `<p class="drill-sentence">${esc(parts[0])}<span class="blank">＿＿</span>${esc(parts[1] || "")}</p>
        <div class="options">${it.options.map((o) => `<button class="opt" data-a="${esc(o)}">${esc(o)}</button>`).join("")}</div>`;
    } else if (it.type === "rewrite") {
      body = `<form class="drill-rewrite" autocomplete="off">
          <div class="rewrite-source">${esc(it.prompt)}</div>
          <textarea class="rewrite-input" rows="2" lang="de" spellcheck="false" autocapitalize="sentences"
            placeholder="Schreib den ganzen Satz…" aria-label="Dein Satz"></textarea>
          <div class="umlauts">${UMLAUT_KEYS.map((u) => `<button type="button" class="uml" data-ch="${u}">${u}</button>`).join("")}</div>
          <button class="btn" type="submit">Prüfen</button></form>`;
    } else {
      body = `<p class="drill-sentence">${esc(it.prompt)}</p>
        <div class="order-line" aria-label="Deine Antwort"></div>
        <div class="order-pool">${it.tokens.map((t, i) => `<button class="chip-btn" data-i="${i}">${esc(t)}</button>`).join("")}</div>
        <div class="toolbar"><button class="btn secondary order-reset">Zurücksetzen</button>
          <button class="btn order-check" disabled>Prüfen</button></div>`;
    }
    $app.innerHTML = `${header()}
      <p class="eyebrow">${{ gap: "Lücke füllen", choice: "Wähle", order: "Sätze bauen", rewrite: "Umformen" }[it.type]}
        ${it.hint ? ` · <span class="hint">${esc(it.hint)}</span>` : ""}</p>
      <div class="flash drill">${body}<div class="drill-fb"></div></div>`;

    const $fb = $app.querySelector(".drill-fb");
    const next = document.createElement("button");
    next.className = "btn";
    next.textContent = idx + 1 < items.length ? "Weiter" : "Fertig";
    next.addEventListener("click", () => { idx += 1; show(); });

    const submit = async (answer) => {
      if (answered) return null;
      answered = true;
      const r = await api(`/drills/${it.id}/check`, { method: "POST", body: { answer } });
      if (r.correct) right += 1; else missed[it.grammar_code] = r.grammar.name;
      $fb.innerHTML = feedback(r, it.type === "rewrite" ? answer : null);
      if (it.type === "rewrite" && !r.correct) {
        // the key can't list every valid sentence: let the learner overrule it
        const ok = document.createElement("button");
        ok.className = "btn secondary small-btn";
        ok.textContent = "Ich hatte es richtig";
        ok.addEventListener("click", async () => {
          await api(`/drills/${it.id}/override`, { method: "POST" });
          right += 1; delete missed[it.grammar_code];
          ok.replaceWith(Object.assign(document.createElement("p"), { className: "small", textContent: "Als richtig gezählt." }));
        }, { once: true });
        $fb.appendChild(ok);
      }
      $fb.appendChild(next);
      next.focus();
      return r;
    };

    if (it.type === "gap") {
      const $in = $app.querySelector(".gap-input");
      $in.focus();
      $app.querySelectorAll(".uml").forEach((b) => b.addEventListener("click", () => {
        const a = $in.selectionStart ?? $in.value.length;
        $in.value = $in.value.slice(0, a) + b.dataset.ch + $in.value.slice($in.selectionEnd ?? a);
        $in.focus(); $in.setSelectionRange(a + 1, a + 1);
      }));
      $app.querySelector(".drill-gap").addEventListener("submit", async (e) => {
        e.preventDefault();
        if (answered) return next.click();
        if (!$in.value.trim()) return;
        const r = await submit($in.value);
        if (!r) return;
        $in.readOnly = true;
        $in.classList.add(r.correct ? "is-ok" : "is-bad");
        $app.querySelector(".drill-gap .btn").hidden = true;
        $app.querySelector(".umlauts").hidden = true;
      });
    } else if (it.type === "rewrite") {
      const $in = $app.querySelector(".rewrite-input");
      $in.focus();
      $app.querySelectorAll(".uml").forEach((b) => b.addEventListener("click", () => {
        const a = $in.selectionStart ?? $in.value.length;
        $in.value = $in.value.slice(0, a) + b.dataset.ch + $in.value.slice($in.selectionEnd ?? a);
        $in.focus(); $in.setSelectionRange(a + 1, a + 1);
      }));
      $in.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $in.form.requestSubmit(); } });
      $app.querySelector(".drill-rewrite").addEventListener("submit", async (e) => {
        e.preventDefault();
        if (answered) return next.click();
        if (!$in.value.trim()) return;
        const r = await submit($in.value.trim());
        if (!r) return;
        $in.readOnly = true;
        $in.classList.add(r.correct ? "is-ok" : "is-bad");
        $app.querySelector(".drill-rewrite .btn").hidden = true;
        $app.querySelector(".drill-rewrite .umlauts").hidden = true;
      });
    } else if (it.type === "choice") {
      $app.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", async () => {
        const r = await submit(b.dataset.a);
        if (!r) return;
        b.classList.add(r.correct ? "right" : "wrong");
        if (!r.correct) $app.querySelectorAll(".opt").forEach((o) => { if (o.dataset.a === r.expected) o.classList.add("right"); });
        $app.querySelector(".blank").textContent = r.expected;
      }));
    } else {
      const $line = $app.querySelector(".order-line"), $pool = $app.querySelector(".order-pool");
      const $check = $app.querySelector(".order-check");
      const sync = () => { $check.disabled = $pool.querySelectorAll(".chip-btn").length > 0; };
      const move = (b) => { if (answered) return; (b.parentElement === $pool ? $line : $pool).appendChild(b); sync(); };
      $app.querySelectorAll(".chip-btn").forEach((b) => b.addEventListener("click", () => move(b)));
      $app.querySelector(".order-reset").addEventListener("click", () => {
        if (answered) return;
        [...$line.children].forEach((b) => $pool.appendChild(b));
        sync();
      });
      $check.addEventListener("click", async () => {
        const r = await submit([...$line.children].map((b) => b.textContent));
        if (!r) return;
        $line.classList.add(r.correct ? "is-ok" : "is-bad");
        $app.querySelector(".toolbar").hidden = true;
        $pool.hidden = true;
      });
    }
  };
  show();
}

// ---- writing ----------------------------------------------------------------

function wordDiff(a, b, loose = false) {
  // word-level LCS: returns [{t, op}] with op = "same" | "del" | "ins".
  // loose (speech): ignore capitals and punctuation, which speech-to-text doesn't produce reliably.
  const x = a.split(/\s+/).filter(Boolean), y = b.split(/\s+/).filter(Boolean);
  const key = (w) => (loose ? w.toLowerCase().replace(/[.,!?;:„“"«»()]/g, "") : w);
  const kx = x.map(key), ky = y.map(key);
  const n = x.length, m = y.length, L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = kx[i] === ky[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (kx[i] === ky[j]) { out.push({ t: y[j], op: "same" }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ t: x[i++], op: "del" });
    else out.push({ t: y[j++], op: "ins" });
  }
  while (i < n) out.push({ t: x[i++], op: "del" });
  while (j < m) out.push({ t: y[j++], op: "ins" });
  return out;
}

function diffHTML(a, b, loose = false) {
  return wordDiff(a, b, loose).map((w) => w.op === "same" ? esc(w.t)
    : `<${w.op === "del" ? "del" : "ins"}>${esc(w.t)}</${w.op === "del" ? "del" : "ins"}>`).join(" ");
}

function feedbackHTML(r) {
  const notes = r.grammar || {};
  return `
    <div class="card">
      <h3>Korrigiert</h3>
      <p class="diff">${diffHTML(r.submission, r.corrected)}</p>
      ${r.praise ? `<p class="praise">${esc(r.praise)}</p>` : ""}
    </div>
    ${r.corrections.length ? `<h3>Die wichtigsten Punkte</h3>` : `<p class="empty">Keine Fehler gefunden. Super!</p>`}
    ${r.corrections.map((c, i) => {
      const g = c.grammar_code && notes[c.grammar_code];
      return `<div class="card correction">
        <p class="fix"><span class="num-badge">${i + 1}</span> <del>${esc(c.original)}</del> → <ins>${esc(c.corrected)}</ins></p>
        <p class="small">${esc(c.explanation)}</p>
        ${g ? `<details><summary>${esc(g.name)}</summary>${grammarHTML(g)}</details>` : ""}
      </div>`;
    }).join("")}
    ${r.more_errors ? `<p class="small muted">+ ${r.more_errors} kleinere Fehler im Text korrigiert.</p>` : ""}`;
}

async function viewWrite(opts = {}) {
  const [task, hist] = await Promise.all([api("/writing/prompt"), api("/writing?limit=5")]);
  let current = task;
  const render = () => {
    $app.innerHTML = `
      <h1>Schreiben</h1>
      <div class="card hero">
        <p class="eyebrow">Lektion ${current.lesson_number} · ${esc(current.theme)}</p>
        <h2 class="task">${esc(current.prompt)}</h2>
        <p class="small muted">${esc(current.prompt_es)}</p>
        <div class="redemittel">${current.redemittel.map((r) => `<button class="chip-btn rm" type="button">${esc(r)}</button>`).join("")}</div>
        <button class="btn secondary small-btn" id="other">Andere Aufgabe</button>
      </div>
      <form id="write-form" class="card">
        <textarea id="text" rows="5" lang="de" spellcheck="false" autocapitalize="sentences"
          placeholder="2–4 Sätze auf Deutsch…" aria-label="Dein Text"></textarea>
        <div class="toolbar" style="justify-content:space-between;align-items:center;margin-top:8px">
          <div class="umlauts">${UMLAUT_KEYS.map((u) => `<button type="button" class="uml" data-ch="${u}">${u}</button>`).join("")}</div>
          <span class="small muted" id="count">0 Sätze</span>
        </div>
        <button class="btn" type="submit" id="send">Korrigieren</button>
        <p class="small muted" id="status" hidden></p>
      </form>
      <section id="result"></section>
      ${hist.length ? `<h2>Deine letzten Texte</h2>${hist.map((h) => `
        <details class="card history"><summary><strong>${esc(h.prompt)}</strong>
          <span class="small muted"> · ${esc(h.ts.slice(0, 10))}</span></summary>
          ${feedbackHTML({ ...h, grammar: {} })}</details>`).join("")}` : ""}`;

    const $t = $app.querySelector("#text");
    const count = () => {
      const n = ($t.value.match(/[.!?]+(\s|$)/g) || []).length || ($t.value.trim() ? 1 : 0);
      $app.querySelector("#count").textContent = `${n} ${n === 1 ? "Satz" : "Sätze"}`;
    };
    $t.addEventListener("input", count);
    const insert = (str) => {
      const a = $t.selectionStart ?? $t.value.length;
      $t.value = $t.value.slice(0, a) + str + $t.value.slice($t.selectionEnd ?? a);
      $t.focus(); $t.setSelectionRange(a + str.length, a + str.length); count();
    };
    $app.querySelectorAll(".uml").forEach((b) => b.addEventListener("click", () => insert(b.dataset.ch)));
    $app.querySelectorAll(".rm").forEach((b) => b.addEventListener("click", () =>
      insert(b.textContent.replace(/\s*…\s*$/, " ").replace(/^…\s*/, ""))));
    $app.querySelector("#other").addEventListener("click", async () => {
      const draft = $t.value;
      current = await api(`/writing/prompt?exclude=${encodeURIComponent(current.prompt)}`);
      render();
      $app.querySelector("#text").value = draft;
    });
    $app.querySelector("#write-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!$t.value.trim()) return toast("Schreib zuerst ein paar Sätze.");
      const $send = $app.querySelector("#send"), $st = $app.querySelector("#status");
      $send.disabled = true; $st.hidden = false; $st.textContent = "Claude korrigiert deinen Text (ca. 20 s)…";
      try {
        const r = await api("/writing", { method: "POST", body: { prompt: current.prompt, text: $t.value } });
        $st.hidden = true;
        $t.readOnly = true;
        $send.hidden = true;
        const $r = $app.querySelector("#result");
        $r.innerHTML = feedbackHTML(r) + doneButton(opts, `<button class="btn" id="again">Neue Aufgabe</button>`);
        $r.querySelector("#again")?.addEventListener("click", () => route());
        wireDone(opts);
        $r.scrollIntoView({ behavior: "smooth" });
      } catch (err) {
        $st.textContent = `Das hat nicht geklappt: ${err.message.replace(/^\d+ /, "")}`;
        $send.disabled = false;
      }
    });
  };
  render();
}

// ---- new words: quick in-session recall before they enter spaced review ------------------

async function viewNewWords(textId, onDone, rounds = 2) {
  const [d, today] = await Promise.all([textId ? api(`/texts/${textId}`) : null, api("/review/today-new")]);
  const fromText = d ? d.text.target_lemma_ids.map((id) => d.lemmas[id]).filter(Boolean) : [];
  const seen = new Set(fromText.map((w) => w.id));
  const words = [...fromText, ...today.filter((w) => !seen.has(w.id))];
  if (!words.length) return onDone();
  const ROUNDS = rounds;
  let round = 1, queue = [...words], retry = [];
  const sentence = (w) => {
    // the sentence the word came from: today's text, else the card's source sentence
    if (!d) return w.source_sentence || "";
    const toks = d.tokens; let cur = [], hit = false;
    for (const t of toks) {
      if (t.br) { cur = []; continue; }
      cur.push(t.t + t.ws); if (t.id === w.id) hit = true;
      if (/[.!?]$/.test(t.t)) { if (hit) return cur.join("").trim(); cur = []; }
    }
    return w.source_sentence || "";
  };
  const show = () => {
    if (!queue.length) {
      if (retry.length) { queue = retry; retry = []; }
      else if (round < ROUNDS) { round += 1; queue = [...words].sort(() => Math.random() - 0.5); }
      else {
        $app.innerHTML = `<div class="card hero review-done"><p class="eyebrow">Neue Wörter</p>
          <h1>Sitzt!</h1><p class="small">${words.length} Wörter sind jetzt in deinen Karten und kommen bald wieder.</p>
          <button class="btn session-next">Weiter →</button></div>`;
        $app.querySelector(".session-next").addEventListener("click", onDone);
        celebrate();
        return;
      }
    }
    const w = queue.shift();
    $app.innerHTML = `
      <p class="eyebrow">Neue Wörter · Runde ${round} von ${ROUNDS}</p>
      ${flipCardHTML(w, sentence(w))}
      <div class="review-actions">
        <button class="btn reveal">Zeigen</button>
        <div class="rate-row two" hidden>
          <button class="rate again" data-ok="0">Nochmal</button><button class="rate good" data-ok="1">Gewusst</button>
        </div>
      </div>`;
    $app.querySelector(".reveal").addEventListener("click", (e) => {
      e.target.hidden = true;
      flipOver();
      $app.querySelector(".rate-row").hidden = false;
    });
    $app.querySelectorAll(".rate").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.ok === "0") retry.push(w);
      show();
    }, { once: true }));
  };
  show();
}

// ---- daily session -----------------------------------------------------------------

const $bar = document.getElementById("session-bar");

async function viewSession(mode) {
  const plan = await api(`/session/plan?mode=${mode}`);
  if (mode === "full" && !plan.text_id) api("/session/prepare-text", { method: "POST" }).catch(() => {});
  const steps = plan.steps;
  let i = 0, textId = null;
  const started = Date.now();

  const renderBar = () => {
    $bar.hidden = false;
    $bar.innerHTML = `<div class="session-steps">${steps.map((st, n) =>
      `<span class="step ${n < i ? "done" : n === i ? "on" : ""}">${n < i ? "✓ " : ""}${esc(st.label)}</span>`).join("")}
      <button class="skip-step" title="Diesen Schritt überspringen">Überspringen ›</button></div>`;
    $bar.querySelector(".skip-step").addEventListener("click", () => { stopSpeaking(); keyHandler = null; next(); });
  };
  const next = () => { i += 1; run(); };

  const waitForText = async () => {
    $app.innerHTML = `<div class="card hero"><p class="eyebrow">Neuer Text</p>
      <h2>Dein Text wird geschrieben…</h2>
      <p class="small muted" id="wait-msg">Claude schreibt einen Text mit deinen Wörtern und prüft ihn. Das dauert meist unter einer Minute.</p>
      <div class="toolbar" id="wait-actions" hidden>
        <button class="btn secondary" id="retry">Nochmal versuchen</button>
        <button class="btn secondary" id="skip">Überspringen</button></div></div>`;
    for (;;) {
      if (!document.body.contains($app.querySelector("#wait-msg"))) return null; // user left
      const st = await api("/session/text-status");
      if (st.text_id) return st.text_id;
      if (!st.generating) {
        if (!st.error) { await api("/session/prepare-text", { method: "POST" }); continue; }
        $app.querySelector("#wait-msg").textContent = `Das hat nicht geklappt: ${st.error}`;
        $app.querySelector("#wait-actions").hidden = false;
        return await new Promise((resolve) => {
          $app.querySelector("#retry").onclick = async () => {
            await api("/session/prepare-text", { method: "POST" }); resolve(waitForText());
          };
          $app.querySelector("#skip").onclick = () => resolve(null);
        });
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
  };

  const run = async () => {
    if (i >= steps.length) return finish();
    renderBar();
    window.scrollTo(0, 0);
    const st = steps[i];
    if (st.kind === "warmup") return viewText(st.text_id, { reread: true, onDone: next });
    if (st.kind === "review") return viewReview({ newWords: (st.new || 0) > 0, newLimit: st.new || 0, limit: st.limit, onDone: next });
    if (st.kind === "text") {
      textId = await waitForText();
      if (!textId) { steps.splice(i, 2); return run(); } // skip text + new words
      return viewText(textId, { onDone: next });
    }
    if (st.kind === "newwords") return viewNewWords(textId, next, st.rounds);
    if (st.kind === "drill") return viewDrill(null, { n: st.n, onDone: next });
    if (st.kind === "write") return viewWrite({ onDone: next });
    next();
  };

  const finish = async () => {
    $bar.hidden = true;
    const p = await api("/progress");
    const mins = Math.max(1, Math.round((Date.now() - started) / 60000));
    $app.innerHTML = `<div class="card hero review-done">
      <p class="eyebrow">${mode === "quick" ? "Quick 5" : `Heutige Session · ${plan.minutes} Minuten geplant`}</p>
      <h1>Geschafft!</h1>
      <p>${mins} Minuten · Serie: <strong>${p.streak} ${p.streak === 1 ? "Tag" : "Tage"}</strong></p>
      <a class="btn" href="#/progress">Fortschritt ansehen</a>
      <a class="btn secondary" href="#/">Zur Übersicht</a></div>`;
    celebrate();
  };
  run();
}

// ---- progress --------------------------------------------------------------------

function activityChart(days) {
  const max = Math.max(1, ...days.map((d) => d.count));
  const label = (d) => new Date(d.day + "T12:00").toLocaleDateString("de-DE", { weekday: "short", day: "numeric" });
  return `<div class="bars" role="img" aria-label="Aktivität der letzten 14 Tage">${days.map((d) => `
    <div class="bar-col" tabindex="0" data-tip="${esc(label(d))}: ${d.count} Übungen">
      <div class="bar" style="height:${d.count ? Math.max(6, (d.count / max) * 100) : 0}%"></div>
      <span class="bar-label">${new Date(d.day + "T12:00").getDate()}</span>
    </div>`).join("")}</div>
    <table class="sr-only"><caption>Aktivität pro Tag</caption>${days.map((d) =>
      `<tr><th>${esc(d.day)}</th><td>${d.count}</td></tr>`).join("")}</table>`;
}

async function viewProgress() {
  const p = await api("/progress");
  const cur = p.lessons.find((l) => l.number === p.current_lesson);
  const speeds = p.reading_speed;
  const lastWpm = speeds.length ? speeds.at(-1).wpm : null;
  const firstWpm = speeds.length > 1 ? speeds[0].wpm : null;
  $app.innerHTML = `
    <h1>Fortschritt</h1>
    <div class="stats four">
      <div class="stat"><b>${p.known_words}</b><span>Wörter sicher</span></div>
      <div class="stat"><b>${p.cards_due}</b><span>heute fällig</span></div>
      <div class="stat"><b>${p.streak}</b><span>Tage Serie</span></div>
      <div class="stat"><b>${lastWpm ?? "–"}</b><span>Wörter/Min.${firstWpm ? ` (vorher ${firstWpm})` : ""}</span></div>
    </div>
    ${p.ready_for_next ? `<div class="card hero"><h3>Bereit für Lektion ${p.current_lesson + 1}!</h3>
      <p class="small">${pct(cur.mastery)} der Wörter aus Lektion ${p.current_lesson} sitzen und du hast ${p.current_check.texts_read} Texte dazu gelesen. Wechsle, wenn dein Kurs so weit ist.</p>
      <button class="btn" id="advance">Zu Lektion ${p.current_lesson + 1} wechseln</button></div>` : ""}
    <div class="card"><h3>Aktivität · 14 Tage</h3>${activityChart(p.activity)}
      <p class="small muted">${p.review_accuracy_7d != null ? `Karten richtig (7 Tage): ${pct(p.review_accuracy_7d)} · ` : ""}${p.texts_read} ${p.texts_read === 1 ? "Text" : "Texte"} gelesen · ${p.writings} ${p.writings === 1 ? "Text" : "Texte"} geschrieben</p></div>
    <div class="card"><h3>Lektionen</h3>
      <p class="small muted">Ziel vor der nächsten Lektion: 80 % der Wörter sicher und 3 Texte gelesen.
        Aktuelle Lektion: ${p.current_check.texts_read}/3 Texte · <a href="#/lesson/${p.current_lesson}">Lektions-Check</a></p>
      ${p.lessons.map((l) => `<a class="mastery-row ${l.number === p.current_lesson ? "current" : ""}" href="#/lesson/${l.number}">
        ${ring(l.mastery, { size: 34, stroke: 4, label: String(l.number), sub: `Lektion ${l.number}` })}
        <span class="m-body"><span class="m-title">${esc(l.theme)}</span>
          <span class="progress"><i style="width:${pct(l.mastery)}"></i></span>
          <span class="small muted">${l.known}/${l.words} sicher${l.learning ? ` · ${l.learning} in Arbeit` : ""}</span></span>
        <span class="m-pct">${pct(l.mastery)}</span></a>`).join("")}</div>
    <div class="card"><h3>Häufigste Fehler</h3>
      ${p.top_errors.length ? `<ol class="errors">${p.top_errors.map((e) => `<li>
        <span>${e.grammar_code ? esc(e.name) : `${e.article ? `<span class="art ${e.article}">${e.article}</span> ` : ""}${esc(e.lemma || "")}`}
          <span class="small muted">· ${e.count}×</span><br><span class="small muted">${esc(e.example || "")}</span></span>
        ${e.grammar_code ? `<a class="btn secondary small-btn" href="#/drill/${esc(e.grammar_code)}">Üben</a>` : ""}</li>`).join("")}</ol>`
        : `<p class="small muted">Noch keine Fehler gesammelt. Sie kommen aus Übungen und Texten, die du schreibst.</p>`}</div>
    <a class="btn secondary" href="#/settings">⚙ Einstellungen</a>`;
  $app.querySelector("#advance")?.addEventListener("click", async () => {
    await api("/settings", { method: "PUT", body: { current_lesson: p.current_lesson + 1 } });
    toast(`Lektion ${p.current_lesson + 1} ist jetzt aktiv`);
    route();
  });
}

// ---- listening playlist (narrow reading set as audio, e.g. for runs) ------------------

async function viewPlaylist() {
  const texts = await api("/texts");
  $app.innerHTML = `
    <p class="eyebrow"><a href="#/listen">← Hören</a></p>
    <h1>Lesetexte als Playlist</h1>
    <p class="small muted">Deine Lesetexte als Playlist, vorgelesen von der deutschen Stimme deines Geräts. Am besten mit Kopfhörern beim Laufen.
      Hinweis: Auf dem iPhone stoppt die Wiedergabe meist, wenn der Bildschirm sperrt.</p>
    ${texts.length ? `
    <div class="card player">
      <p class="small" id="now">Bereit: ${texts.length} ${texts.length === 1 ? "Text" : "Texte"}</p>
      <p class="player-sentence" id="sentence"></p>
      <div class="toolbar" style="align-items:center">
        <button class="btn" id="main">▶ Alle abspielen</button>
        <button class="btn secondary" id="restart" hidden>⏮ Von vorne</button>
        <label class="small">Tempo <select id="rate">${[[0.8, "langsam"], [0.9, "normal"], [1, "schnell"]].map(([v, l]) =>
          `<option value="${v}" ${v === ttsRate() ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      </div>
    </div>
    <ul class="lesson-list">${texts.map((t, n) => `<li><div class="lesson-row" data-n="${n}">
      <span class="num">${t.lesson_number}</span>
      <span class="body"><span class="title">${esc(t.title)}</span><span class="meta">${esc(t.summary || "")}</span></span>
      <button class="btn secondary small-btn play-one" data-n="${n}" aria-label="${esc(t.title)} abspielen">▶</button></div></li>`).join("")}</ul>`
    : `<p class="empty">Noch keine Texte. Erstelle zuerst einen unter „Lesen“.</p>`}`;
  if (!texts.length) return;

  const $now = $app.querySelector("#now"), $sent = $app.querySelector("#sentence");
  const $main = $app.querySelector("#main"), $restart = $app.querySelector("#restart");
  const cache = {};
  const sentencesOf = async (n) => {
    if (!cache[n]) {
      const d = await api(`/texts/${texts[n].id}`);
      cache[n] = splitSentences(`${texts[n].title}.\n` + d.tokens.map((tk) => tk.br ? "\n" : tk.t + tk.ws).join(""));
    }
    return cache[n];
  };
  // status: idle | playing | paused; pos = which text and which sentence to continue from
  let status = "idle", pos = { t: 0, s: 0 }, continuous = true;

  const render = () => {
    $main.textContent = status === "playing" ? "⏸ Pause" : status === "paused" ? "▶ Weiter" : "▶ Alle abspielen";
    $restart.hidden = status === "idle";
    $app.querySelectorAll(".lesson-row").forEach((r) => r.classList.toggle("playing", status !== "idle" && +r.dataset.n === pos.t));
  };
  const showPos = (sents) => {
    $now.textContent = `${status === "paused" ? "Pausiert" : "Jetzt"}: ${texts[pos.t].title} · Satz ${pos.s + 1} von ${sents.length}`;
    $sent.textContent = sents[pos.s]?.text || "";
  };
  const play = async () => {
    if (!("speechSynthesis" in window)) return toast("Vorlesen wird hier nicht unterstützt");
    status = "playing"; render();
    const sents = await sentencesOf(pos.t);
    showPos(sents);
    speakSentences(sents, {
      startAt: pos.s,
      rate: +$app.querySelector("#rate").value,
      onSentence: (i) => { if (i >= 0) { pos.s = i; showPos(sents); } },
      onEnd: () => {
        if (continuous && pos.t + 1 < texts.length) { pos = { t: pos.t + 1, s: 0 }; play(); }
        else { status = "idle"; pos = { t: 0, s: 0 }; $now.textContent = "Fertig gehört."; $sent.textContent = ""; render(); }
      },
    });
  };
  $main.addEventListener("click", async () => {
    if (status === "playing") {                 // pause: remember the sentence
      stopSpeaking(); status = "paused"; render(); showPos(await sentencesOf(pos.t)); return;
    }
    if (status === "idle") { pos = { t: 0, s: 0 }; continuous = true; }
    play();                                     // idle: from the top · paused: resume where we stopped
  });
  $restart.addEventListener("click", () => { stopSpeaking(); pos = { t: pos.t, s: 0 }; play(); });   // this text from the start
  $app.querySelectorAll(".play-one").forEach((b) => b.addEventListener("click", () => {
    stopSpeaking(); pos = { t: +b.dataset.n, s: 0 }; continuous = false; play();
  }));
}

// ---- Hören: listening comprehension (listen max. 2×, then a quiz, then the transcript) ---------

function secondVoice(primary) {
  // a different German voice for the second speaker in dialogues, from the same engine
  if (primary?.kind === "piper") {
    const other = piperVoices.find((v) => v.id !== primary.id);
    return other ? { kind: "piper", id: other.id } : null;
  }
  const taken = primary?.voice?.name;
  const vs = germanVoices().filter((v) => v.name !== taken && !/Grandma|Grandpa|Rocko/.test(v.name));
  for (const re of VOICE_ORDER) { const v = vs.find((x) => re.test(x.name)); if (v) return { kind: "browser", voice: v }; }
  return vs[0] ? { kind: "browser", voice: vs[0] } : null;
}

// "Lena: Hallo!" lines → sentences tagged with their speaker's voice. With only one voice available the
// name is read out, so you can still tell who speaks.
function dialogueSentences(body) {
  const primary = chosenVoice(), other = secondVoice(primary);
  const speakers = [];
  const out = [];
  body.split(/\n+/).forEach((line, li) => {
    const m = line.match(/^\s*([A-ZÄÖÜ][\wäöüß-]{1,20}):\s*(.+)$/);
    const speaker = m ? m[1] : null, text = m ? m[2] : line;
    if (speaker && !speakers.includes(speaker)) speakers.push(speaker);
    const voice = speaker && other ? (speakers.indexOf(speaker) % 2 === 0 ? primary : other) : null;
    splitSentences(text).forEach((s, k) => out.push({
      text: !other && speaker && k === 0 ? `${speaker}: ${s.text}` : s.text,
      shown: s.text, speaker: k === 0 ? speaker : null, voice, paraStart: k === 0 && li > 0,
    }));
  });
  return out;
}

async function viewListen() {
  const [tasks, status, o] = await Promise.all([api("/texts?kind=listen"), api("/llm/status"), api("/overview")]);
  const row = (t) => `<li><a class="lesson-row" href="#/listen/${t.id}">
      <span class="num">${t.lesson_number}</span>
      <span class="body"><span class="title">${esc(t.title)}</span>
        <span class="meta">${t.attempts ? `Bestes Ergebnis: ${pct(t.best_score)} · ${t.attempts}× gemacht` : "neu"}</span></span></a></li>`;
  $app.innerHTML = `
    <h1>Hören</h1>
    <div class="card hero">
      <p class="eyebrow">Lektion ${o.current_lesson.number} · ${esc(o.current_lesson.theme)}</p>
      <p class="small">Ein kurzer Hörtext (Dialog, Sprachnachricht oder Durchsage). Du hörst ihn höchstens zweimal,
        ohne Text, und beantwortest dann ein Quiz. Danach siehst du den Text.</p>
      ${status.configured ? `<button class="btn" id="gen">Neue Höraufgabe</button>`
        : `<p class="small warning-box">${esc(status.message)}</p>`}
      <p class="small muted" id="gen-status" hidden></p>
    </div>
    ${tasks.length ? `<ul class="lesson-list">${tasks.map(row).join("")}</ul>` : `<p class="empty">Noch keine Höraufgaben.</p>`}
    <p class="small"><a href="#/playlist">🎧 Deine Lesetexte als Playlist (zum Laufen)</a></p>`;
  const btn = $app.querySelector("#gen");
  btn?.addEventListener("click", async () => {
    btn.disabled = true;
    const st = $app.querySelector("#gen-status");
    st.hidden = false; st.textContent = "Claude schreibt eine Höraufgabe (ca. 1 Minute)…";
    try {
      const r = await api("/texts/generate", { method: "POST", body: { kind: "listen" } });
      location.hash = `#/listen/${r.text_id}`;
    } catch (e) { st.textContent = `Das hat nicht geklappt: ${e.message.replace(/^\d+ /, "")}`; btn.disabled = false; }
  });
}

const MAX_PLAYS = 2;

async function viewListenTask(id) {
  const d = await api(`/texts/${id}`);
  const body = d.tokens.map((tk) => tk.br ? "\n" : tk.t + tk.ws).join("");
  await voicesReady();
  const sents = dialogueSentences(body);
  let plays = 0, status = "idle", pos = 0;     // status: idle | playing | paused | done (heard enough)

  $app.innerHTML = `
    <p class="eyebrow"><a href="#/listen">← Hören</a> · Lektion ${d.text.lesson_number}</p>
    <h1>${esc(d.text.title)}</h1>
    <div class="card listen-card">
      <p class="small muted" id="hint">Hör gut zu. Du kannst den Text höchstens ${MAX_PLAYS}× hören, dann kommt das Quiz.</p>
      <button class="play-big" id="play" aria-label="Anhören">▶</button>
      <div class="progress"><i id="bar" style="width:0%"></i></div>
      <p class="small" id="count">Gehört: 0 von ${MAX_PLAYS}</p>
      <div class="toolbar" style="justify-content:center">
        <button class="btn secondary small-btn" id="restart" hidden>⏮ Von vorne</button>
        <label class="small">Tempo <select id="rate"><option value="0.8">langsam</option>
          <option value="0.9" selected>normal</option><option value="1">schnell</option></select></label>
      </div>
      <button class="btn" id="to-quiz" hidden>Zum Quiz →</button>
    </div>
    <section id="quiz" hidden></section>
    <section id="transcript" hidden></section>`;

  const $play = $app.querySelector("#play"), $bar = $app.querySelector("#bar"), $count = $app.querySelector("#count");
  const $restart = $app.querySelector("#restart"), $toQuiz = $app.querySelector("#to-quiz"), $hint = $app.querySelector("#hint");
  const render = () => {
    $play.textContent = status === "playing" ? "⏸" : "▶";
    $play.disabled = status === "done";
    $play.setAttribute("aria-label", status === "playing" ? "Pause" : status === "paused" ? "Weiter" : "Anhören");
    $restart.hidden = !(status === "playing" || status === "paused");
    $count.textContent = `Gehört: ${plays} von ${MAX_PLAYS}${status === "paused" ? " · pausiert" : ""}`;
    $toQuiz.hidden = plays === 0 || status === "playing";
    if (status === "idle" && plays > 0 && plays < MAX_PLAYS) $hint.textContent = "Noch einmal hören oder direkt zum Quiz.";
    if (status === "done") $hint.textContent = "Du hast den Text zweimal gehört. Jetzt das Quiz!";
  };
  const progress = (i) => { $bar.style.width = `${Math.round(((i + 1) / sents.length) * 100)}%`; };
  const playFrom = (from, newPlay) => {
    if (newPlay) plays += 1;
    status = "playing"; pos = from; render();
    speakSentences(sents, {
      startAt: from, rate: +$app.querySelector("#rate").value,
      onSentence: (i) => { if (i >= 0) { pos = i; progress(i); } },
      onEnd: () => { status = plays >= MAX_PLAYS ? "done" : "idle"; pos = 0; render(); },
    });
  };
  $play.addEventListener("click", () => {
    if (status === "playing") { stopSpeaking(); status = "paused"; render(); return; }  // pause, same listen
    if (status === "paused") return playFrom(pos, false);                              // resume, same listen
    if (plays < MAX_PLAYS) playFrom(0, true);                                          // a new listen
  });
  $restart.addEventListener("click", () => { stopSpeaking(); playFrom(0, false); });   // restart this listen
  render();

  // ---- quiz
  $toQuiz.addEventListener("click", () => {
    stopSpeaking(); status = "done"; render();
    $app.querySelector(".listen-card").hidden = true;
    const $q = $app.querySelector("#quiz");
    $q.hidden = false;
    const graded = d.questions.filter((q) => q.type !== "short_answer").length;
    let answered = 0, correct = 0;
    $q.innerHTML = `<h2>Quiz</h2>${d.questions.map((q, n) => `
      <div class="card question" data-q="${q.id}" data-type="${q.type}">
        <p><strong>${n + 1}.</strong> ${esc(q.prompt)}</p>
        ${q.type === "short_answer"
          ? `<textarea rows="2" lang="de" spellcheck="false" placeholder="Antwort auf Deutsch…"></textarea>
             <button class="btn secondary check">Lösung zeigen</button>`
          : `<div class="options">${q.options.map((op) => `<button class="opt" data-a="${esc(op)}">${esc(op)}</button>`).join("")}</div>`}
        <p class="small q-feedback" hidden></p>
      </div>`).join("")}
      <button class="btn" id="finish-quiz" disabled>Auswertung</button>`;
    const $finish = $q.querySelector("#finish-quiz");
    const sync = () => { $finish.disabled = answered < graded; };
    $q.querySelectorAll(".question").forEach((box) => {
      const qid = box.dataset.q, fb = box.querySelector(".q-feedback");
      box.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", async () => {
        if (box.dataset.answered) return;
        box.dataset.answered = "1";
        const r = await api(`/questions/${qid}/check`, { method: "POST", body: { answer: b.dataset.a } });
        answered += 1; if (r.correct) correct += 1; sync();
        b.classList.add(r.correct ? "right" : "wrong");
        if (!r.correct) box.querySelectorAll(".opt").forEach((o) => { if (o.dataset.a === r.answer) o.classList.add("right"); });
        fb.hidden = false; fb.textContent = r.correct ? "Richtig!" : `Richtig wäre: ${r.answer}`;
      }));
      box.querySelector(".check")?.addEventListener("click", async () => {
        const r = await api(`/questions/${qid}/check`, { method: "POST", body: { answer: box.querySelector("textarea").value } });
        fb.hidden = false; fb.textContent = `Mögliche Antwort: ${r.answer}`;
      });
    });
    sync();
    $finish.addEventListener("click", async () => {
      $finish.disabled = true;
      await api(`/texts/${id}/listen-result`, { method: "POST", body: { plays, correct, total: graded } });
      showTranscript(correct, graded);
    });
  });

  // ---- transcript: read along, open in the reader for translations
  const showTranscript = (correct, graded) => {
    const $t = $app.querySelector("#transcript");
    $t.hidden = false;
    $t.innerHTML = `
      <div class="card hero"><h3>${correct === graded ? "Super gehört!" : correct / Math.max(1, graded) >= 0.6
        ? "Gut gemacht!" : "Dranbleiben! Lies den Text und hör ihn nochmal."}</h3>
        <p>${correct} von ${graded} richtig · ${plays}× gehört</p></div>
      <div class="card"><h3>Der Text</h3>
        <div class="toolbar"><button class="btn secondary small-btn" id="along">▶ Mit Text anhören</button>
          <a class="btn secondary small-btn" href="#/text/${id}">Im Leser öffnen (mit Übersetzungen)</a></div>
        <div class="reading transcript">${sents.map((s, i) => `${s.speaker ? `${i ? "</p>" : ""}<p><strong>${esc(s.speaker)}:</strong> `
          : i === 0 || s.paraStart ? `${i ? "</p>" : ""}<p>` : ""}<span data-s="${i}">${esc(s.shown)}</span> `).join("")}</p></div>
      </div>
      <a class="btn" href="#/listen">Zurück zu Hören</a>`;
    if (correct / Math.max(1, graded) >= 0.6) celebrate();
    const hl = (n) => $t.querySelectorAll("[data-s]").forEach((el) => el.classList.toggle("speaking", +el.dataset.s === n));
    const $along = $t.querySelector("#along");
    let on = false;
    $along.addEventListener("click", () => {
      if (on) { stopSpeaking(); on = false; hl(-1); $along.textContent = "▶ Mit Text anhören"; return; }
      on = true; $along.textContent = "■ Stopp";
      speakSentences(sents, { onSentence: hl, onEnd: () => { on = false; hl(-1); $along.textContent = "▶ Mit Text anhören"; } });
    });
    $t.scrollIntoView({ behavior: "smooth" });
  };
}

// ---- Spickzettel: cases at a glance (written for this app) ------------------------------------

function caseTable(head, rows, note = "", corner = "") {
  return `<div class="table-wrap"><table class="case-table"><thead><tr><th>${corner}</th>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(([c, ...cells]) => `<tr><th>${c}</th>${cells.map((x) => `<td>${x}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    ${note ? `<p class="small muted">${note}</p>` : ""}`;
}

function viewCases() {
  const G = ["<span class='art der'>m</span>", "<span class='art die'>f</span>", "<span class='art das'>n</span>", "Plural"];
  const hi = (x) => `<mark>${x}</mark>`;   // the forms that change
  $app.innerHTML = `
    <p class="eyebrow"><a href="#/drill">← Grammatik</a></p>
    <h1>Spickzettel: Fälle</h1>
    <p class="muted">Nominativ, Akkusativ, Dativ auf einen Blick. Markiert ist, was sich ändert.</p>

    <nav class="toc">${[["faelle", "Die 3 Fälle"], ["artikel", "der / den / dem"], ["ein", "ein / kein"], ["poss", "mein … unser, euer"],
      ["pron", "ich / mich / mir"], ["praep", "Präpositionen"], ["verben", "Verben mit Dativ"], ["tricks", "Merktricks"]]
      .map(([id, t]) => `<a href="#/cases" data-jump="${id}">${t}</a>`).join("")}</nav>

    <section class="card" id="faelle"><h2>Die 3 Fälle</h2>
      <dl class="cases-dl">
        <dt>Nominativ · <em>Wer? Was?</em></dt><dd>Das Subjekt. <span class="muted">ES: el sujeto</span> · <i>Der Hund schläft.</i></dd>
        <dt>Akkusativ · <em>Wen? Was?</em></dt><dd>Das direkte Objekt. <span class="muted">ES: complemento directo (lo / la)</span> · <i>Ich sehe den Hund.</i></dd>
        <dt>Dativ · <em>Wem?</em></dt><dd>Das indirekte Objekt, oft eine Person. <span class="muted">ES: complemento indirecto (le)</span> · <i>Ich gebe dem Hund Wasser.</i></dd>
      </dl></section>

    <section class="card" id="artikel"><h2>Bestimmter Artikel</h2>
      ${caseTable(G, [["Nom", "der", "die", "das", "die"], ["Akk", hi("den"), "die", "das", "die"],
        ["Dat", hi("dem"), hi("der"), hi("dem"), hi("den") + " …" + hi("n")]],
        "Akkusativ: nur maskulin ändert sich (der → den). Dativ Plural: das Nomen bekommt -n: mit den Freunde<b>n</b>.")}
    </section>

    <section class="card" id="ein"><h2>ein / kein</h2>
      ${caseTable(G, [["Nom", "ein", "eine", "ein", "–"], ["Akk", hi("einen"), "eine", "ein", "–"],
        ["Dat", hi("einem"), hi("einer"), hi("einem"), "–"]])}
      ${caseTable(G, [["Nom", "kein", "keine", "kein", "keine"], ["Akk", hi("keinen"), "keine", "kein", "keine"],
        ["Dat", hi("keinem"), hi("keiner"), hi("keinem"), hi("keinen")]],
        "kein hat dieselben Endungen wie ein, aber auch einen Plural.")}
    </section>

    <section class="card" id="poss"><h2>Possessivartikel</h2>
      ${caseTable(["Possessivartikel"], [["ich", "mein"], ["du", "dein"], ["er / es", "sein"], ["sie", "ihr"],
        ["wir", "unser"], ["ihr", "euer → eure, euren …"], ["sie (Plural)", "ihr"], ["Sie", "Ihr"]], "", "Person")}
      <p class="small">Die Endungen sind wie bei <b>kein</b>. Beispiel mit <b>unser</b>:</p>
      ${caseTable(G, [["Nom", "unser Hund", "unser" + hi("e") + " WG", "unser Haus", "unser" + hi("e") + " Freunde"],
        ["Akk", "unser" + hi("en") + " Hund", "unser" + hi("e") + " WG", "unser Haus", "unser" + hi("e") + " Freunde"],
        ["Dat", "unser" + hi("em") + " Hund", "unser" + hi("er") + " WG", "unser" + hi("em") + " Haus", "unser" + hi("en") + " Freunde" + hi("n")]],
        "Achtung: euer verliert das e vor einer Endung: eure Wohnung, euren Hund (nicht *euere*).")}
    </section>

    <section class="card" id="pron"><h2>Personalpronomen</h2>
      ${caseTable(["Akkusativ", "Dativ"], [["ich", "mich", "mir"], ["du", "dich", "dir"], ["er", "ihn", "ihm"], ["sie", "sie", "ihr"],
        ["es", "es", "ihm"], ["wir", "uns", "uns"], ["ihr", "euch", "euch"], ["sie (Plural)", "sie", "ihnen"], ["Sie", "Sie", "Ihnen"]],
        "ES: mich = me (lo) · mir = me (le). Ich sehe dich (te veo) · Ich helfe dir (te ayudo).", "Nominativ")}
    </section>

    <section class="card" id="praep"><h2>Präpositionen</h2>
      <div class="prep-grid">
        <div><h3>immer Akkusativ</h3><p>durch · für · gegen · ohne · um</p><p class="small muted">Ich laufe durch <b>den</b> Park.</p></div>
        <div><h3>immer Dativ</h3><p>aus · bei · mit · nach · seit · von · zu</p><p class="small muted">Ich fahre mit <b>dem</b> Fahrrad.</p></div>
        <div><h3>Wechselpräpositionen</h3><p>an · auf · hinter · in · neben · über · unter · vor · zwischen</p>
          <p class="small"><b>Wo?</b> → Dativ: Ich bin in <b>dem</b> (im) Park.<br><b>Wohin?</b> → Akkusativ: Ich gehe in <b>den</b> Park.</p></div>
      </div>
      <p class="small"><b>Kurzformen:</b> am = an dem · im = in dem · ins = in das · ans = an das · zum = zu dem · zur = zu der · vom = von dem · beim = bei dem</p>
    </section>

    <section class="card" id="verben"><h2>Verben mit Dativ</h2>
      <p>helfen · danken · gefallen · gehören · schmecken · passen · antworten</p>
      <p class="small muted">Das gefällt <b>mir</b> (me gusta) · Ich helfe <b>dir</b> · Die Jacke gehört <b>meinem</b> Bruder · Das passt <b>mir</b> gut.</p>
    </section>

    <section class="card" id="tricks"><h2>Merktricks</h2>
      <ul class="tricks">
        <li><b>Akkusativ:</b> nur der Mann ändert sich: der → <b>den</b>, ein → <b>einen</b>, er → <b>ihn</b>.</li>
        <li><b>Dativ:</b> maskulin und neutral enden auf <b>-m</b> (dem, einem, meinem), feminin auf <b>-r</b> (der, einer, meiner), Plural auf <b>-n</b> (den Freunden).</li>
        <li><b>Wo oder wohin?</b> Bewegung zu einem Ziel → Akkusativ, Position → Dativ.</li>
        <li><b>Für Spanischsprechende:</b> Wenn du auf Spanisch „le“ sagst, ist es auf Deutsch meistens Dativ.</li>
      </ul>
    </section>`;
  $app.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById(a.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

// ---- router ----------------------------------------------------------------

const routes = [
  [/^#?\/?$/, "home", viewHome],
  [/^#\/lessons$/, "lessons", viewLessons],
  [/^#\/lesson\/(\d+)$/, "lessons", (m) => viewLesson(m[1])],
  [/^#\/review$/, "home", () => viewReview()],
  [/^#\/read$/, "read", viewReadList],
  [/^#\/write$/, "home", () => viewWrite()],
  [/^#\/session\/(full|quick)$/, "home", (m) => viewSession(m[1])],
  [/^#\/progress$/, "progress", viewProgress],
  [/^#\/listen$/, "read", viewListen],
  [/^#\/listen\/(\d+)$/, "read", (m) => viewListenTask(m[1])],
  [/^#\/playlist$/, "read", viewPlaylist],
  [/^#\/drill$/, "home", () => viewDrill(null)],
  [/^#\/cases$/, "home", viewCases],
  [/^#\/drill\/([A-Z0-9_]+)$/, "home", (m) => viewDrill(m[1])],
  [/^#\/text\/(\d+)$/, "read", (m) => viewText(m[1])],
  [/^#\/words$/, "words", viewWords],
  [/^#\/settings$/, "settings", viewSettings],
];

async function route() {
  const hash = location.hash || "#/";
  keyHandler = null;
  $app.innerHTML = skeleton();
  $app.classList.remove("enter"); void $app.offsetWidth; $app.classList.add("enter");
  $bar.hidden = true;
  stopSpeaking();
  for (const [re, name, view] of routes) {
    const m = hash.match(re);
    if (!m) continue;
    document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("on", a.dataset.route === name));
    try {
      await view(m);
      window.scrollTo(0, 0);
    } catch (e) {
      $app.innerHTML = `<p class="empty">Fehler beim Laden: ${esc(e.message)}</p>`;
    }
    return;
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", route);
route();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
