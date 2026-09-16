"""Kontrol panelinin tek dosyalik arayuzu (HTML + CSS + JS)."""

PAGE = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HusCC Kontrol Paneli</title>
<style>
  :root{
    --bg:#070b14; --panel:#0e1524; --panel-2:#131c30; --line:#1f2b45;
    --ink:#e8eefc; --muted:#8d9cba; --gold:#ffc400; --red:#e63946;
    --green:#3ddc84; --blue:#4da3ff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:14px/1.5 "Segoe UI",system-ui,sans-serif}
  a{color:var(--gold)}
  header{display:flex;align-items:center;gap:14px;padding:14px 20px;
         background:linear-gradient(90deg,#0b1220,#131c30);border-bottom:1px solid var(--line);
         position:sticky;top:0;z-index:20}
  .logo{font-weight:800;font-size:20px;letter-spacing:.5px}
  .logo span{color:var(--gold)}
  .chips{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
  .chip{font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--line);
        background:#0b1220;color:var(--muted);white-space:nowrap}
  .chip.ok{color:var(--green);border-color:#1d4d33}
  .chip.bad{color:var(--red);border-color:#4d1d22}
  .wrap{display:grid;grid-template-columns:330px 1fr;gap:16px;padding:16px;align-items:start}
  @media(max-width:900px){.wrap{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
  .card h2{margin:0 0 10px;font-size:14px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
  .vid{padding:10px;border-radius:10px;border:1px solid transparent;cursor:pointer;
       display:flex;flex-direction:column;gap:3px}
  .vid:hover{background:var(--panel-2)}
  .vid.active{background:var(--panel-2);border-color:var(--gold)}
  .vid b{font-weight:600;font-size:13px;word-break:break-word}
  .vid small{color:var(--muted);font-size:11px}
  .tag{display:inline-block;font-size:10px;padding:1px 7px;border-radius:999px;
       background:#1b2740;color:var(--blue);margin-right:4px}
  .tag.up{background:#16351f;color:var(--green)}
  .tag.warn{background:#3a2a10;color:var(--gold)}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  button{background:var(--panel-2);border:1px solid var(--line);color:var(--ink);
         padding:9px 14px;border-radius:9px;cursor:pointer;font-size:13px;font-weight:600}
  button:hover{border-color:var(--gold)}
  button:disabled{opacity:.45;cursor:not-allowed}
  button.primary{background:var(--gold);color:#1a1200;border-color:var(--gold)}
  button.danger{border-color:#5a2026;color:#ff8a94}
  button.ghost{background:transparent}
  label.opt{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
  select,input[type=number],input[type=text]{background:#0a1120;border:1px solid var(--line);
         color:var(--ink);border-radius:8px;padding:7px 9px;font-size:13px}
  .tabs{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}
  .tab{padding:7px 13px;border-radius:9px;cursor:pointer;font-size:13px;color:var(--muted);
       border:1px solid transparent}
  .tab.active{background:var(--panel-2);color:var(--ink);border-color:var(--line)}
  pre,textarea{background:#060a12;border:1px solid var(--line);border-radius:10px;
       padding:12px;color:#cfe0ff;font:12px/1.55 "Cascadia Mono",Consolas,monospace;
       white-space:pre-wrap;word-break:break-word;width:100%}
  textarea{min-height:360px;resize:vertical}
  #log{height:260px;overflow:auto;margin:0}
  #log .l-ok{color:var(--green)} #log .l-err{color:#ff7b86} #log .l-warn{color:var(--gold)}
  #log .l-step{color:var(--blue);font-weight:700}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
  .grid img{width:100%;border-radius:8px;border:2px solid transparent;cursor:pointer;display:block}
  .grid img.sel{border-color:var(--gold)}
  .meta-k{color:var(--muted);font-size:12px}
  .empty{color:var(--muted);padding:20px;text-align:center}
  .bar{height:3px;background:var(--line);border-radius:2px;overflow:hidden;margin-top:10px}
  .bar i{display:block;height:100%;width:0;background:var(--gold);transition:width .3s}
  .hint{color:var(--muted);font-size:12px;line-height:1.6}
  .kv{display:grid;grid-template-columns:120px 1fr;gap:6px 12px;font-size:13px}
  .kv div:nth-child(odd){color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="logo">Hus<span>CC</span></div>
  <div class="hint" id="channelLine">yukleniyor...</div>
  <div class="chips" id="chips"></div>
</header>

<div class="wrap">
  <!-- SOL: video listesi -->
  <div style="display:flex;flex-direction:column;gap:16px">
    <div class="card">
      <h2>CC Klasoru</h2>
      <div class="row" style="margin-bottom:10px">
        <button class="ghost" onclick="refresh()">Yenile</button>
        <button class="ghost" onclick="openPath(BOOT.doctor.video_dir)">Klasoru ac</button>
      </div>
      <div id="videos"></div>
    </div>
    <div class="card">
      <h2>Yayin Gecmisi</h2>
      <div id="history" class="hint"></div>
    </div>
  </div>

  <!-- SAG: detay -->
  <div style="display:flex;flex-direction:column;gap:16px">
    <div class="card" id="actions">
      <h2>Islemler</h2>
      <div id="selName" style="font-weight:700;margin-bottom:10px">Soldan bir video sec</div>
      <div class="row" style="margin-bottom:10px">
        <button class="primary" onclick="run('publish')">Videomu paylas</button>
        <button onclick="run('prep')">1 · Analiz</button>
        <button onclick="run('render')">2 · Kurgu + Kapak</button>
        <button onclick="run('upload')">3 · Yukle</button>
      </div>
      <div class="row" style="margin-bottom:10px">
        <button class="ghost" onclick="run('update')">Meta veriyi guncelle</button>
        <button class="ghost" onclick="runOpts('update',{rebuild:true})">SEO'yu tazele + guncelle</button>
        <button class="ghost" onclick="run('probe')">Secici sondasi</button>
      </div>
      <div class="row">
        <label class="opt">Beyin
          <select id="brain">
            <option value="claude-code">claude-code (Claude kareleri okur)</option>
            <option value="heuristic">heuristic (dosya adi + ses)</option>
            <option value="api">api (API anahtari ile)</option>
          </select>
        </label>
        <label class="opt">Kare <input type="number" id="frames" value="14" min="6" max="40" style="width:70px"></label>
        <label class="opt"><input type="checkbox" id="subs" checked> Altyazi</label>
        <label class="opt"><input type="checkbox" id="shorts" checked> Shorts uret</label>
        <label class="opt"><input type="checkbox" id="upload_shorts"> Shorts'u da yukle</label>
        <label class="opt"><input type="checkbox" id="dry_run"> Deneme (yukleme yok)</label>
        <label class="opt"><input type="checkbox" id="skip_edit"> Kurguyu atla</label>
        <label class="opt"><input type="checkbox" id="force"> Yayinlanmis olsa da yukle</label>
        <label class="opt">Yayin yolu
          <select id="via">
            <option value="">config (varsayilan)</option>
            <option value="browser">browser (Studio)</option>
            <option value="api">api</option>
          </select>
        </label>
      </div>
      <div class="bar"><i id="bar"></i></div>
    </div>

    <div class="card">
      <div class="tabs">
        <div class="tab active" data-t="log" onclick="tab('log')">Canli Kayit</div>
        <div class="tab" data-t="brief" onclick="tab('brief')">Brief</div>
        <div class="tab" data-t="thumb" onclick="tab('thumb')">Kapak</div>
        <div class="tab" data-t="meta" onclick="tab('meta')">Meta Veri</div>
        <div class="tab" data-t="frames" onclick="tab('frames')">Kareler</div>
        <div class="tab" data-t="shots" onclick="tab('shots')">Tarayici</div>
        <div class="tab" data-t="setup" onclick="tab('setup')">Kurulum</div>
      </div>

      <div class="pane" id="pane-log">
        <pre id="log">Hazir.</pre>
      </div>

      <div class="pane" id="pane-brief" hidden>
        <div class="row" style="margin-bottom:8px">
          <button onclick="saveBrief()">brief.json kaydet</button>
          <button class="ghost" onclick="loadDraft()">Taslagi yukle</button>
          <span class="hint" id="briefMsg"></span>
        </div>
        <textarea id="briefBox" spellcheck="false"></textarea>
      </div>

      <div class="pane" id="pane-thumb" hidden>
        <div class="card" style="background:var(--panel-2);margin-bottom:14px">
          <h2>ChatGPT Gorseli</h2>
          <div class="row" style="margin-bottom:8px">
            <label class="opt">Kaynak
              <select id="image_source">
                <option value="auto">auto (anahtar varsa ChatGPT)</option>
                <option value="api">api (gpt-image-1)</option>
                <option value="browser">browser (tarayicida ChatGPT)</option>
                <option value="frame">frame (video karesi)</option>
              </select>
            </label>
            <button onclick="aiOpen()">ChatGPT'yi ac + prompt'u kopyala</button>
            <button class="ghost" onclick="el('aiFile').click()">Gorseli yukle</button>
            <input type="file" id="aiFile" accept="image/*" hidden onchange="aiUpload(this)">
            <span class="hint" id="aiMsg"></span>
          </div>
          <div id="aiDrop" class="hint"
               style="border:1px dashed var(--line);border-radius:10px;padding:14px;text-align:center">
            Uretilen gorseli buraya surukle-birak, ya da yukaridan yukle.
            Sonra <b>Kurgu + Kapak</b>'i tekrar calistir.
          </div>
          <pre id="aiPrompt" style="margin-top:10px;max-height:190px;overflow:auto"></pre>
        </div>
        <div class="hint" style="margin-bottom:8px">Varyanta tiklayarak yayinlanacak kapagi sec.</div>
        <div class="grid" id="thumbs"></div>
      </div>

      <div class="pane" id="pane-meta" hidden>
        <div id="metaBox"></div>
      </div>

      <div class="pane" id="pane-frames" hidden>
        <div class="grid" id="frames"></div>
      </div>

      <div class="pane" id="pane-shots" hidden>
        <div id="issueBox"></div>
        <div class="grid" id="shots"></div>
      </div>

      <div class="pane" id="pane-setup" hidden>
        <div class="row" style="margin-bottom:10px">
          <button class="primary" onclick="run('login')">Google'a giris yap (tarayici)</button>
          <button class="ghost" onclick="run('doctor')">Sistem kontrolu</button>
          <button class="ghost" onclick="run('probe')">Secici sondasi calistir</button>
          <button class="ghost" onclick="run('auth')">API yolu icin yetkilendir</button>
        </div>
        <div class="hint" style="margin-bottom:10px">
          Varsayilan yol <b>tarayici</b>: HusCC gercek Chrome'u acar, YouTube Studio'ya
          girer ve yuklemeyi orada yapar. API anahtari, Google Cloud projesi gerekmez.
          Bir kez giris yapman yeterli; oturum saklanir.
        </div>
        <pre id="setupHelp" class="hint"></pre>
      </div>
    </div>
  </div>
</div>

<script>
let BOOT = {doctor:{}}, SEL = null, DETAIL = null, BUSY = false;

function el(id){return document.getElementById(id)}
function esc(s){return (s||"").replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}

async function api(path, opts){
  const r = await fetch(path, opts);
  const t = await r.text();
  try { return JSON.parse(t) } catch(e){ return {error:t} }
}

async function refresh(){
  BOOT = await api('/api/bootstrap');
  const d = BOOT.doctor || {};
  el('channelLine').textContent =
    (BOOT.channel?.name||'HusCC') + ' · ' +
    (d.profile_ready ? 'tarayici oturumu hazir' : 'once Google girisi gerekiyor');
  el('chips').innerHTML = [
    chip('ffmpeg', d.ffmpeg), chip('altyazi', d.whisper),
    chip('playwright', d.playwright), chip(d.browser_channel||'chrome', d.browser),
    chip('oturum', d.profile_ready), chip('gorsel api', d.api_key)
  ].join('') + `<span class="chip">yol: ${d.via||'browser'}</span>`;
  el('setupHelp').textContent = d.setup_help || '';
  drawVideos(BOOT.videos || []);
  drawHistory(BOOT.history || []);
}

function chip(label, good){
  return `<span class="chip ${good?'ok':'bad'}">${good?'✓':'✗'} ${label}</span>`;
}

function drawVideos(list){
  const host = el('videos');
  if(!list.length){
    host.innerHTML = '<div class="empty">CC klasoru bos.<br>Ekran kaydini oraya koyun.</div>';
    return;
  }
  host.innerHTML = list.map(v=>{
    let tags = '';
    if(v.url) tags += '<span class="tag up">yayinda</span>';
    else if(v.stage==='render') tags += '<span class="tag">kurgu hazir</span>';
    else if(v.stage==='prep') tags += v.has_brief? '<span class="tag">brief var</span>'
                                                 : '<span class="tag warn">brief bekliyor</span>';
    return `<div class="vid ${SEL===v.name?'active':''}" onclick="select('${esc(v.name).replace(/'/g,"\\'")}')">
      <b>${esc(v.file)}</b>
      <small>${v.size} ${tags}</small>
      ${v.title? '<small>'+esc(v.title)+'</small>':''}
    </div>`;
  }).join('');
}

function drawHistory(list){
  el('history').innerHTML = list.length
    ? list.slice().reverse().map(h=>`<div style="margin-bottom:8px">
        <a href="${h.url}" target="_blank">${esc(h.title||h.slug)}</a><br>
        <small>${(h.uploaded_at||'').slice(0,16).replace('T',' ')}</small></div>`).join('')
    : 'Henuz yayinlanmis video yok.';
}

async function select(name){
  SEL = name;
  el('selName').textContent = name;
  drawVideos(BOOT.videos||[]);
  DETAIL = await api('/api/detail/' + encodeURIComponent(name));
  if(DETAIL.error){ el('selName').textContent = DETAIL.error; return }
  if(DETAIL.published){
    el('selName').innerHTML = esc(name) +
      ` <a href="https://youtu.be/${DETAIL.video_id}" target="_blank" class="tag up">yayinda</a>`;
  }
  el('briefBox').value = JSON.stringify(DETAIL.brief || DETAIL.draft || {}, null, 2);
  drawThumbs(); drawMeta(); drawFrames(); drawAi(); drawShots();
}

async function aiOpen(){
  const r = await api('/api/aiopen', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: SEL})});
  el('aiMsg').textContent = r.error ? r.error
    : (r.copied ? 'Prompt panoya kopyalandi, ChatGPT acildi.' : 'ChatGPT acildi, prompt asagida.');
  if(r.prompt) el('aiPrompt').textContent = r.prompt;
}

async function sendImage(file){
  const b64 = await new Promise(res=>{
    const fr = new FileReader(); fr.onload = ()=>res(fr.result); fr.readAsDataURL(file);
  });
  const r = await api('/api/aiupload', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: SEL, data: b64})});
  el('aiMsg').textContent = r.error ? r.error : 'Gorsel alindi. Simdi "Kurgu + Kapak" calistir.';
}

function aiUpload(input){ if(input.files?.[0]) sendImage(input.files[0]) }

function drawAi(){
  el('aiPrompt').textContent = DETAIL?.ai_prompt || '';
  if(DETAIL?.thumb_source) el('aiMsg').textContent = 'Son kapak kaynagi: ' + DETAIL.thumb_source;
}

function drawThumbs(){
  const host = el('thumbs');
  if(!DETAIL || !DETAIL.thumbs.length){
    host.innerHTML = '<div class="empty">Kapak yok. Once "Kurgu + Kapak" calistirin.</div>'; return;
  }
  host.innerHTML = DETAIL.thumbs.map(t=>`
    <figure style="margin:0">
      <img src="/media/thumb/${DETAIL.slug}/${t}?t=${Date.now()}"
           class="${DETAIL.chosen_thumb===t?'sel':''}" onclick="chooseThumb('${t}')">
      <figcaption class="hint">${t}</figcaption>
    </figure>`).join('');
}

async function chooseThumb(file){
  const r = await api('/api/thumb', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: SEL, file})});
  if(r.error) alert(r.error); else select(SEL);
}

function drawFrames(){
  const host = el('frames');
  if(!DETAIL || !DETAIL.frames.length){ host.innerHTML='<div class="empty">Kare yok.</div>'; return }
  host.innerHTML = DETAIL.frames.map(f=>`
    <figure style="margin:0"><img src="/media/frame/${DETAIL.slug}/${f}">
    <figcaption class="hint">${f}</figcaption></figure>`).join('');
}

function drawShots(){
  const host = el('shots');
  const issue = el('issueBox');
  if(!DETAIL){ host.innerHTML=''; issue.innerHTML=''; return }
  issue.innerHTML = DETAIL.browser_issue
    ? `<pre style="border-color:#5a2026">${esc(DETAIL.browser_issue)}</pre>` : '';
  const todo = DETAIL.manual_todo || [];
  if(todo.length){
    issue.innerHTML += '<div class="card" style="background:var(--panel-2);margin-bottom:12px">'
      + '<h2>Elle yapilacaklar</h2>'
      + todo.map(t=>`<div>• ${esc(t)}</div>`).join('') + '</div>';
  }
  host.innerHTML = (DETAIL.shots||[]).length
    ? DETAIL.shots.map(f=>`<figure style="margin:0">
        <img src="/media/shot/${DETAIL.slug}/${f}?t=${Date.now()}">
        <figcaption class="hint">${f}</figcaption></figure>`).join('')
    : '<div class="empty">Henuz tarayici adimi calismadi.</div>';
}

function drawMeta(){
  const m = DETAIL?.metadata || {};
  if(!m.title){ el('metaBox').innerHTML = '<div class="empty">Meta veri yok. "Kurgu + Kapak" calistirin.</div>'; return }
  const alts = (m.title_alternatives||[]).map(a=>`<div>[${a.score}] ${esc(a.title)}</div>`).join('');
  el('metaBox').innerHTML = `
    <div class="kv">
      <div>Baslik</div><div><b>${esc(m.title)}</b> <span class="hint">(${m.title.length} karakter)</span></div>
      <div>Gizlilik</div><div>${m.privacy}${m.publish_at? ' · planli: '+m.publish_at : ''}</div>
      <div>Oynatma L.</div><div>${esc(m.playlist||'-')}</div>
      <div>Etiketler</div><div class="hint">${esc((m.tags||[]).join(', '))}</div>
      <div>Bolumler</div><div class="hint">${(m.chapters||[]).map(c=>esc(c.label)).join(' · ')||'-'}</div>
      <div>Diller</div><div>${Object.keys(m.localizations||{}).join(', ')||'-'}</div>
      <div>Alternatif</div><div class="hint">${alts||'-'}</div>
    </div>
    <h2 style="margin-top:16px">Aciklama</h2>
    <pre>${esc(m.description||'')}</pre>`;
}

async function saveBrief(){
  let payload;
  try { payload = JSON.parse(el('briefBox').value) }
  catch(e){ el('briefMsg').textContent = 'JSON hatasi: ' + e.message; return }
  const r = await api('/api/brief', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: SEL, brief: payload})});
  el('briefMsg').textContent = r.error ? r.error
    : (r.problems?.length ? 'Kaydedildi, eksikler: ' + r.problems.join(' | ') : 'Kaydedildi ✓');
  refresh();
}

function loadDraft(){
  if(DETAIL?.draft) el('briefBox').value = JSON.stringify(DETAIL.draft, null, 2);
}

function tab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.t===name));
  document.querySelectorAll('.pane').forEach(p=>p.hidden = p.id !== 'pane-'+name);
}

