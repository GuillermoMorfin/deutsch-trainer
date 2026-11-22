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

// ---- shared pieces ---------------------------------------------------------

function wordHTML(w) {
  const art = w.article ? `<span class="art ${w.article}">${w.article}</span> ` : "";
  const extras = [];
  if (w.pos === "NOUN" && w.plural) extras.push(w.plural === "-" ? "kein Plural" : `Pl. die ${esc(w.plural)}`);
  if (w.pos === "VERB" && w.partizip2) extras.push(`${w.aux === "sein" ? "ist" : "hat"} ${esc(w.partizip2)}`);
  return `<li class="word">
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
  const [o, allErrors] = await Promise.all([api("/overview"), api("/errors?limit=5")]);
  const errors = allErrors.filter((e) => e.grammar_code);
  const l = o.current_lesson;
  $app.innerHTML = `
    <p class="eyebrow">Momente A2.1 · Deutsch-Trainer</p>
    <h1>Hallo! 👋</h1>
    <div class="stats">
      <div class="stat"><b>${o.known_words}</b><span>Wörter bekannt</span></div>
      <div class="stat"><b>${o.cards_due}</b><span>heute fällig</span></div>
      <div class="stat"><b>${pct(l.mastery)}</b><span>Lektion ${l.number}</span></div>
    </div>
    <a class="card hero" href="#/lesson/${l.number}" style="display:block;text-decoration:none;color:inherit">
      <p class="eyebrow">Aktuelle Lektion ${l.number} · ${esc(l.theme)}</p>
      <h2>${esc(l.title)}</h2>
      <div class="progress" aria-label="Fortschritt"><i style="width:${pct(l.mastery)}"></i></div>
      <p class="small muted">${l.known_count} von ${l.word_count} Lektionswörtern sicher · Ziel 80 %</p>
    </a>
    <div class="card">
      <h3>Wortschatz wiederholen</h3>
      <p class="small muted">${o.cards_due ? `${o.cards_due} Karten fällig` : "Keine Karten fällig"} ·
        bis zu ${o.settings.daily_new_word_cap} neue Wörter aus Lektion ${l.number} pro Tag</p>
      <a class="btn" href="#/review">Jetzt wiederholen</a>
    </div>
    <div class="card">
      <h3>Grammatik üben</h3>
      <p class="small muted">8 kurze Übungen, mehr davon, wo du Fehler machst.</p>
      ${errors.length ? `<p class="small"><strong>Häufige Fehler:</strong> ${errors.map((e) =>
        `<a href="#/drill/${esc(e.grammar_code)}">${esc(e.name)}</a> (${e.count}×)`).join(" · ")}</p>` : ""}
      <a class="btn secondary" href="#/drill">Grammatik üben</a>
    </div>
    <div class="card">
      <h3>Lesen</h3>
      <p class="small muted">Kurze Texte über dein Leben in Berlin, fast nur mit Wörtern, die du kennst.</p>
      <a class="btn secondary" href="#/read">Zum Lesen</a>
    </div>`;
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

const POS_HINT = { NOUN: "Nomen · mit Artikel", VERB: "Verb · Infinitiv", ADJ: "Adjektiv", ADV: "Adverb",
  PHRASE: "Ausdruck", CONJ: "Konjunktion", PRON: "Pronomen", ADP: "Präposition", DET: "Artikel/Begleiter", INTJ: "Ausruf" };

async function viewReview() {
  $app.innerHTML = `<p class="empty">Karten werden geladen…</p>`;
  const start = await api("/review/start", { method: "POST", body: { new_words: true } });
  let queue = start.queue;
  let done = 0, correct = 0;

  const finish = () => {
    $app.innerHTML = `
      <div class="card hero review-done">
        <p class="eyebrow">Fertig für jetzt</p>
        <h1>Gut gemacht! 🎉</h1>
        <p>${done} Karten wiederholt${done ? ` · ${Math.round((correct / done) * 100)} % richtig` : ""}.</p>
        <p class="small muted">Neue Wörter heute: ${start.new_today}. Die nächsten Karten plant FSRS für dich.</p>
        <a class="btn" href="#/">Zur Übersicht</a>
      </div>`;
  };

  const next = async () => {
    if (!queue.length) {
      // Learning steps may have brought cards back into the window.
      queue = (await api("/review/queue")).queue;
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
      ${c.lesson_number ? ` · Lektion ${c.lesson_number}` : " · A1"}${c.reps === 0 ? ' · <span class="chip amber">neu</span>' : ""}</p>`;

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
      <div class="flash">
        <div class="flash-word">${nounHTML(c)}</div>
        ${c.source_sentence ? `<p class="flash-sentence">${esc(c.source_sentence)}</p>` : ""}
        <div class="flash-answer" hidden>
          <div class="flash-gloss">${esc(c.gloss_es)}</div>
          <div class="small muted">${esc(c.gloss_en || "")}${formsHTML(c) ? ` · ${formsHTML(c)}` : ""}</div>
        </div>
      </div>
      <div class="review-actions">
        <button class="btn reveal">Zeigen</button>
        <div class="rate-row" hidden>${RATINGS.map(([v, label, cls]) =>
          `<button class="rate ${cls}" data-rating="${v}">${label}</button>`).join("")}</div>
      </div>`;
    const reveal = () => {
      $app.querySelector(".flash-answer").hidden = false;
      $app.querySelector(".reveal").hidden = true;
      $app.querySelector(".rate-row").hidden = false;
    };
    $app.querySelector(".reveal").addEventListener("click", reveal);
    $app.querySelectorAll(".rate").forEach((b) => b.addEventListener("click", async () => {
      if (await submit(c, { rating: +b.dataset.rating, duration_ms: Math.round(performance.now() - t0) })) next();
    }));
    keyHandler = (e) => {
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (!$app.querySelector(".flash-answer").hidden) return; reveal(); }
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
      fb.innerHTML = `<strong>${esc(r.check.message)}</strong>
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

async function viewLessons() {
  const lessons = await api("/lessons");
  $app.innerHTML = `
    <h1>Lektionen</h1>
    <ul class="lesson-list">${lessons.map((l) => `
      <li><a class="lesson-row ${l.status}" href="#/lesson/${l.number}">
        <span class="num">${l.number}</span>
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

    <div class="card">
      <h2>Grammatik</h2>
      ${grammar.map(grammarHTML).join("")}
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
    </div>`;

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

async function viewWords() {
  const lessons = await api("/lessons");
  $app.innerHTML = `
    <h1>Wörter</h1>
    <div class="toolbar">
      <input type="search" id="q" placeholder="Suchen (Deutsch, Español, English)…" aria-label="Suchen">
      <select id="lesson" aria-label="Lektion">
        <option value="">Alle</option>
        <option value="0">A1 Basis</option>
        ${lessons.map((l) => `<option value="${l.number}">Lektion ${l.number}</option>`).join("")}
      </select>
      <select id="pos" aria-label="Wortart">
        <option value="">Alle Wortarten</option>
        <option value="NOUN">Nomen</option><option value="VERB">Verben</option>
        <option value="ADJ">Adjektive</option><option value="ADV">Adverbien</option>
      </select>
    </div>
    <p class="small muted" id="count"></p>
    <ul class="word-list" id="list"></ul>`;

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
    </div>`;
  $app.querySelector("#save").addEventListener("click", async () => {
    await api("/settings", { method: "PUT", body: {
      current_lesson: +$app.querySelector("#cur").value,
      daily_new_word_cap: +$app.querySelector("#cap").value,
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

function speak(text, onEnd) {
  if (!("speechSynthesis" in window)) { toast("Vorlesen wird hier nicht unterstützt"); return; }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "de-DE";
  u.rate = 0.9;
  const voice = speechSynthesis.getVoices().find((v) => v.lang.startsWith("de"));
  if (voice) u.voice = voice;
  u.onend = onEnd;
  speechSynthesis.speak(u);
}

async function viewText(id) {
  const d = await api(`/texts/${id}`);
  const { text: t, tokens, lemmas, questions } = d;
  const started = Date.now();
  const paragraphs = [[]];
  tokens.forEach((tok, i) => tok.br ? (paragraphs.at(-1).length && paragraphs.push([])) : paragraphs.at(-1).push([tok, i]));
  const plain = tokens.map((tk) => tk.br ? "\n" : tk.t + tk.ws).join("");

  $app.innerHTML = `
    <p class="eyebrow"><a href="#/read">← Lesen</a> · Lektion ${t.lesson_number} · ${pct(t.coverage)} bekannt</p>
    <h1>${esc(t.title)}</h1>
    <div class="toolbar">
      <button class="btn secondary" id="speak">▶ Vorlesen</button>
      <span class="small muted" style="align-self:center">Tippe auf ein Wort für die Übersetzung.</span>
    </div>
    <article class="reading">${paragraphs.filter((p) => p.length).map((p) => `<p>${p.map(([tok, i]) =>
      tok.id ? `<span class="tok${tok.target ? " target" : ""}" data-i="${i}" role="button" tabindex="0">${esc(tok.t)}</span>${esc(tok.ws)}`
             : `${esc(tok.t)}${esc(tok.ws)}`).join("")}</p>`).join("")}</article>
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

  // audio
  const $speak = $app.querySelector("#speak");
  let speaking = false;
  $speak.addEventListener("click", () => {
    if (speaking) { speechSynthesis.cancel(); speaking = false; $speak.textContent = "▶ Vorlesen"; return; }
    speaking = true; $speak.textContent = "■ Stopp";
    speak(plain, () => { speaking = false; $speak.textContent = "▶ Vorlesen"; });
  });

  // comprehension
  const $q = $app.querySelector("#questions");
  $app.querySelector("#done-reading").addEventListener("click", (ev) => {
    ev.target.hidden = true;
    $sheet.hidden = true;
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    const seconds = (Date.now() - started) / 1000;
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
        <h3>Super! 🎉</h3>
        <p class="small">${r.introduced ? `${r.introduced} neue Wörter sind jetzt in deinen Karten.` : "Alle Wörter sind schon in deinen Karten."}
          ${r.wpm ? ` Lesetempo: ${r.wpm} Wörter/Minute.` : ""}</p>
        <a class="btn" href="#/review">Neue Wörter üben</a></div>`);
    });
    $q.scrollIntoView({ behavior: "smooth" });
  });
}

// ---- grammar drills -----------------------------------------------------------

const UMLAUT_KEYS = ["ä", "ö", "ü", "ß"];

async function viewDrill(code) {
  $app.innerHTML = `<p class="empty">Übungen werden geladen…</p>`;
  const { items } = await api(`/drills/session?n=8${code ? `&code=${encodeURIComponent(code)}` : ""}`);
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
      ${code ? generateBtn(code) : ""}`;
    wireGenerate();
    return;
  }

  const finish = () => {
    const codes = Object.entries(missed);
    $app.innerHTML = `
      <div class="card hero review-done">
        <p class="eyebrow">Grammatik</p>
        <h1>${right === items.length ? "Perfekt! 🎉" : right / items.length >= 0.6 ? "Gut gemacht!" : "Dranbleiben! 💪"}</h1>
        <p>${right} von ${items.length} richtig.</p>
      </div>
      ${codes.length ? `<div class="card"><h3>Nochmal üben</h3>${codes.map(([c, name]) => `
        <div class="toolbar" style="align-items:center;justify-content:space-between">
          <span>${esc(name)}</span>
          <span><a class="btn secondary" href="#/drill/${encodeURIComponent(c)}">Üben</a></span>
        </div>`).join("")}</div>` : ""}
      ${code ? `<div class="card"><h3>Mehr davon?</h3>${generateBtn(code)}</div>` : ""}
      <a class="btn" href="#/">Zur Übersicht</a>`;
    wireGenerate();
  };

  const header = () => `
    <div class="review-top">
      <a href="#/" class="small">✕ Beenden</a>
      <span class="small muted">${idx + 1} / ${items.length}</span>
    </div>
    <div class="progress"><i style="width:${pct(idx / items.length)}"></i></div>`;

  const feedback = (r) => `
    <div class="feedback ${r.correct ? "ok" : "bad"}">
      <strong>${r.correct ? "Richtig!" : "Leider falsch."}</strong>
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
    } else {
      body = `<p class="drill-sentence">${esc(it.prompt)}</p>
        <div class="order-line" aria-label="Deine Antwort"></div>
        <div class="order-pool">${it.tokens.map((t, i) => `<button class="chip-btn" data-i="${i}">${esc(t)}</button>`).join("")}</div>
        <div class="toolbar"><button class="btn secondary order-reset">Zurücksetzen</button>
          <button class="btn order-check" disabled>Prüfen</button></div>`;
    }
    $app.innerHTML = `${header()}
      <p class="eyebrow">${{ gap: "Lücke füllen", choice: "Wähle", order: "Sätze bauen" }[it.type]}
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
      $fb.innerHTML = feedback(r);
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

// ---- router ----------------------------------------------------------------

const routes = [
  [/^#?\/?$/, "home", viewHome],
  [/^#\/lessons$/, "lessons", viewLessons],
  [/^#\/lesson\/(\d+)$/, "lessons", (m) => viewLesson(m[1])],
  [/^#\/review$/, "home", viewReview],
  [/^#\/read$/, "read", viewReadList],
  [/^#\/drill$/, "home", () => viewDrill(null)],
  [/^#\/drill\/([A-Z0-9_]+)$/, "home", (m) => viewDrill(m[1])],
  [/^#\/text\/(\d+)$/, "read", (m) => viewText(m[1])],
  [/^#\/words$/, "words", viewWords],
  [/^#\/settings$/, "settings", viewSettings],
];

async function route() {
  const hash = location.hash || "#/";
  keyHandler = null;
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
