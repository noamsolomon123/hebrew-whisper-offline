"use strict";
const $ = s => document.querySelector(s);
// The server only answers its own page: every request carries this header (see appbase.request_ok).
const _fetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => _fetch(url, { ...opts, headers: { ...(opts.headers || {}), "X-HW": "1" } });
let jobs = [], sel = null, model = {}, lastRendered = "", fails = 0;
let project = { id: null, name: "", dirty: false };
const edits = {};     // job id -> text the user changed
const tabOf = {};     // job id -> "text" | "ai"
const doneTasks = {}; // "jobid:index" -> true (ticked in the page)
const uploads = {};   // temp id -> {name, size, pct}
const segCache = {};  // job id -> [[start, end, text]] (fetched once a job is done)
const tx = $("#text"), hl = $("#hl"), au = $("#au");

const KEYS = [["Space", "ניגון / עצירה"], ["Ctrl + Space", "ניגון / עצירה גם בזמן הקלדה"],
  ["J", "5 שניות אחורה"], ["K", "עצירה"], ["L", "ניגון; לחיצה נוספת מאיצה"],
  ["← / →", "5 שניות אחורה / קדימה"], ["Ctrl + F", "חיפוש בתמלול"], ["Ctrl + H", "חיפוש והחלפה"],
  ["Ctrl + S", "שמירת הפרויקט"], ["F2", "שינוי שם ההקלטה"], ["Esc", "סגירת חלון / חיפוש"]];
$("#keysList").innerHTML = KEYS.map(([k, v]) => `<span>${k.split(" ").map(x => /^[+/]$/.test(x) ? x : `<kbd>${x}</kbd>`).join(" ")}</span><span>${v}</span>`).join("");

function fmtTime(s) {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0");
}
function fmtSize(b) { return b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : (b / 1e6).toFixed(1) + " MB"; }
function fmtWhen(t) {
  if (!t) return "";
  const d = new Date(t * 1000), now = new Date(), hm = d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === now.toDateString() ? "היום " + hm : d.toLocaleDateString("he-IL", { day: "numeric", month: "numeric" }) + " " + hm;
}
function toast(t) { const e = $("#toast"); e.textContent = t; e.classList.add("on"); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove("on"), 2000); }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
const selJob = () => jobs.find(x => x.id === sel);
const stem = j => j.name.replace(/\.[^.]+$/, "");

function etaText(j) {
  return j.eta != null ? "נותרו כ-" + fmtTime(j.eta) : "מחשב זמן…";
}
function stateText(j) {
  if (j.uploading) return "מעלה… " + Math.round(j.pct) + "%";
  if (j.state === "queued") return j.ahead ? `בתור · ${j.ahead} לפני` : "בתור · הבא";
  if (j.state === "running") return "מתמלל " + Math.round(j.progress || 0) + "% · " + etaText(j);
  if (j.state === "done") return fmtTime(j.duration) + " · " + fmtWhen(j.created) + (j.device === "cpu" ? " · מעבד" : "");
  if (j.state === "error") return '<span class="e">התמלול נכשל</span>';
  return "";
}
function aiBadge(j) {
  if (j.ai_state === "done") return '<span class="badge">AI</span>';
  if (j.ai_state === "running" || j.ai_state === "queued") return '<span class="badge">AI…</span>';
  return "";
}

function renderList() {
  const all = [...Object.values(uploads), ...jobs.slice().reverse()];
  $("#list").innerHTML = (all.length ? `<div class="lhead">${all.length === 1 ? "הקלטה אחת" : all.length + " הקלטות"}</div>` : "") + all.map(j => {
    const pct = j.uploading ? j.pct : (j.state === "done" ? 100 : (j.progress || 0));
    const cls = ["job", j.state || "", j.id === sel ? "sel" : ""].join(" ");
    const busy = j.uploading || j.state === "running" || j.ai_state === "running";
    return `<div class="${cls}" data-id="${j.id}" role="option" aria-selected="${j.id === sel}" tabindex="0">
      <div class="row"><span class="name" title="${esc(j.name)}">${esc(stem(j))}</span>${aiBadge(j)}
      ${busy ? "" : `<button class="x" data-rm="${j.id}" title="הסרה מהרשימה" aria-label="הסרה מהרשימה">×</button>`}</div>
      <div class="meta">${stateText(j)}</div>
      <div class="bar"><i style="width:${pct}%"></i></div></div>`;
  }).join("");
}

function show(which) {  // "placeholder" | "text" | "ai"
  $("#placeholder").hidden = which !== "placeholder";
  $("#txwrap").hidden = $("#hint").hidden = which !== "text";
  $("#aiView").hidden = which !== "ai";
  if (which !== "text") closeFind(true);
}
function placeholder(html) { show("placeholder"); $("#placeholder").innerHTML = `<div class="empty">${html}</div>`; }
function emptyState() {
  if (model.model === "error")
    return placeholder(`<b style="color:var(--err)">מודל התמלול לא נטען</b><div class="why">${esc(model.error || "")}</div>
      <div class="why">כדאי לסגור את החלון ולהפעיל שוב את HEBREW-WHISPER.bat. אם זה חוזר - להריץ את SELFTEST.bat.</div>`);
  placeholder(`<svg class="ico" width="54" height="54" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" aria-hidden="true"><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"/><path d="M19 11a7 7 0 0 1-14 0M12 18v3"/></svg>
    <b>גררו קובץ שמע או וידאו כדי להתחיל</b>אפשר כמה קבצים יחד, או להקליט מהמיקרופון. הטקסט מופיע תוך כדי, ונשמר גם בתיקיית התוצאות (TXT + Word).
    <div class="act"><button class="primary" onclick="$('#pick').click()">בחירת קבצים</button><button onclick="$('#recBtn').click()">הקלטה</button></div>
    <div class="keys">${$("#keysList").innerHTML.split("</span>").slice(0, 10).join("</span>")}</span></div>`);
}
function currentText(j) { return j.id in edits ? edits[j.id] : (j.edited || j.text); }
function parseT(s) {
  const p = String(s || "").trim().split(":").map(Number);
  return p.length < 2 || p.some(isNaN) ? null : p.reduce((a, v) => a * 60 + v, 0);
}
const timeBtn = t => t ? (parseT(t) != null ? `<button class="time" data-t="${parseT(t)}" title="ניגון מנקודה זו">${esc(t)}</button>` : `<span class="time">${esc(t)}</span>`) : "";

