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
    <div><span class="state-dot ${esc(w.state)}" title="${esc(w.state)}"></span><span class="de">${art}${esc(w.lemma)}</span>
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
  </div>`;
}

// ---- views -----------------------------------------------------------------

async function viewHome() {
  const o = await api("/overview");
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
      <h3>Heutige Session</h3>
      <p class="small muted">Lesen, Wiederholen, Grammatik und Schreiben kommen in den nächsten Bauphasen.</p>
      <button class="btn" disabled>Session starten</button>
    </div>`;
}

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

// ---- router ----------------------------------------------------------------

const routes = [
  [/^#?\/?$/, "home", viewHome],
  [/^#\/lessons$/, "lessons", viewLessons],
  [/^#\/lesson\/(\d+)$/, "lessons", (m) => viewLesson(m[1])],
  [/^#\/words$/, "words", viewWords],
  [/^#\/settings$/, "settings", viewSettings],
];

async function route() {
  const hash = location.hash || "#/";
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
