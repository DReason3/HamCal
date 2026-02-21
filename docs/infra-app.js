(async function(){
  const $ = (id)=>document.getElementById(id);

  const qEl = $("q");
  const typeEl = $("type");
  const statusEl = $("status");
  const listEl = $("list");
  const metaEl = $("meta");

  function fmtUtc(isoZ){
    // isoZ expected "...Z"
    try{
      const d = new Date(isoZ);
      return d.toISOString().replace(".000Z","Z");
    }catch{
      return isoZ;
    }
  }

  function durationStr(startZ, endZ){
    try{
      const a = new Date(startZ).getTime();
      const b = new Date(endZ).getTime();
      const mins = Math.max(0, Math.round((b-a)/60000));
      const h = Math.floor(mins/60);
      const m = mins%60;
      if(h<=0) return `${m}m`;
      if(m===0) return `${h}h`;
      return `${h}h ${m}m`;
    }catch{
      return "";
    }
  }

  function statusBadge(status){
    const s = (status||"").toLowerCase();
    if(s==="cancelled") return `<span class="badge bad">cancelled</span>`;
    if(s==="tentative") return `<span class="badge warn">tentative</span>`;
    return `<span class="badge good">scheduled</span>`;
  }

  function safe(v){
    return (v===null || v===undefined || v==="") ? "—" : String(v);
  }

  function joinOrDash(arr){
    if(!arr || !arr.length) return "—";
    return arr.join(", ");
  }

  function relLabel(rel){
    return (rel||"info").toLowerCase();
  }

  function authMark(authority){
    const a = (authority||"unknown").toLowerCase();
    if(a==="originator") return "★";
    if(a==="authority") return "✓";
    if(a==="directory") return "↪";
    return "";
  }

  function linkSort(a,b){
    // Put originator-ish links first visually.
    const order = {originator:0, authority:1, unknown:2, directory:3};
    const aa = order[(a.authority||"unknown").toLowerCase()] ?? 9;
    const bb = order[(b.authority||"unknown").toLowerCase()] ?? 9;
    if(aa!==bb) return aa-bb;
    return relLabel(a.rel).localeCompare(relLabel(b.rel));
  }

  const res = await fetch("./api/infra_events.v1.json", {cache:"no-store"});
  const all = await res.json();

  function filterData(){
    const q = (qEl.value||"").trim().toLowerCase();
    const t = (typeEl.value||"").trim().toLowerCase();
    const s = (statusEl.value||"").trim().toLowerCase();

    return all.filter(ev=>{
      if(t && (ev.type||"").toLowerCase()!==t) return false;
      if(s && (ev.status||"").toLowerCase()!==s) return false;

      if(q){
        const hay = [
          ev.name, ev.exchange, ev.scoring, ev.notes,
          (ev.modes||[]).join(" "),
          (ev.bands||[]).join(" "),
        ].join(" ").toLowerCase();
        if(!hay.includes(q)) return false;
      }

      return true;
    }).sort((a,b)=>{
      return String(a.start_utc).localeCompare(String(b.start_utc)) || String(a.name).localeCompare(String(b.name));
    });
  }

  function render(){
    const data = filterData();
    metaEl.textContent = `${data.length} shown · ${all.length} total in feed`;

    listEl.innerHTML = data.map(ev=>{
      const titleUrl = ev.primary_link || (ev.links && ev.links[0] && ev.links[0].url) || null;
      const title = titleUrl
        ? `<a class="name" href="${titleUrl}" target="_blank" rel="noopener noreferrer">${safe(ev.name)}</a>`
        : `<div class="name">${safe(ev.name)}</div>`;

      const dur = durationStr(ev.start_utc, ev.end_utc);

      const links = (ev.links || []).slice().sort(linkSort).slice(0, 8).map(l=>{
        const mark = authMark(l.authority);
        const label = `${mark} ${relLabel(l.rel)}`.trim();
        return `<a class="linkpill" href="${l.url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      }).join("");

      // Contest Summary block (ND4X-style quick glance)
      return `
        <div class="card">
          <div class="row">
            <div>${title}
              <div class="small">
                <span class="badge">${safe(ev.type)}</span>
                ${statusBadge(ev.status)}
                <span class="badge">UTC ${fmtUtc(ev.start_utc)} → ${fmtUtc(ev.end_utc)}</span>
                <span class="badge">dur ${safe(dur)}</span>
              </div>
            </div>
            <div class="badges">
              ${ev.primary_link ? `<span class="badge">primary link: <code>origin-preferred</code></span>` : `<span class="badge">primary link: <code>none</code></span>`}
            </div>
          </div>

          <div class="summary">
            <div>
              <div class="label">Modes</div>
              <div class="value">${joinOrDash(ev.modes)}</div>
            </div>
            <div>
              <div class="label">Bands</div>
              <div class="value">${joinOrDash(ev.bands)}</div>
            </div>
            <div>
              <div class="label">Exchange</div>
              <div class="value">${safe(ev.exchange)}</div>
            </div>
            <div>
              <div class="label">Scoring</div>
              <div class="value">${safe(ev.scoring)}</div>
            </div>
            <div>
              <div class="label">Geo scope</div>
              <div class="value">${safe(ev.geo_scope)}</div>
            </div>
            <div>
              <div class="label">Notes</div>
              <div class="value">${safe(ev.notes)}</div>
            </div>
          </div>

          ${links ? `<div class="links">${links}</div>` : ``}
        </div>
      `;
    }).join("");
  }

  qEl.addEventListener("input", render);
  typeEl.addEventListener("change", render);
  statusEl.addEventListener("change", render);

  render();
})();