function renderAi(j) {
  const r = j.ai;
  if (j.ai_state === "queued" || j.ai_state === "running")
    return placeholder(`<div class="spin"></div><b>${esc(j.ai_msg || "מסדר…")}</b>gemma4 קורא את התמלול ומסדר אותו. בהקלטה ארוכה זה לוקח כמה דקות. אפשר להמשיך לעבוד בינתיים.`);
  if (j.ai_state === "error")
    return placeholder(`<b style="color:var(--err)">ה-AI לא הצליח</b><div class="why">${esc(j.ai_error)}</div><div class="act"><button class="ai" onclick="runAi()">לנסות שוב</button></div>`);
  if (!r) return placeholder("<b>עוד לא סודר</b>לחצו על 'סידור עם AI'.");
  show("ai");
  const card = (title, n, body, wide) => body ? `<div class="card${wide ? " wide" : ""}"><h3>${title}${n ? `<span class="n">${n}</span>` : ""}</h3>${body}</div>` : "";
  const list = xs => xs.length ? `<ul class="bul">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  const tasks = r.tasks.length ? `<ul>${r.tasks.map((t, i) => {
    const k = j.id + ":" + i, d = k in doneTasks ? doneTasks[k] : (j.done_tasks || []).includes(i);
    const chips = [t.priority === "גבוהה" && `<span class="chip hot">דחוף</span>`,
                   t.owner && `<span class="chip who">${esc(t.owner)}</span>`, t.due && `<span class="chip due">עד ${esc(t.due)}</span>`,
                   timeBtn(t.time)].filter(Boolean).join("");
    return `<li class="task${d ? " doneT" : ""}"><input type="checkbox" data-task="${k}"${d ? " checked" : ""} aria-label="בוצע"><div><div class="tt">${esc(t.task)}</div>${chips ? `<div class="chips">${chips}</div>` : ""}</div></li>`;
  }).join("")}</ul>` : "";
  const tl = r.timeline.length ? `<div class="tl">${r.timeline.map(t => `<div class="ev">${t.time ? timeBtn(t.time) + " · " : ""}${esc(t.event)}</div>`).join("")}</div>` : "";
  const topics = r.topics.length ? r.topics.map(t => `<div class="topic"><h4>${esc(t.title)}${timeBtn(t.time)}</h4>${list(t.points)}</div>`).join("") : "";
  const nothing = !r.summary && !r.tasks.length && !r.key_points.length && !r.timeline.length;
  $("#aiView").innerHTML = `
    <div class="ai-head">${r.kind ? `<div class="kind">${esc(r.kind)}</div>` : ""}<h2>${esc(r.title || j.name)}</h2>
      ${(r.speakers || []).length ? `<div class="people">${r.speakers.map(p => `<span class="person"><b>${esc(p.name)}</b>${p.role ? " · " + esc(p.role) : ""}</span>`).join("")}</div>` : ""}
      <div class="by">סודר ע"י ${esc(r.model || "AI")} · כדאי לבדוק מול התמלול${j.has_audio ? " · לחיצה על זמן מנגנת מאותה נקודה" : ""}</div></div>
    ${r.summary ? `<div class="summary">${esc(r.summary)}</div>` : ""}
    <div class="grid">
      ${card("משימות", r.tasks.length, tasks)}
      ${card("החלטות", r.decisions.length, list(r.decisions))}
      ${card("נקודות עיקריות", r.key_points.length, list(r.key_points))}
      ${card("ציר זמן", r.timeline.length, tl)}
      ${card("נושאים", r.topics.length, topics, true)}
      ${card("שאלות פתוחות", r.open_questions.length, list(r.open_questions))}
    </div>
    ${nothing ? '<div class="empty">ה-AI לא מצא מה לסדר בהקלטה הזאת.</div>' : ""}`;
}

function renderText() {
  const j = selJob();
  const can = !!j && j.state === "done";
  for (const b of ["#copy", "#dlTxt", "#dlDocx"]) $(b).disabled = !can;
  $("#findBtn").disabled = !(j && j.text);
  $("#renameBtn").hidden = !j;
  $("#aiBtn").disabled = !can || j.ai_state === "running" || j.ai_state === "queued" || model.model !== "ready";
  $("#edited").hidden = !(can && currentText(j) !== j.text);
  const hasAi = j && j.ai_state;
  $("#tabs").hidden = !hasAi;
  const tab = hasAi ? (tabOf[sel] || "ai") : "text";
  document.querySelectorAll(".tab").forEach(b => { b.classList.toggle("on", b.dataset.tab === tab); b.setAttribute("aria-selected", b.dataset.tab === tab); });
  $("#tActions").hidden = tab !== "text";
  $("#aActions").hidden = !(tab === "ai" && j && j.ai);
  updatePlayer(j);
  if (!j) {
    $("#tTitle").textContent = "—"; $("#tMeta").textContent = "";
    const k = "empty:" + model.model;
    if (lastRendered !== k) { emptyState(); lastRendered = k; }
    return;
  }
  $("#tTitle").textContent = stem(j); $("#tTitle").title = j.name;
  $("#tMeta").innerHTML = j.state === "done" ? fmtTime(j.duration) + " · תומלל ב-" + fmtTime(j.seconds) : stateText(j);
  const live = j.state === "running" && !j.text ? Math.round(j.progress) + ":" + (j.eta | 0) : "";
  const key = [j.id, tab, j.state, j.text.length, j.ai_state, j.ai_msg, j.ahead, live].join(":");
  if (key === lastRendered) return;
  lastRendered = key;
  if (tab === "ai") return renderAi(j);
  if (j.state === "error") {
    const why = /פגום|פורמט/.test(j.error || "") ? "אפשר לנסות להמיר את הקובץ ל-MP3 או WAV ולהעלות שוב."
      : /זיכרון|memory|cuda/i.test(j.error || "") ? "כרטיס המסך עסוק. כדאי לחכות דקה ולנסות שוב." : "אפשר לנסות שוב, או להעלות את הקובץ מחדש.";
    return placeholder(`<b style="color:var(--err)">התמלול נכשל</b><div class="why">${esc(j.error || "")}</div><div class="why">${why}</div>
      <div class="act">${j.has_audio && !/פגום|פורמט/.test(j.error || "") ? `<button class="primary" onclick="retry('${j.id}')">לנסות שוב</button>` : ""}<button onclick="removeJob('${j.id}')">הסרה מהרשימה</button></div>`);
  }
  if (!j.text) {
    if (j.state === "queued")
      return placeholder(`<b>ממתין בתור</b>${j.ahead ? `${j.ahead === 1 ? "קובץ אחד" : j.ahead + " קבצים"} לפני הקובץ הזה. ` : ""}התמלול יתחיל אוטומטית.`);
    return placeholder(`<div class="spin blue"></div><b>מתמלל… ${Math.round(j.progress || 0)}%</b>${j.progress ? etaText(j) + ". " : "טוען את הקובץ. "}הטקסט יופיע כאן תוך כדי.
      <div class="prog"><i style="width:${j.progress || 0}%"></i></div>`);
  }
  const atBottom = $("#txwrap").hidden || tx.scrollTop + tx.clientHeight >= tx.scrollHeight - 30;
  show("text");
  tx.readOnly = j.state !== "done";
  if (document.activeElement !== tx || tx.readOnly) tx.value = currentText(j);
  if (j.state === "running" && atBottom) tx.scrollTop = tx.scrollHeight;
  $("#txwrap").classList.toggle("seekable", !!j.has_audio);
  $("#hintPlay").hidden = !j.has_audio;
  if (j.state === "done" && !segCache[j.id]) loadSegs(j.id);
  remap(); refind(); paint();
}

async function poll() {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    const d = await r.json();
    fails = 0; $("#gone").style.display = "none";
    model = d.model; jobs = d.jobs; project = d.project; renderProject(); renderUpd(d);
    if (updating) return;
    if (project.restored && !window._restoredShown) {
      window._restoredShown = true;
      toast("שוחזרה עבודה שלא נשמרה מהפעם הקודמת");
    }
    const dot = $("#mdot"), t = $("#mtext");
    dot.className = "dot";
    if (model.model === "loading") { dot.classList.add("busy"); t.textContent = "טוען מודל…"; }
    else if (model.model === "error") { dot.classList.add("err"); t.textContent = "שגיאה בטעינת המודל"; t.title = model.error || ""; }
    else { dot.classList.add("ok"); t.textContent = model.device === "cuda" ? "מוכן · כרטיס גרפי" : "מוכן · מעבד (איטי)"; }
    const run = jobs.find(j => j.state === "running");
    if (run) t.textContent = "מתמלל " + Math.round(run.progress || 0) + "%" + (jobs.filter(j => j.state === "queued").length ? " · עוד " + jobs.filter(j => j.state === "queued").length + " בתור" : "");
    if (run || jobs.some(j => j.ai_state === "running")) dot.classList.add("busy");
    if (!sel || !selJob()) {
      const pick = run || jobs[jobs.length - 1];
      sel = pick ? pick.id : null;
    }
    renderList(); renderText();
  } catch (e) {
    if (++fails > 3 && !updating) $("#gone").style.display = "flex";
  }
}

function upload(file, keep) {
  const tmp = "u" + Math.random().toString(36).slice(2);
  uploads[tmp] = { id: tmp, name: file.name, size: file.size, pct: 0, uploading: true };
  renderList();
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name) + (keep ? "&keep=1" : ""));
  xhr.setRequestHeader("X-HW", "1");
  xhr.upload.onprogress = e => { if (e.lengthComputable) { uploads[tmp].pct = 100 * e.loaded / e.total; renderList(); } };
  xhr.onload = () => {
    delete uploads[tmp];
    try { const d = JSON.parse(xhr.responseText); if (d.id) { sel = d.id; lastRendered = ""; } else toast("העלאה נכשלה"); }
    catch (e) { toast("העלאה נכשלה"); }
    poll();
  };
  xhr.onerror = () => { delete uploads[tmp]; toast("העלאה נכשלה"); renderList(); };
  xhr.send(file);
}
function addFiles(list) { for (const f of list) if (f.size > 0) upload(f); }

const drop = $("#drop");
drop.onclick = () => $("#pick").click();
drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#pick").click(); } };
$("#pick").onchange = e => { addFiles(e.target.files); e.target.value = ""; };
for (const ev of ["dragenter", "dragover"]) document.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) document.addEventListener(ev, e => { e.preventDefault(); if (ev === "drop" || !e.relatedTarget) drop.classList.remove("over"); });
document.addEventListener("drop", e => addFiles(e.dataTransfer.files));

function selectJob(id) { if (id === sel) return; sel = id; lastRendered = ""; renderList(); renderText(); }
async function removeJob(id) {
  await fetch("/api/remove?id=" + id, { method: "POST" });
  if (sel === id) sel = null;
  lastRendered = ""; poll();
}
async function retry(id) {
  const r = await fetch("/api/retry?id=" + id, { method: "POST" });
  if (!r.ok) toast("אין את הקובץ המקורי. גררו אותו שוב.");
  lastRendered = ""; poll();
}
$("#list").onclick = e => {
  const rm = e.target.closest("[data-rm]");
  if (rm) { e.stopPropagation(); return removeJob(rm.dataset.rm); }
  const j = e.target.closest(".job");
  if (j && !j.dataset.id.startsWith("u")) selectJob(j.dataset.id);
};
$("#list").ondblclick = e => { const j = e.target.closest(".job"); if (j && !j.dataset.id.startsWith("u")) { selectJob(j.dataset.id); rename(); } };
$("#list").onkeydown = e => {
  const j = e.target.closest(".job"); if (!j) return;
  if (e.key === "Enter") selectJob(j.dataset.id);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); const n = e.key === "ArrowDown" ? j.nextElementSibling : j.previousElementSibling;
    if (n && n.classList.contains("job")) { n.focus(); selectJob(n.dataset.id); $(`.job[data-id="${n.dataset.id}"]`)?.focus(); }
  }
};
$("#tabs").onclick = e => {
  const b = e.target.closest(".tab"); if (!b || !sel) return;
  tabOf[sel] = b.dataset.tab; lastRendered = ""; renderText();
};
$("#aiView").onchange = e => {
  const k = e.target.dataset.task; if (!k) return;
  doneTasks[k] = e.target.checked;
  e.target.closest(".task").classList.toggle("doneT", e.target.checked);
  const [id, i] = k.split(":");
  fetch(`/api/task?id=${id}&k=${i}&v=${e.target.checked ? 1 : 0}`, { method: "POST" });
};
$("#aiView").onclick = e => { const b = e.target.closest("[data-t]"); if (b) seek(+b.dataset.t, true); };

let editTimer = null, editFlush = null;
async function flushEdit() {  // a pending (debounced) edit must reach the server before a save
  clearTimeout(editTimer);
  if (editFlush) { const f = editFlush; editFlush = null; await f(); }
}
function textChanged() {
  const j = selJob(); if (!j || j.state !== "done") return;
  edits[j.id] = tx.value;
  $("#edited").hidden = tx.value === j.text;
  clearTimeout(editTimer);
  const id = j.id, val = tx.value === j.text ? "" : tx.value;
  editFlush = () => fetch("/api/edit?id=" + id, { method: "POST",
    body: new Blob([val], { type: "text/plain;charset=utf-8" }) });
  editTimer = setTimeout(() => flushEdit(), 500);
  remap(); refind(); paint();
}
tx.oninput = textChanged;

async function rename() {
  const j = selJob(); if (!j) return;
  const v = await promptBox("שינוי שם ההקלטה", stem(j));
  if (!v || v === stem(j)) return;
  const r = await fetch("/api/rename?id=" + j.id + "&name=" + encodeURIComponent(v), { method: "POST" });
  if (!r.ok) return toast("שינוי השם נכשל");
  lastRendered = ""; poll();
}
$("#renameBtn").onclick = rename;
$("#tTitle").ondblclick = rename;

/* ---- player: the job's audio, synced to the text ---- */
const player = { id: null, rate: 1, base: 1, curSeg: -1, userScroll: 0, failed: false };
let segMap = [];   // [{a, z, s, e}] : segment times -> character range in the textarea
const RATES = [1, 1.25, 1.5, 2, 0.75];
function updatePlayer(j) {
  const has = !!(j && j.has_audio && j.state !== "error");
  $("#player").hidden = !has;
  if (!has) { if (player.id) { au.pause(); au.removeAttribute("src"); au.load(); player.id = null; } return; }
  if (player.id !== j.id) {
    player.id = j.id; player.curSeg = -1; player.failed = false;
    au.src = "/api/audio?id=" + j.id; au.playbackRate = player.base;
    $("#pMsg").textContent = ""; paintTime();
  }
}
function paintTime() {
  const d = isFinite(au.duration) ? au.duration : (selJob() || {}).duration || 0;
  $("#pTime").textContent = fmtTime(au.currentTime) + " / " + fmtTime(d);
  if (!player.dragging) $("#pSeek").value = d ? Math.round(1000 * au.currentTime / d) : 0;
  const playing = !au.paused;
  $("#icPlay").toggleAttribute("hidden", playing); $("#icPause").toggleAttribute("hidden", !playing);
  $("#pPlay").setAttribute("aria-label", playing ? "עצירה" : "ניגון");
  $("#pRate").textContent = (Math.round(au.playbackRate * 100) / 100) + "×";
}
function seek(t, play) {
  if (!player.id || player.failed) return;
  au.currentTime = Math.max(0, t);
  if (play) au.play().catch(() => {});
  player.userScroll = 0; syncSeg(true);
}
function toggle() {
  if (!player.id || player.failed) return;
  if (au.paused) { au.playbackRate = player.base; au.play().catch(() => {}); } else au.pause();
}
function nudge(dt) { if (player.id) { au.currentTime = Math.max(0, Math.min((au.duration || 1e9), au.currentTime + dt)); syncSeg(true); } }
$("#pPlay").onclick = toggle;
$("#pBack").onclick = () => nudge(-5);
$("#pFwd").onclick = () => nudge(5);
$("#pRate").onclick = () => { player.base = RATES[(RATES.indexOf(player.base) + 1) % RATES.length]; au.playbackRate = player.base; paintTime(); };
$("#pSeek").oninput = e => { player.dragging = true; const d = au.duration || 0; if (d) { au.currentTime = d * e.target.value / 1000; paintTime(); } };
$("#pSeek").onchange = () => { player.dragging = false; syncSeg(true); };
for (const ev of ["play", "pause", "ratechange", "loadedmetadata", "seeked"]) au.addEventListener(ev, paintTime);
au.addEventListener("timeupdate", () => { paintTime(); syncSeg(false); });
au.addEventListener("error", () => {
  if (!player.id) return;
  player.failed = true;
  $("#pMsg").textContent = "אי אפשר לנגן את הפורמט הזה בחלון. הטקסט לא נפגע.";
});

async function loadSegs(id) {
  segCache[id] = [];
  try { segCache[id] = (await (await fetch("/api/segments?id=" + id)).json()).segments || []; } catch (e) { delete segCache[id]; }
  if (id === sel) { remap(); paint(); }
}
function remap() {   // finds each segment's words in the (maybe edited) text
  const j = selJob(), segs = j && segCache[j.id];
  segMap = [];
  if (!segs || !segs.length) return;
  const text = tx.value; let pos = 0;
  for (const [a, z, raw] of segs) {
    const t = (raw || "").trim(); if (!t) continue;
    let i = text.indexOf(t, pos), len = t.length, part = false;
    if (i < 0 || i - pos > 600) {
      const pre = t.slice(0, Math.min(14, t.length)); const k = text.indexOf(pre, pos);
      if (k >= 0 && k - pos <= 600) { i = k; len = pre.length; part = true; } else i = -1;
    }
    if (i < 0) continue;
    segMap.push({ a, z, s: i, e: i + len, part }); pos = i + len;
  }
  for (let n = 0; n < segMap.length; n++) if (segMap[n].part) {   // an edited segment: up to the next one
    const end = n + 1 < segMap.length ? segMap[n + 1].s : text.length;
    segMap[n].e = segMap[n].s + text.slice(segMap[n].s, end).trimEnd().length;
  }
  player.curSeg = -1;
}
function segAt(t) {
  let lo = 0, hi = segMap.length - 1, best = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (segMap[m].a <= t + 0.05) { best = m; lo = m + 1; } else hi = m - 1; }
  return best;
}
function syncSeg(force) {
  if ($("#txwrap").hidden || !segMap.length) return;
  const i = au.currentTime > 0 || !au.paused ? segAt(au.currentTime) : -1;
  if (i === player.curSeg && !force) return;
  player.curSeg = i; paint();
  if (i >= 0 && (!au.paused || force) && Date.now() - player.userScroll > 4000) scrollToMark("mark.cur");
}
function scrollToMark(q) {
  const m = hl.querySelector(q); if (!m) return;
  const top = m.offsetTop, h = tx.clientHeight;
  if (top < tx.scrollTop + 40 || top > tx.scrollTop + h - 90) tx.scrollTo({ top: Math.max(0, top - h * 0.33), behavior: "smooth" });
}
for (const ev of ["wheel", "keydown", "mousedown"]) tx.addEventListener(ev, () => { player.userScroll = Date.now(); });
tx.addEventListener("scroll", () => { hl.scrollTop = tx.scrollTop; });
tx.addEventListener("click", () => {   // click a word: the playhead jumps there (Premiere text panel style)
  if (!player.id || player.failed || !segMap.length || tx.selectionStart !== tx.selectionEnd) return;
  const pos = tx.selectionStart; let best = -1;
  for (let n = 0; n < segMap.length && segMap[n].s <= pos; n++) best = n;
  if (best >= 0) { au.currentTime = segMap[best].a; player.curSeg = -1; syncSeg(false); paintTime(); }
});

/* ---- highlights painted behind the textarea: current segment + find matches ---- */
function paint() {
  if ($("#txwrap").hidden) return;
  const t = tx.value, ranges = [];
  const c = segMap[player.curSeg];
  if (c && player.id) ranges.push([c.s, c.e, "cur"]);
  find.hits.forEach((p, n) => ranges.push([p, p + find.len, n === find.i ? "f on" : "f"]));
  if (!ranges.length) { hl.textContent = t + "\n"; hl.scrollTop = tx.scrollTop; return; }
  const pts = new Set([0, t.length]);
  for (const [s, e] of ranges) { pts.add(s); pts.add(e); }
  const xs = [...pts].sort((x, y) => x - y); let out = "";
  for (let k = 0; k + 1 < xs.length; k++) {
    const s = xs[k], e = xs[k + 1], seg = esc(t.slice(s, e));
    const cls = ranges.filter(r => r[0] <= s && r[1] >= e).map(r => r[2]).join(" ");
    out += cls ? `<mark class="${cls}">${seg}</mark>` : seg;
  }
  hl.innerHTML = out + "\n"; hl.scrollTop = tx.scrollTop;
}

/* ---- find & replace ---- */
const find = { hits: [], i: -1, len: 0 };
function openFind(replace) {
  const j = selJob(); if (!j || !j.text) return;
  if (j.ai_state && (tabOf[sel] || "ai") === "ai") { tabOf[sel] = "text"; lastRendered = ""; renderText(); }
  $("#find").hidden = false;
  const editable = j.state === "done";
  for (const id of ["#fr", "#fRep", "#fRepAll"]) $(id).hidden = !editable;
  const s = tx.value.slice(tx.selectionStart, tx.selectionEnd);
  if (s && s.length < 60 && !s.includes("\n")) $("#fq").value = s;
  (replace && editable && $("#fq").value ? $("#fr") : $("#fq")).focus();
  $("#fq").select(); refind(); paint();
}
function closeFind(silent) {
  if ($("#find").hidden) return;
  $("#find").hidden = true; const h = find.hits[find.i];
  find.hits = []; find.i = -1;
  if (silent) return;
  paint();
  if (h != null) { tx.focus(); tx.setSelectionRange(h, h + find.len); }
}
function refind() {
  const q = $("#find").hidden ? "" : $("#fq").value;
  const prev = find.hits[find.i];
  find.hits = []; find.len = q.length;
  if (q) { const t = tx.value.toLowerCase(), ql = q.toLowerCase(); for (let p = t.indexOf(ql); p >= 0 && find.hits.length < 5000; p = t.indexOf(ql, p + ql.length)) find.hits.push(p); }
  find.i = find.hits.length ? Math.max(0, find.hits.findIndex(p => p >= (prev ?? 0))) : -1;
  const c = $("#fCount");
  c.textContent = !q ? "" : find.hits.length ? (find.i + 1) + " מתוך " + find.hits.length : "לא נמצא";
  c.className = q && !find.hits.length ? "nf" : "";
}
function step(d) {
  if (!find.hits.length) return;
  find.i = (find.i + d + find.hits.length) % find.hits.length;
  $("#fCount").textContent = (find.i + 1) + " מתוך " + find.hits.length;
  player.userScroll = Date.now(); paint(); scrollToMark("mark.f.on");
}
$("#fq").oninput = () => { find.i = 0; find.hits = []; refind(); paint(); scrollToMark("mark.f.on"); };
$("#fq").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); } };
$("#fr").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); $("#fRep").click(); } };
$("#fNext").onclick = () => step(1);
$("#fPrev").onclick = () => step(-1);
$("#fClose").onclick = () => closeFind();
$("#findBtn").onclick = () => openFind(false);
$("#fRep").onclick = () => {
  const p = find.hits[find.i]; if (p == null) return;
  tx.value = tx.value.slice(0, p) + $("#fr").value + tx.value.slice(p + find.len);
  textChanged(); scrollToMark("mark.f.on");
};
$("#fRepAll").onclick = () => {
  const q = $("#fq").value, n = find.hits.length; if (!q || !n) return;
  let t = tx.value; for (let k = n - 1; k >= 0; k--) t = t.slice(0, find.hits[k]) + $("#fr").value + t.slice(find.hits[k] + q.length);
  tx.value = t; textChanged();
  toast(n === 1 ? "הוחלף מופע אחד" : "הוחלפו " + n + " מופעים");
};

/* ---- keyboard: Premiere-like transport, plus app shortcuts ---- */
document.addEventListener("keydown", e => {
  const open = document.querySelector(".overlay.on");
  if (open) { if (e.key === "Escape") { open.classList.remove("on"); open._cancel && open._cancel(); } return; }
  const ctrl = e.ctrlKey || e.metaKey, el = document.activeElement;
  const typing = el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || el.isContentEditable) && !el.readOnly;
  if (ctrl && e.code === "KeyF") { e.preventDefault(); return openFind(false); }
  if (ctrl && e.code === "KeyH") { e.preventDefault(); return openFind(true); }
  if (ctrl && e.code === "KeyS") { e.preventDefault(); return $("#pSave").disabled || $("#pSave").click(); }
  if (ctrl && e.code === "Space") { e.preventDefault(); return toggle(); }
  if (e.key === "Escape" && !$("#find").hidden) { e.preventDefault(); return closeFind(); }
  if (e.key === "F2") { e.preventDefault(); return rename(); }
  if (typing || ctrl || e.altKey) return;
  const k = e.code;
  if (k === "Space" && el && el.tagName === "BUTTON") return;
  if (k === "Space") { e.preventDefault(); toggle(); }
  else if (k === "KeyK") { au.pause(); au.playbackRate = player.base; }
  else if (k === "KeyJ") nudge(-5);
  else if (k === "KeyL") {
    if (au.paused) { au.playbackRate = player.base; toggle(); }
    else au.playbackRate = Math.min(2, au.playbackRate < 1.5 ? 1.5 : 2);
  }
  else if (k === "ArrowLeft" && !(el && el.closest && el.closest("#list"))) { e.preventDefault(); nudge(e.shiftKey ? -1 : -5); }
  else if (k === "ArrowRight" && !(el && el.closest && el.closest("#list"))) { e.preventDefault(); nudge(e.shiftKey ? 1 : 5); }
});

/* ---- dialogs ---- */
function ask(title, body, buttons, input) {
  $("#askT").textContent = title; $("#askB").textContent = body || "";
  $("#askB").hidden = !body;
  const inp = $("#askIn"); inp.hidden = input == null; if (input != null) inp.value = input;
  const box = $("#askBtns"); box.innerHTML = "";
  for (const b of buttons) {
    const el = document.createElement("button"); el.textContent = b.label; if (b.cls) el.className = b.cls;
    el.onclick = () => { $("#askDlg").classList.remove("on"); b.fn && b.fn(inp.value.trim()); };
    box.appendChild(el);
  }
  $("#askDlg")._cancel = (buttons.find(b => !b.cls && !b.fn) || {}).fn;
  $("#askDlg").classList.add("on");
  setTimeout(() => { if (input != null) { inp.focus(); inp.select(); } else box.firstChild && box.firstChild.focus(); }, 30);
}
function promptBox(title, value) {
  return new Promise(res => {
    ask(title, "", [{ label: "שמירה", cls: "primary", fn: v => res(v) }, { label: "ביטול", fn: () => res(null) }], value);
    $("#askDlg")._cancel = () => res(null);
  });
}
$("#askIn").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); $("#askBtns").firstChild.click(); } };

/* ---- project: save / new / history ---- */
const anyBusy = () => jobs.some(j => j.state === "queued" || j.state === "running" || j.ai_state === "queued" || j.ai_state === "running") || Object.keys(uploads).length;
const unsaved = () => project.dirty && jobs.length > 0;
function renderProject() {
  $("#pName").textContent = project.name || "פרויקט חדש";
  $("#pName").title = project.name || "";
  $("#pState").classList.toggle("dirty", unsaved());
  $("#pStateT").textContent = !jobs.length && !project.id ? "גררו קבצים כדי להתחיל" : unsaved() ? (project.id ? "יש שינויים שלא נשמרו" : "לא נשמר עדיין") : "נשמר בהיסטוריה";
  $("#pSave").disabled = !jobs.length;
  $("#pSave").className = unsaved() ? "primary" : "";
  $("#exportAll").disabled = !jobs.some(j => j.state === "done");
}
function openSave(then) {
  const first = jobs[0] ? stem(jobs[0]) : "";
  const ai = jobs.find(j => j.ai && j.ai.title);
  $("#saveName").value = project.name || (ai ? ai.ai.title : first) || "";
  $("#saveDlg").classList.add("on");
  setTimeout(() => { $("#saveName").focus(); $("#saveName").select(); }, 30);
  $("#saveOk").onclick = async () => {
    const ok = await saveProject($("#saveName").value.trim());
    $("#saveDlg").classList.remove("on");
    if (ok) { toast("נשמר בהיסטוריה"); then && then(); }
  };
}
$("#saveName").onkeydown = e => { if (e.key === "Enter") $("#saveOk").click(); };
$("#saveCancel").onclick = () => $("#saveDlg").classList.remove("on");
// Saves the project; on failure says why and returns false, so callers never go on to wipe the work.
async function saveProject(name) {
  await flushEdit();
  let r;
  try { r = await fetch("/api/project/save" + (name ? "?name=" + encodeURIComponent(name) : ""), { method: "POST" }); }
  catch (e) { r = null; }
  await poll();
  if (r && r.ok) return true;
  let msg = "לא הצלחנו לשמור את הפרויקט.";
  try { msg = (await r.json()).error || msg; } catch (e) { /* keep default */ }
  ask("השמירה נכשלה", msg + " העבודה לא נמחקה ונשמרת זמנית גם בגיבוי אוטומטי.", [{ label: "הבנתי" }]);
  return false;
}
$("#pSave").onclick = async () => { if (!project.id) return openSave(); if (await saveProject()) toast("נשמר"); };
function guard(action) {  // runs action after making sure nothing unsaved is lost
  if (anyBusy()) return toast("יש עבודה שרצה עכשיו. חכו לסיום.");
  if (!unsaved()) return action();
  ask("לשמור את הפרויקט הנוכחי?", "יש בו עבודה שלא נשמרה בהיסטוריה.", [
    { label: "שמירה", cls: "primary", fn: async () => { if (!project.id) return openSave(action); if (await saveProject()) action(); } },
    { label: "בלי לשמור", cls: "x", fn: action },
    { label: "ביטול" }]);
}
async function switchTo(url) {
  const r = await fetch(url, { method: "POST" });
  if (r.status === 409) return toast("יש עבודה שרצה עכשיו. חכו לסיום.");
  for (const k in edits) delete edits[k];
  for (const k in doneTasks) delete doneTasks[k];
  for (const k in segCache) delete segCache[k];
  closeFind(true); sel = null; lastRendered = ""; await poll();
}
$("#pNew").onclick = () => guard(() => switchTo("/api/project/new"));
let hist = [];
function fmtDate(t) { const d = new Date(t * 1000); return d.toLocaleDateString("he-IL") + " " + d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" }); }
function renderHist() {
  const q = $("#histQ").value.trim();
  const xs = hist.filter(p => !q || p.name.includes(q) || p.names.some(n => (n || "").includes(q)));
  $("#histList").innerHTML = xs.length ? xs.map(p => `<div class="hp${p.id === project.id ? " cur" : ""}" data-p="${p.id}" tabindex="0" role="button">
      <div class="info"><div class="t">${esc(p.name)}</div>
      <div class="s">${fmtDate(p.saved)} · ${p.count === 1 ? "הקלטה אחת" : p.count + " הקלטות"} · ${fmtTime(p.duration)}${p.ai ? " · AI" : ""} · ${esc(p.names.join(", "))}</div></div>
      <button class="del" data-del="${p.id}" title="מחיקה">מחיקה</button></div>`).join("")
    : `<div class="hempty">${hist.length ? "לא נמצא" : "עוד אין פרויקטים שמורים. לחצו 'שמירה' כדי להוסיף."}</div>`;
}
$("#pHist").onclick = async () => {
  hist = (await (await fetch("/api/history")).json()).projects;
  $("#histQ").value = ""; renderHist(); $("#histDlg").classList.add("on");
  setTimeout(() => $("#histQ").focus(), 30);
};
$("#histQ").oninput = renderHist;
$("#histQ").onkeydown = e => { if (e.key === "Enter") { const f = $("#histList [data-p]"); f && f.click(); } };
$("#histClose").onclick = () => $("#histDlg").classList.remove("on");
$("#histList").onkeydown = e => { if (e.key === "Enter" && e.target.dataset.p) e.target.click(); };
$("#histList").onclick = e => {
  const del = e.target.closest("[data-del]");
  if (del) {
    e.stopPropagation();
    const p = hist.find(x => x.id === del.dataset.del);
    return ask("למחוק את \"" + p.name + "\"?", "הפרויקט יימחק מההיסטוריה. קבצי ה-TXT וה-Word שבתיקיית התוצאות נשארים.", [
      { label: "מחיקה", cls: "primary", fn: async () => { await fetch("/api/project/delete?id=" + p.id, { method: "POST" }); hist = hist.filter(x => x.id !== p.id); renderHist(); poll(); } },
      { label: "ביטול" }]);
  }
  const row = e.target.closest("[data-p]"); if (!row) return;
  $("#histDlg").classList.remove("on");
  if (row.dataset.p === project.id && !project.dirty) return;
  guard(() => switchTo("/api/project/open?id=" + row.dataset.p));
};
for (const o of document.querySelectorAll(".overlay")) o.addEventListener("mousedown", e => { if (e.target === o) { o.classList.remove("on"); o._cancel && o._cancel(); } });
for (const b of document.querySelectorAll("[data-close]")) b.onclick = () => b.closest(".overlay").classList.remove("on");
$("#keysBtn").onclick = () => $("#keysDlg").classList.add("on");
window.addEventListener("beforeunload", e => { if (unsaved() || rec.mr) { e.preventDefault(); e.returnValue = ""; } });

/* ---- recorder: microphone -> webm/opus -> same upload path as a dropped file ---- */
const rec = { mr: null, chunks: [], stream: null, t0: 0, acc: 0, timer: null, ctx: null, raf: 0 };
function recUi(on) { $("#recBtn").hidden = on; $("#recLive").hidden = !on; $("#recLive").classList.remove("paused"); $("#recPause").textContent = "השהיה"; }
function recElapsed() { return rec.acc + (rec.mr && rec.mr.state === "recording" ? Date.now() - rec.t0 : 0); }
function recStopAll() {
  clearInterval(rec.timer); cancelAnimationFrame(rec.raf);
  if (rec.stream) rec.stream.getTracks().forEach(t => t.stop());
  if (rec.ctx) rec.ctx.close();
  rec.mr = rec.stream = rec.ctx = null; recUi(false);
}
$("#recBtn").onclick = async () => {
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true } });
  } catch (e) {
    return ask("אין גישה למיקרופון", e.name === "NotFoundError" ? "לא נמצא מיקרופון מחובר למחשב." : "צריך לאשר גישה למיקרופון (בחלון שקפץ, או בסמל המנעול/המצלמה בשורת הכתובת).", [{ label: "הבנתי", cls: "primary" }]);
  }
  const type = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find(t => MediaRecorder.isTypeSupported(t)) || "";
  rec.mr = new MediaRecorder(rec.stream, type ? { mimeType: type, audioBitsPerSecond: 64000 } : undefined);
  rec.chunks = []; rec.acc = 0; rec.t0 = Date.now();
  rec.mr.ondataavailable = e => { if (e.data.size) rec.chunks.push(e.data); };
  rec.mr.start(1000);
  recUi(true);
  rec.timer = setInterval(() => { $("#recTime").textContent = fmtTime(recElapsed() / 1000); }, 250);
  rec.ctx = new AudioContext();
  const an = rec.ctx.createAnalyser(); an.fftSize = 512;
  rec.ctx.createMediaStreamSource(rec.stream).connect(an);
  const buf = new Uint8Array(an.fftSize);
  const tick = () => {
    an.getByteTimeDomainData(buf);
    let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
    $("#recLevel").style.width = Math.min(100, peak / 128 * 160) + "%";
    rec.raf = requestAnimationFrame(tick);
  };
  tick();
};
$("#recPause").onclick = () => {
  if (!rec.mr) return;
  if (rec.mr.state === "recording") { rec.mr.pause(); rec.acc += Date.now() - rec.t0; $("#recPause").textContent = "המשך"; $("#recLive").classList.add("paused"); }
  else { rec.mr.resume(); rec.t0 = Date.now(); $("#recPause").textContent = "השהיה"; $("#recLive").classList.remove("paused"); }
};
$("#recCancel").onclick = () => {
  if (!rec.mr) return;
  ask("לבטל את ההקלטה?", "ההקלטה תימחק ולא תתומלל.", [
    { label: "מחיקה", cls: "primary", fn: () => { rec.mr.onstop = null; rec.mr.stop(); recStopAll(); } },
    { label: "המשך הקלטה" }]);
};
$("#recStop").onclick = () => {
  if (!rec.mr) return;
  const mr = rec.mr;
  mr.onstop = () => {
    const blob = new Blob(rec.chunks, { type: mr.mimeType || "audio/webm" });
    recStopAll();
    const d = new Date(), p = n => String(n).padStart(2, "0");
    const ext = (mr.mimeType || "").includes("ogg") ? "ogg" : "webm";
    const name = `הקלטה ${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}-${p(d.getMinutes())}.${ext}`;
    if (blob.size < 2000) return toast("ההקלטה ריקה");
    upload(new File([blob], name, { type: blob.type }), true);
  };
  mr.stop();
};

/* ---- copy / save / AI ---- */
async function copyText(txt) {
  try { await navigator.clipboard.writeText(txt); }
  catch (e) { const t = document.createElement("textarea"); t.value = txt; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); }
  toast("הועתק");
}
function downloadBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
$("#copy").onclick = () => { const j = selJob(); if (j) copyText(currentText(j)); };
async function save(fmt) {
  const j = selJob(); if (!j) return;
  const r = await fetch("/api/save?fmt=" + fmt + "&name=" + encodeURIComponent(j.name), {
    method: "POST", body: new Blob([currentText(j)], { type: "text/plain;charset=utf-8" }) });
  if (!r.ok) return toast("השמירה נכשלה");
  downloadBlob(await r.blob(), stem(j) + "." + fmt);
}
$("#dlTxt").onclick = () => save("txt");
$("#dlDocx").onclick = () => save("docx");
async function runAi() {
  const j = selJob(); if (!j) return;
  tabOf[j.id] = "ai";
  await fetch("/api/ai?id=" + j.id, { method: "POST",
    body: new Blob([currentText(j) === j.text ? "" : currentText(j)], { type: "text/plain;charset=utf-8" }) });
  lastRendered = ""; poll();
}
$("#aiBtn").onclick = runAi;
$("#aiAgain").onclick = runAi;
async function aiFile(fmt) {
  const j = selJob(); if (!j) return;
  const r = await fetch("/api/ai-file?fmt=" + fmt + "&id=" + j.id);
  if (!r.ok) return toast("השמירה נכשלה");
  downloadBlob(await r.blob(), stem(j) + " - סיכום AI." + fmt);
}
$("#aiDocx").onclick = () => aiFile("docx");
$("#aiTxt").onclick = () => aiFile("txt");
$("#aiCopy").onclick = async () => {
  const j = selJob(); if (!j) return;
  const r = await fetch("/api/ai-file?fmt=txt&id=" + j.id);
  if (r.ok) copyText((await r.text()).replace(/^﻿/, ""));
};
$("#exportAll").onclick = async () => {
  const r = await fetch("/api/project/export");
  if (!r.ok) return toast("אין עדיין תמלול לייצוא");
  downloadBlob(await r.blob(), (project.name || "פרויקט") + ".docx");
  toast("הקובץ נשמר בתיקיית ההורדות");
};
$("#openFolder").onclick = () => fetch("/api/open-folder");

/* ---- software updates (kits in the updates folder, see updates.py) ---- */
let upd = null, updating = null, updSeen = null, lastSeen = false;
function renderUpd(d) {
  upd = d.update || null;
  $("#verSub").textContent = d.version ? "גרסה " + d.version : "";
  if (updating) {   // the installer has the app closed and restarted it: reload into the new version
    if (d.version && d.version !== updating.from) location.reload();
    return;
  }
  if (!upd) return;
  const a = upd.available, b = $("#updBtn");
  b.classList.toggle("has", !!a);
  b.textContent = a ? "עדכון זמין · " + a.version : "עדכונים";
  if (a && updSeen !== a.version) { updSeen = a.version; toast("גרסה " + a.version + " מוכנה להתקנה · עדכונים"); }
  if (upd.last && !lastSeen) {
    lastSeen = true;
    const l = upd.last;
    if (l.ok && l.result === "ok") toast("עודכן לגרסה " + l.to);
    else if (l.ok && l.result === "restored") toast("הוחזרה גרסה " + l.to);
    else if (!l.ok) ask("העדכון לא הותקן", (l.error || "") + " · שום דבר לא השתנה.", [{ label: "סגירה" }]);
  }
  if ($("#updDlg").classList.contains("on")) paintUpd();
}
function paintUpd(msg, err) {
  if (!upd) return;
  $("#updVer").textContent = upd.version;
  if (document.activeElement !== $("#updDir")) $("#updDir").value = upd.folder || "";
  const m = $("#updMsg");
  const a = upd.available;
  m.className = "upd-msg" + (err || upd.error ? " err" : "");
  m.textContent = msg || upd.error || (!upd.folder ? "עוד לא נבחרה תיקיית עדכונים." : a ? "" : "אין עדכון חדש בתיקייה. הגרסה המותקנת היא האחרונה.");
  $("#updNew").hidden = !a;
  if (a) {
    $("#updNewV").textContent = a.version;
    $("#updNotes").innerHTML = (a.notes || []).map(n => `<li>${esc(n)}</li>`).join("");
  }
}
$("#updBtn").onclick = async () => {
  $("#updDlg").classList.add("on"); paintUpd("מחפש…");
  try { upd = await (await fetch("/api/update/check", { method: "POST" })).json(); paintUpd(); } catch (e) { paintUpd(); }
};
$("#updSave").onclick = async () => {
  paintUpd("מחפש…");
  const r = await fetch("/api/update/folder", { method: "POST", body: $("#updDir").value.trim() });
  const d = await r.json();
  if (!r.ok) return paintUpd(d.error || "שגיאה", true);
  upd = d; $("#updDir").blur(); paintUpd();
};
$("#updDir").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); $("#updSave").click(); } };
$("#updGo").onclick = async () => {   // open work is autosaved and comes back after the restart
  if (anyBusy()) return toast("אפשר לעדכן כשאין תמלול או סידור AI באמצע");
  const from = upd.version;
  const r = await fetch("/api/update/apply", { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    return paintUpd(r.status === 409 ? "יש עבודה באמצע. אפשר לעדכן כשהיא תסתיים." : (d.error || "העדכון לא הופעל"), true);
  }
  $("#updDlg").classList.remove("on");
  updating = { from, t0: Date.now() };
  $("#updating").style.display = "flex";
  setInterval(() => {
    if (Date.now() - updating.t0 > 240000)
      $("#updatingT").textContent = "זה לוקח יותר מהרגיל. אם החלון לא חוזר: להפעיל את HEBREW-WHISPER.bat. פרטים: _updates\\update-log.txt";
  }, 2000);
};

poll(); setInterval(poll, 1000);