function opts(){
  return {
    brain: el('brain').value,
    frames: parseInt(el('frames').value||'14',10),
    subs: el('subs').checked,
    shorts: el('shorts').checked,
    upload_shorts: el('upload_shorts').checked,
    dry_run: el('dry_run').checked,
    image_source: el('image_source').value,
    via: el('via').value,
    force: el('force').checked,
    skip_edit: el('skip_edit').checked
  };
}

async function runOpts(action, extra){
  if(BUSY){ alert('Zaten calisan bir is var.'); return }
  if(!SEL && !['auth','doctor','login','probe'].includes(action)){ alert('Once bir video secin.'); return }
  tab('log'); el('log').textContent = '';
  const r = await api('/api/run', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action, name: SEL, options: {...opts(), ...(extra||{})}})});
  if(r.error){ alert(r.error); return }
  BUSY = true; el('bar').style.width = '8%';
}

async function run(action){
  if(BUSY){ alert('Zaten calisan bir is var.'); return }
  if(!SEL && !['auth','doctor','login','probe'].includes(action)){ alert('Once bir video secin.'); return }
  tab('log');
  el('log').textContent = '';
  const r = await api('/api/run', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action, name: SEL, options: opts()})});
  if(r.error){ alert(r.error); return }
  BUSY = true; el('bar').style.width = '8%';
}

