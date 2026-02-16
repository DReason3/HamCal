/* HamCal docs/app.js
   - Loads docs/all.json
   - Filters + List/Month view
   - Persistent Selected Events (localStorage)
   - Selected list has its own search
   - Add-all-filtered with safety cap
   - Export modes (selected visible/all, filtered, union)
   - Shareable static selection links via URL hash (#sel=...)
   - Unique download filenames (hash + date)
   - DETAILS under Add/Remove:
       - uses evt.url/link/etc if present
       - else extracts href from HTML in evt.description (e.g. <a href="...">Info</a>)
*/

(() => {
  "use strict";

  // ---------- DOM ----------
  const el = (id) => document.getElementById(id);

  const viewModeEl = el("viewMode");
  const qEl = el("q");
  const modeEl = el("mode");
  const sourceEl = el("source");
  const whenEl = el("when");
  const tzEl = el("tz");
  const resetFiltersEl = el("resetFilters");

  const addAllFilteredEl = el("addAllFiltered");

  const listViewEl = el("listView");
  const monthViewEl = el("monthView");
  const listContainerEl = el("listContainer");
  const monthGridEl = el("monthGrid");
  const monthTitleEl = el("monthTitle");
  const monthPrevEl = el("monthPrev");
  const monthNextEl = el("monthNext");

  const resultCountEl = el("resultCount");
  const selectedCountEl = el("selectedCount");
  const selectedSearchEl = el("selectedSearch");
  const selectedContainerEl = el("selectedContainer");

  const exportModeEl = el("exportMode");
  const downloadCustomIcsEl = el("downloadCustomIcs");
  const copyShareLinkEl = el("copyShareLink");
  const clearSelectedEl = el("clearSelected");

  // ---------- Storage ----------
  const LS_KEYS = {
    VIEW: "hamcal.viewMode",
    FILTERS: "hamcal.filters",
    SELECTED: "hamcal.selected.uids",
    MONTH_CURSOR: "hamcal.monthCursorISO",
    SELECTED_SEARCH: "hamcal.selected.search",
    EXPORT_MODE: "hamcal.export.mode",
  };

  // ---------- Config ----------
  const MAX_ADD_ALL = 200;

  // ---------- Data ----------
  let ALL = [];
  let FILTERED = [];
  let monthCursor = startOfMonth(new Date());
  let selectedUIDs = new Set();

  // ---------- Helpers ----------
  function safeString(x) {
    if (x === null || x === undefined) return "";
    return String(x);
  }

  function escapeHTML(str) {
    return safeString(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function getUID(evt) {
    return safeString(evt.uid || evt.UID || evt.id || evt.guid || evt._uid || evt.key);
  }

  function getTitle(evt) {
    return safeString(evt.title || evt.summary || evt.name || evt.event || evt.contest || "Untitled");
  }

  function getMode(evt) {
    return safeString(evt.mode || evt.category || evt.type || "").toLowerCase();
  }

  function getSource(evt) {
    return safeString(evt.source || evt.src || evt.origin || "").toLowerCase();
  }

  function getDescription(evt) {
    return safeString(evt.description || evt.desc || evt.details || "");
  }

  // Extract first http(s) URL from HTML in description like: <a href="http://...">Info</a>
  function extractHrefFromHtml(html) {
    const s = safeString(html);
    // href='...' or href="..."
    const m = s.match(/href\s*=\s*["'](https?:\/\/[^"']+)["']/i);
    if (m && m[1]) return m[1].trim();

    // fallback: any http(s) in text
    const m2 = s.match(/https?:\/\/[^\s"'<>)\]]+/i);
    if (m2 && m2[0]) return m2[0].trim();

    return "";
  }

  // Robust URL detection:
  // 1) explicit url/link fields
  // 2) else href inside HTML description
  function getURL(evt) {
    const candidates = [
      evt.url,
      evt.link,
      evt.href,
      evt.website,
      evt.web,
      evt.page,
      evt.details_url,
      evt.detail_url,
      evt.info_url,
      evt.more_info_url,
      evt.event_url,
      evt.eventUrl,
      evt.contest_url,
      evt.contestUrl,
      evt.registration_url,
      evt.registrationUrl,
    ];

    for (const c of candidates) {
      const u = safeString(c).trim();
      if (u && (u.startsWith("http://") || u.startsWith("https://"))) return u;
    }

    // WA7BNM style: description contains an <a href="...">
    const fromDesc = extractHrefFromHtml(getDescription(evt));
    if (fromDesc && (fromDesc.startsWith("http://") || fromDesc.startsWith("https://"))) return fromDesc;

    return "";
  }

  function getSponsor(evt) {
    return safeString(evt.sponsor || evt.organizer || evt.host || evt.by || "");
  }

  function getStartISO(evt) {
    return safeString(evt.start || evt.dtstart || evt.begin || evt.start_utc || evt.startISO || evt.start_iso || "");
  }

  function getEndISO(evt) {
    return safeString(evt.end || evt.dtend || evt.finish || evt.end_utc || evt.endISO || evt.end_iso || "");
  }

  function parseDateMaybe(isoLike) {
    if (!isoLike) return null;
    const d = new Date(isoLike);
    return isNaN(d.getTime()) ? null : d;
  }

  function normalizeModeToFilter(m) {
    const x = safeString(m).toLowerCase();
    if (!x) return "";
    if (x.includes("cw")) return "cw";
    if (x.includes("phone") || x.includes("ssb") || x.includes("voice")) return "phone";
    if (x.includes("dig") || x.includes("rtty") || x.includes("ft8") || x.includes("psk")) return "digital";
    return x;
  }

  function formatDateRange(evt, tzMode) {
    const s = parseDateMaybe(getStartISO(evt));
    const e = parseDateMaybe(getEndISO(evt));
    if (!s && !e) return "Date TBD";

    const opts =
      tzMode === "utc"
        ? { timeZone: "UTC", year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }
        : { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" };

    const fmt = new Intl.DateTimeFormat(undefined, opts);
    if (s && e) return `${fmt.format(s)} \u2192 ${fmt.format(e)}`;
    if (s) return `${fmt.format(s)} \u2192 ?`;
    return `? \u2192 ${fmt.format(e)}`;
  }

  function isUpcoming(evt) {
    const now = new Date();
    const s = parseDateMaybe(getStartISO(evt));
    const e = parseDateMaybe(getEndISO(evt));
    if (e) return e.getTime() >= now.getTime();
    if (s) return s.getTime() >= now.getTime();
    return true;
  }

  function isPast(evt) {
    const now = new Date();
    const e = parseDateMaybe(getEndISO(evt));
    const s = parseDateMaybe(getStartISO(evt));
    if (e) return e.getTime() < now.getTime();
    if (s) return s.getTime() < now.getTime();
    return false;
  }

  function containsQuery(evt, q) {
    if (!q) return true;
    const needle = q.toLowerCase().trim();
    if (!needle) return true;

    const fields = [
      getTitle(evt),
      getSponsor(evt),
      getSource(evt),
      getMode(evt),
      getUID(evt),
      getURL(evt),
      getDescription(evt),
    ].map((x) => safeString(x).toLowerCase());

    return fields.some((f) => f.includes(needle));
  }

  // ---------- LocalStorage ----------
  function loadState() {
    const view = localStorage.getItem(LS_KEYS.VIEW);
    if (view === "list" || view === "month") viewModeEl.value = view;

    try {
      const f = JSON.parse(localStorage.getItem(LS_KEYS.FILTERS) || "{}");
      if (typeof f.q === "string") qEl.value = f.q;
      if (typeof f.mode === "string") modeEl.value = f.mode;
      if (typeof f.source === "string") sourceEl.value = f.source;
      if (typeof f.when === "string") whenEl.value = f.when;
      if (typeof f.tz === "string") tzEl.value = f.tz;
    } catch {}

    try {
      const arr = JSON.parse(localStorage.getItem(LS_KEYS.SELECTED) || "[]");
      if (Array.isArray(arr)) selectedUIDs = new Set(arr.filter((x) => typeof x === "string" && x.length));
    } catch {}

    const mc = localStorage.getItem(LS_KEYS.MONTH_CURSOR);
    const d = mc ? new Date(mc) : null;
    if (d && !isNaN(d.getTime())) monthCursor = startOfMonth(d);

    const ss = localStorage.getItem(LS_KEYS.SELECTED_SEARCH);
    if (typeof ss === "string") selectedSearchEl.value = ss;

    const em = localStorage.getItem(LS_KEYS.EXPORT_MODE);
    if (em && exportModeEl) exportModeEl.value = em;
  }

  function saveView() {
    localStorage.setItem(LS_KEYS.VIEW, viewModeEl.value);
  }
  function saveFilters() {
    const f = {
      q: qEl.value || "",
      mode: modeEl.value || "",
      source: sourceEl.value || "",
      when: whenEl.value || "all",
      tz: tzEl.value || "local",
    };
    localStorage.setItem(LS_KEYS.FILTERS, JSON.stringify(f));
  }
  function saveSelected() {
    localStorage.setItem(LS_KEYS.SELECTED, JSON.stringify(Array.from(selectedUIDs)));
  }
  function saveMonthCursor() {
    localStorage.setItem(LS_KEYS.MONTH_CURSOR, monthCursor.toISOString());
  }
  function saveSelectedSearch() {
    localStorage.setItem(LS_KEYS.SELECTED_SEARCH, selectedSearchEl.value || "");
  }
  function saveExportMode() {
    localStorage.setItem(LS_KEYS.EXPORT_MODE, exportModeEl.value || "selected_visible");
  }

  // ---------- Filtering ----------
  function applyFilters() {
    const q = (qEl.value || "").trim();
    const modeFilter = (modeEl.value || "").toLowerCase();
    const sourceFilter = (sourceEl.value || "").toLowerCase();
    const whenFilter = (whenEl.value || "all").toLowerCase();

    FILTERED = ALL.filter((evt) => {
      if (!containsQuery(evt, q)) return false;

      if (modeFilter) {
        const m = normalizeModeToFilter(getMode(evt));
        if (m !== modeFilter) return false;
      }

      if (sourceFilter) {
        const s = getSource(evt);
        if (!s.includes(sourceFilter)) return false;
      }

      if (whenFilter === "upcoming" && !isUpcoming(evt)) return false;
      if (whenFilter === "past" && !isPast(evt)) return false;

      return true;
    });

    FILTERED.sort((a, b) => {
      const as = parseDateMaybe(getStartISO(a));
      const bs = parseDateMaybe(getStartISO(b));
      const at = as ? as.getTime() : Number.MAX_SAFE_INTEGER;
      const bt = bs ? bs.getTime() : Number.MAX_SAFE_INTEGER;
      if (at !== bt) return at - bt;
      return getTitle(a).localeCompare(getTitle(b));
    });

    resultCountEl.textContent = String(FILTERED.length);
    updateAddAllFilteredButton();
  }

  function updateAddAllFilteredButton() {
    if (!addAllFilteredEl) return;
    const n = FILTERED.length;
    if (n <= 0) {
      addAllFilteredEl.textContent = "Add all filtered";
      addAllFilteredEl.disabled = true;
      return;
    }
    addAllFilteredEl.disabled = false;
    addAllFilteredEl.textContent = `Add all filtered (${n})`;
  }

  // ---------- Rendering ----------
  function detailsMarkup(url) {
    if (!url) {
      return `<button class="btn secondary" type="button" style="display:block; margin-top:6px; width:100%;" disabled>Details</button>`;
    }
    return `<a class="btn secondary" style="display:block; margin-top:6px; text-align:center; width:100%;" href="${escapeHTML(
      url
    )}" target="_blank" rel="noopener">Details</a>`;
  }

  function render() {
    applyFilters();
    saveFilters();

    const view = viewModeEl.value;
    if (view === "month") {
      listViewEl.classList.add("hidden");
      monthViewEl.classList.remove("hidden");
      renderMonth();
    } else {
      monthViewEl.classList.add("hidden");
      listViewEl.classList.remove("hidden");
      renderList();
    }

    renderSelected();
    saveView();
  }

  function renderList() {
    const tzMode = tzEl.value || "local";
    const items = FILTERED.map((evt) => renderEventCard(evt, tzMode)).join("");
    listContainerEl.innerHTML = items || `<div class="muted small" style="padding:10px;">No results.</div>`;

    listContainerEl.querySelectorAll("[data-add-uid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const uid = btn.getAttribute("data-add-uid");
        if (!uid) return;
        toggleSelected(uid);
      });
    });
  }

  function renderEventCard(evt, tzMode) {
    const uid = getUID(evt);
    const title = escapeHTML(getTitle(evt));
    const mode = normalizeModeToFilter(getMode(evt));
    const source = escapeHTML(getSource(evt) || "unknown");
    const sponsor = escapeHTML(getSponsor(evt));
    const url = getURL(evt);
    const range = escapeHTML(formatDateRange(evt, tzMode));

    const selected = selectedUIDs.has(uid);
    const addLabel = selected ? "Remove" : "Add";

    const pills = [
      mode ? `<span class="pill">Mode: ${escapeHTML(mode)}</span>` : "",
      sponsor ? `<span class="pill">Sponsor: ${sponsor}</span>` : "",
      source ? `<span class="pill">Source: ${source}</span>` : "",
      `<span class="pill">${range}</span>`,
    ].filter(Boolean).join("");

    return `
      <div class="card">
        <div class="card-top">
          <div>
            <div class="card-title">${title}</div>
            <div class="card-sub">${pills}</div>
          </div>
          <div class="actions">
            <button class="btn ${selected ? "danger" : "primary"}" type="button" data-add-uid="${escapeHTML(uid)}">${addLabel}</button>
            ${detailsMarkup(url)}
          </div>
        </div>
      </div>
    `;
  }

  function renderSelected() {
    const ss = (selectedSearchEl.value || "").trim().toLowerCase();
    const tzMode = tzEl.value || "local";

    const selectedEvents = ALL.filter((evt) => selectedUIDs.has(getUID(evt)));

    selectedEvents.sort((a, b) => {
      const as = parseDateMaybe(getStartISO(a));
      const bs = parseDateMaybe(getStartISO(b));
      const at = as ? as.getTime() : Number.MAX_SAFE_INTEGER;
      const bt = bs ? bs.getTime() : Number.MAX_SAFE_INTEGER;
      if (at !== bt) return at - bt;
      return getTitle(a).localeCompare(getTitle(b));
    });

    const filteredSelected = !ss ? selectedEvents : selectedEvents.filter((evt) => eventMatchesSelectedSearch(evt, ss));

    selectedCountEl.textContent = String(selectedUIDs.size);
    saveSelected();
    saveSelectedSearch();
    saveExportMode();

    if (selectedUIDs.size === 0) {
      selectedContainerEl.innerHTML = `<div class="muted small" style="padding:10px;">No selected events yet.</div>`;
      downloadCustomIcsEl.disabled = false;
      clearSelectedEl.disabled = true;
      copyShareLinkEl.disabled = true;
      return;
    }

    clearSelectedEl.disabled = false;
    copyShareLinkEl.disabled = false;

    selectedContainerEl.innerHTML = filteredSelected.map((evt) => {
      const uid = getUID(evt);
      const title = escapeHTML(getTitle(evt));
      const mode = normalizeModeToFilter(getMode(evt));
      const source = escapeHTML(getSource(evt) || "unknown");
      const sponsor = escapeHTML(getSponsor(evt));
      const url = getURL(evt);
      const range = escapeHTML(formatDateRange(evt, tzMode));

      const pills = [
        mode ? `<span class="pill">Mode: ${escapeHTML(mode)}</span>` : "",
        sponsor ? `<span class="pill">Sponsor: ${sponsor}</span>` : "",
        `<span class="pill">Source: ${source}</span>`,
        `<span class="pill">${range}</span>`,
      ].filter(Boolean).join("");

      return `
        <div class="card">
          <div class="card-top">
            <div>
              <div class="card-title">${title}</div>
              <div class="card-sub">${pills}</div>
              <div style="margin-top:6px;">${detailsMarkup(url)}</div>
              <div class="muted small" style="margin-top:6px;">UID: <code>${escapeHTML(uid)}</code></div>
            </div>
            <div class="actions">
              <button class="btn danger" type="button" data-remove-uid="${escapeHTML(uid)}">Remove</button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    selectedContainerEl.querySelectorAll("[data-remove-uid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const uid = btn.getAttribute("data-remove-uid");
        if (!uid) return;
        selectedUIDs.delete(uid);
        renderSelected();
        if (viewModeEl.value === "list") renderList(); else renderMonth();
      });
    });
  }

  function eventMatchesSelectedSearch(evt, ssLower) {
    const hay = [
      getTitle(evt),
      getSponsor(evt),
      getSource(evt),
      getMode(evt),
      getUID(evt),
      getURL(evt),
      getDescription(evt),
    ].map((x) => safeString(x).toLowerCase());
    return hay.some((f) => f.includes(ssLower));
  }

  function toggleSelected(uid) {
    if (selectedUIDs.has(uid)) selectedUIDs.delete(uid);
    else selectedUIDs.add(uid);

    renderSelected();
    if (viewModeEl.value === "list") renderList();
    else renderMonth();
  }

  // ---------- Add-all-filtered ----------
  function addAllFiltered() {
    const uids = FILTERED.map(getUID).filter((u) => !!u);
    const uniqueUids = Array.from(new Set(uids));
    const toAdd = uniqueUids.filter((u) => !selectedUIDs.has(u));

    if (toAdd.length === 0) {
      alert("All filtered events are already selected.");
      return;
    }

    if (toAdd.length > MAX_ADD_ALL) {
      const ok = confirm(
        `You are about to add ${toAdd.length} events.\n\nSafety cap is ${MAX_ADD_ALL}.\n\nOK = add first ${MAX_ADD_ALL}\nCancel = do nothing`
      );
      if (!ok) return;
      toAdd.length = MAX_ADD_ALL;
    }

    for (const u of toAdd) selectedUIDs.add(u);

    renderSelected();
    if (viewModeEl.value === "list") renderList();
    else renderMonth();
  }

  // ---------- Month View ----------
  function startOfMonth(d) {
    const x = new Date(d);
    x.setDate(1);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  function addMonths(d, n) {
    const x = new Date(d);
    x.setMonth(x.getMonth() + n);
    return startOfMonth(x);
  }

  function monthLabel(d) {
    return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "long" }).format(d);
  }

  function dateKeyLocal(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${dd}`;
  }

  function renderMonth() {
    monthTitleEl.textContent = monthLabel(monthCursor);

    const first = startOfMonth(monthCursor);
    const firstDow = first.getDay();
    const gridStart = new Date(first);
    gridStart.setDate(first.getDate() - firstDow);
    gridStart.setHours(0, 0, 0, 0);

    const nextMonth = addMonths(first, 1);
    const lastOfMonth = new Date(nextMonth);
    lastOfMonth.setDate(0);
    lastOfMonth.setHours(0, 0, 0, 0);

    const lastDow = lastOfMonth.getDay();
    const gridEnd = new Date(lastOfMonth);
    gridEnd.setDate(lastOfMonth.getDate() + (6 - lastDow));
    gridEnd.setHours(0, 0, 0, 0);

    const eventsByDay = new Map();
    for (const evt of FILTERED) {
      const s = parseDateMaybe(getStartISO(evt));
      if (!s) continue;
      const k = dateKeyLocal(s);
      if (!eventsByDay.has(k)) eventsByDay.set(k, []);
      eventsByDay.get(k).push(evt);
    }

    const cells = [];
    const cur = new Date(gridStart);
    while (cur.getTime() <= gridEnd.getTime()) {
      const inMonth = cur.getMonth() === first.getMonth();
      const k = dateKeyLocal(cur);
      const dayEvents = eventsByDay.get(k) || [];

      const shown = dayEvents.slice(0, 3);
      const more = dayEvents.length - shown.length;

      const miniHtml = shown.map((evt) => {
        const uid = getUID(evt);
        const title = escapeHTML(getTitle(evt));
        const mode = normalizeModeToFilter(getMode(evt));
        const src = escapeHTML(getSource(evt) || "unknown");
        const url = getURL(evt);

        const selected = selectedUIDs.has(uid);
        const addLabel = selected ? "Remove" : "Add";

        return `
          <div class="minievent">
            <div class="t">${title}</div>
            <div class="m">
              ${mode ? `<span class="pill">${escapeHTML(mode)}</span>` : ""}
              <span class="pill">${src}</span>
            </div>
            <div class="actions" style="margin-top:6px;">
              <button class="btn ${selected ? "danger" : "primary"}" type="button" data-add-uid="${escapeHTML(uid)}">${addLabel}</button>
              ${detailsMarkup(url)}
            </div>
          </div>
        `;
      }).join("");

      const moreHtml = more > 0 ? `<div class="muted small" style="margin-top:6px;">+${more} more\u2026</div>` : "";

      cells.push(`
        <div class="daycell" data-day="${k}" style="${inMonth ? "" : "opacity:0.55;"}">
          <div class="dayhead">
            <div class="daynum">${cur.getDate()}</div>
            <div class="muted small">${inMonth ? "" : "\u2022"}</div>
          </div>
          <div class="dayevents">
            ${miniHtml || `<div class="muted small">\u2014</div>`}
            ${moreHtml}
          </div>
        </div>
      `);

      cur.setDate(cur.getDate() + 1);
    }

    monthGridEl.innerHTML = cells.join("");

    monthGridEl.querySelectorAll("[data-add-uid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const uid = btn.getAttribute("data-add-uid");
        if (!uid) return;
        toggleSelected(uid);
      });
    });

    saveMonthCursor();
  }

  // ---------- Share links ----------
  function base64UrlEncodeUTF8(str) {
    const utf8 = encodeURIComponent(str).replace(/%([0-9A-F]{2})/g, (_, p1) =>
      String.fromCharCode(parseInt(p1, 16))
    );
    return btoa(utf8).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
  }

  function base64UrlDecodeUTF8(b64url) {
    let s = safeString(b64url).replaceAll("-", "+").replaceAll("_", "/");
    while (s.length % 4) s += "=";
    const bin = atob(s);
    const pct = Array.from(bin, (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join("");
    return decodeURIComponent(pct);
  }

  function parseSelectionFromHash() {
    const h = (location.hash || "").replace(/^#/, "");
    if (!h) return null;

    const parts = h.split("&");
    for (const p of parts) {
      const [k, v] = p.split("=");
      if (k === "sel" && v) {
        try {
          const json = base64UrlDecodeUTF8(v);
          const obj = JSON.parse(json);
          if (obj && Array.isArray(obj.uids)) {
            return obj.uids.filter((x) => typeof x === "string" && x.length);
          }
        } catch {
          return null;
        }
      }
    }
    return null;
  }

  function copyShareLink() {
    const uids = Array.from(selectedUIDs);
    if (uids.length === 0) {
      alert("Nothing selected to share.");
      return;
    }

    const payload = { uids };
    const encoded = base64UrlEncodeUTF8(JSON.stringify(payload));
    const url = `${location.origin}${location.pathname}#sel=${encoded}`;

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url)
        .then(() => alert("Share link copied to clipboard."))
        .catch(() => prompt("Copy this share link:", url));
    } else {
      prompt("Copy this share link:", url);
    }
  }

  // ---------- ICS generation ----------
  function pad2(n) { return String(n).padStart(2, "0"); }

  function toICSDateUTC(d) {
    return [
      d.getUTCFullYear(),
      pad2(d.getUTCMonth() + 1),
      pad2(d.getUTCDate()),
      "T",
      pad2(d.getUTCHours()),
      pad2(d.getUTCMinutes()),
      pad2(d.getUTCSeconds()),
      "Z",
    ].join("");
  }

  function icsEscapeText(s) {
    return safeString(s)
      .replaceAll("\\", "\\\\")
      .replaceAll("\n", "\\n")
      .replaceAll(";", "\\;")
      .replaceAll(",", "\\,");
  }

  function foldLine(line) {
    const limit = 75;
    if (line.length <= limit) return line;
    let out = "";
    let i = 0;
    while (i < line.length) {
      const chunk = line.slice(i, i + limit);
      out += (i === 0 ? chunk : "\r\n " + chunk);
      i += limit;
    }
    return out;
  }

  function cryptoRandomUID() {
    const rnd = Math.random().toString(16).slice(2);
    const t = Date.now().toString(16);
    return `hamcal-${t}-${rnd}@local`;
  }

  function listSelectedVisibleEvents() {
    const ss = (selectedSearchEl.value || "").trim().toLowerCase();
    const selectedEvents = ALL.filter((evt) => selectedUIDs.has(getUID(evt)));
    if (!ss) return selectedEvents;
    return selectedEvents.filter((evt) => eventMatchesSelectedSearch(evt, ss));
  }
  function listSelectedAllEvents() { return ALL.filter((evt) => selectedUIDs.has(getUID(evt))); }
  function listFilteredEvents() { return FILTERED.slice(); }
  function listUnionEvents() {
    const byUid = new Map();
    for (const evt of listSelectedAllEvents()) byUid.set(getUID(evt), evt);
    for (const evt of listFilteredEvents()) byUid.set(getUID(evt), evt);
    return Array.from(byUid.values());
  }
  function eventsForExportMode() {
    const mode = exportModeEl.value || "selected_visible";
    if (mode === "selected_all") return listSelectedAllEvents();
    if (mode === "filtered") return listFilteredEvents();
    if (mode === "union") return listUnionEvents();
    return listSelectedVisibleEvents();
  }

  function buildCustomICS(events) {
    const now = new Date();
    const dtstamp = toICSDateUTC(now);

    const sorted = events.slice().sort((a, b) => {
      const as = parseDateMaybe(getStartISO(a));
      const bs = parseDateMaybe(getStartISO(b));
      const at = as ? as.getTime() : Number.MAX_SAFE_INTEGER;
      const bt = bs ? bs.getTime() : Number.MAX_SAFE_INTEGER;
      if (at !== bt) return at - bt;
      return getTitle(a).localeCompare(getTitle(b));
    });

    const lines = [];
    lines.push("BEGIN:VCALENDAR");
    lines.push("VERSION:2.0");
    lines.push("PRODID:-//HamCal//Static Selection//EN");
    lines.push("CALSCALE:GREGORIAN");
    lines.push("METHOD:PUBLISH");
    lines.push("X-WR-CALNAME:HamCal Custom");

    for (const evt of sorted) {
      const uid = getUID(evt) || cryptoRandomUID();
      const title = getTitle(evt);
      const url = getURL(evt);
      const desc = getDescription(evt);
      const source = getSource(evt);
      const sponsor = getSponsor(evt);
      const mode = normalizeModeToFilter(getMode(evt));

      const s = parseDateMaybe(getStartISO(evt));
      const e = parseDateMaybe(getEndISO(evt));
      const s2 = s || now;
      const e2 = e || new Date(s2.getTime() + 2 * 60 * 60 * 1000);

      const descriptionParts = [];
      if (sponsor) descriptionParts.push(`Sponsor: ${sponsor}`);
      if (mode) descriptionParts.push(`Mode: ${mode}`);
      if (source) descriptionParts.push(`Source: ${source}`);
      if (url) descriptionParts.push(`Link: ${url}`);
      if (desc) descriptionParts.push("");
      if (desc) descriptionParts.push(desc);

      const description = descriptionParts.join("\n");

      lines.push("BEGIN:VEVENT");
      lines.push(`UID:${icsEscapeText(uid)}`);
      lines.push(`DTSTAMP:${dtstamp}`);
      lines.push(`DTSTART:${toICSDateUTC(s2)}`);
      lines.push(`DTEND:${toICSDateUTC(e2)}`);
      lines.push(`SUMMARY:${icsEscapeText(title)}`);
      if (description) lines.push(`DESCRIPTION:${icsEscapeText(description)}`);
      if (url) lines.push(`URL:${icsEscapeText(url)}`);
      lines.push("END:VEVENT");
    }

    lines.push("END:VCALENDAR");
    return lines.map(foldLine).join("\r\n") + "\r\n";
  }

  function downloadText(filename, text) {
    const blob = new Blob([text], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function isoDateStampLocal(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${dd}`;
  }

  function fnv1a32(str) {
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = (h * 0x01000193) >>> 0;
    }
    return h >>> 0;
  }

  function makeDownloadFilename(events, mode) {
    const stamp = isoDateStampLocal(new Date());
    const uids = events.map(getUID).join("|");
    const h = fnv1a32(`${mode}|${uids}`).toString(16).padStart(8, "0");
    return `hamcal-${mode}-${stamp}-${h}.ics`;
  }

  // ---------- Bind UI Events ----------
  function bindEvents() {
    viewModeEl.addEventListener("change", () => render());

    [qEl, modeEl, sourceEl, whenEl, tzEl].forEach((x) => {
      x.addEventListener("input", () => render());
      x.addEventListener("change", () => render());
    });

    resetFiltersEl.addEventListener("click", () => {
      qEl.value = "";
      modeEl.value = "";
      sourceEl.value = "";
      whenEl.value = "all";
      tzEl.value = "local";
      saveFilters();
      render();
    });

    selectedSearchEl.addEventListener("input", () => { renderSelected(); });
    exportModeEl.addEventListener("change", () => { saveExportMode(); });

    clearSelectedEl.addEventListener("click", () => {
      selectedUIDs.clear();
      saveSelected();
      render();
    });

    copyShareLinkEl.addEventListener("click", () => { copyShareLink(); });

    downloadCustomIcsEl.addEventListener("click", () => {
      const mode = exportModeEl.value || "selected_visible";
      const events = eventsForExportMode();
      if (events.length === 0) {
        alert("Nothing to export for the selected export mode.");
        return;
      }
      const ics = buildCustomICS(events);
      const filename = makeDownloadFilename(events, mode);
      downloadText(filename, ics);
    });

    addAllFilteredEl.addEventListener("click", () => { addAllFiltered(); });

    monthPrevEl.addEventListener("click", () => { monthCursor = addMonths(monthCursor, -1); render(); });
    monthNextEl.addEventListener("click", () => { monthCursor = addMonths(monthCursor, 1); render(); });
  }

  // ---------- Load ----------
  async function loadAllJSON() {
    const res = await fetch("./all.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`Failed to load all.json (${res.status})`);
    const data = await res.json();
    if (Array.isArray(data)) return data;
    if (data && Array.isArray(data.events)) return data.events;
    if (data && Array.isArray(data.items)) return data.items;
    return [];
  }

  function applySelectionFromHashIfPresent() {
    const uidsFromHash = parseSelectionFromHash();
    if (!uidsFromHash || uidsFromHash.length === 0) return;

    const uidsInData = new Set(ALL.map(getUID));
    const filtered = uidsFromHash.filter((u) => uidsInData.has(u));

    if (filtered.length === 0) {
      alert("Share link selection did not match current dataset (no UIDs found).");
      return;
    }

    selectedUIDs = new Set(filtered);
    saveSelected();
    history.replaceState(null, "", `${location.pathname}${location.search}`);
  }

  async function main() {
    loadState();
    bindEvents();

    try {
      ALL = await loadAllJSON();

      ALL = ALL.map((evt, idx) => {
        const uid = getUID(evt) || `hamcal-auto-${idx}`;
        if (!evt.uid) evt.uid = uid;
        return evt;
      });

      const uidsInData = new Set(ALL.map(getUID));
      selectedUIDs = new Set(Array.from(selectedUIDs).filter((u) => uidsInData.has(u)));

      applySelectionFromHashIfPresent();
      render();
    } catch (err) {
      console.error(err);
      listContainerEl.innerHTML = `<div class="muted small" style="padding:10px;">Error loading events. See console.</div>`;
      resultCountEl.textContent = "0";
      renderSelected();
    }
  }

  main();
})();