async function openPath(p){
  await api('/api/open', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({path:p})});
}

function logLine(line){
  if(line.startsWith('::start::')){ BUSY=true; el('bar').style.width='10%'; return }
  if(line.startsWith('::done::')){
    BUSY=false; el('bar').style.width='100%';
    setTimeout(()=>el('bar').style.width='0', 1200);
    refresh(); if(SEL) select(SEL);
    return;
  }
  const box = el('log');
  let cls = '';
  if(line.startsWith('✓')||line.startsWith('+')) cls='l-ok';
  else if(line.startsWith('✗')||line.startsWith('x ')) cls='l-err';
  else if(line.startsWith('!')) cls='l-warn';
  else if(line.startsWith('▸')||line.startsWith('*')) cls='l-step';
  box.insertAdjacentHTML('beforeend', `<span class="${cls}">${esc(line)}</span>\n`);
  box.scrollTop = box.scrollHeight;
  const w = parseInt(el('bar').style.width||'10');
  if(BUSY && w < 92) el('bar').style.width = (w+2)+'%';
}

const drop = el('aiDrop');
['dragover','dragenter'].forEach(e=>drop.addEventListener(e, ev=>{
  ev.preventDefault(); drop.style.borderColor='var(--gold)';
}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e, ev=>{
  ev.preventDefault(); drop.style.borderColor='var(--line)';
}));
drop.addEventListener('drop', ev=>{
  const f = ev.dataTransfer?.files?.[0];
  if(f && SEL) sendImage(f);
});

const es = new EventSource('/api/stream');
es.onmessage = e => { try{ logLine(JSON.parse(e.data).line) }catch(_){} };

refresh();
</script>
</body>
</html>
"""
