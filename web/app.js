/* DeepArch MVP SPA */
const $ = (s, el=document) => el.querySelector(s);
const api = (path, opts={}) => fetch('/api'+path, {
  ...opts,
  headers: {'Content-Type':'application/json', 'X-Token': localStorage.token||'', ...(opts.headers||{})}
}).then(async r => { const d = await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.detail||r.status); return d; });

let S = { user:null, standard:null };
/* Mermaid: C4 / deployment / ER / flowchart */
if(window.mermaid){
  mermaid.initialize({ startOnLoad:false, theme:'neutral', securityLevel:'strict',
    flowchart:{ useMaxWidth:true }, c4:{ useMaxWidth:true }, er:{ useMaxWidth:true } });
}
const esc = s => String(s??'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const badge = (txt, cls) => `<span class="badge b-${cls}">${esc(txt)}</span>`;
const gradeB = g => badge(g==='E'?'Есть':g==='Ch'?'Частично':'Нет', g);
const weightB = w => badge(w==='mandatory'?'обязательный':w==='desired'?'желательно':'не обязательный', w);
const statusB = s => badge(s.replace('_',' '), s);
const gradeVal = g => g==='E'?1:g==='Ch'?0.5:0;

function toast(msg, err=false){
  const t = document.createElement('div');
  t.className = 'toast'+(err?' err':''); t.innerHTML = msg;
  $('#toast').append(t); setTimeout(()=>t.remove(), 4200);
}

/* ---------- router ---------- */
const routes = [];
const route = (re, fn) => routes.push([re, fn]);
async function render(){
  if(!S.user){ return viewLogin(); }
  const h = location.hash || '#/';
  const nav = {'#/':'Дашборд','#/services':'Сервисы','#/debts':'Техдолг','#/components':'Компоненты','#/access':'Доступ','#/admin':'Интеграции'};
  $('#nav').innerHTML = Object.entries(nav).map(([u,t]) =>
    `<a href="${u}" class="${h.startsWith(u)&&u!=='#/'||h===u?'act':''}">${t}</a>`).join('');
  $('#userbox').innerHTML = `${esc(S.user.display_name)} · ${S.user.role} <button class="sec" onclick="logout()">Выйти</button>`;
  if(!S.standard) S.standard = await api('/standard');
  for(const [re, fn] of routes){ const m = h.match(re); if(m) return fn(...m.slice(1)); }
  return viewDash();
}

/* ---------- login ---------- */
function viewLogin(){
  $('#nav').innerHTML=''; 
  $('#view').innerHTML = `<div class="login"><div class="card vio">
    <h1>DeepArch</h1><p class="mut">Проектирование и ревью архитектуры по стандарту компании</p>
    <label>Логин</label>
    <input id="lg" autocomplete="username" placeholder="например, admin">
    <label style="margin-top:8px">Пароль</label>
    <input id="pw" type="password" autocomplete="current-password" placeholder="••••••"
           onkeydown="if(event.key==='Enter')login()">
    <div class="btnrow"><button onclick="login()">Войти</button></div>
    <p class="mut small" style="margin-top:14px">Демо-учётки (пароль <b>123456</b>):
      <b>admin</b> · <b>expert</b> (domain_expert) · <b>lead</b> (team_lead) · <b>sec</b> (infosec) · <b>viewer</b></p>
  </div></div>`;
}
async function login(){
  const username = $('#lg').value.trim(), password = $('#pw').value;
  if(!username || !password) return toast('Введите логин и пароль', true);
  try{
    const r = await api('/login', {method:'POST', body: JSON.stringify({username, password})});
    localStorage.token = r.token; S.user = r.user; location.hash='#/'; render();
    toast(`Добро пожаловать, ${esc(r.user.display_name)}`);
  }catch(e){ toast(esc(e.message), true); }
}
async function logout(){
  try{ await api('/logout', {method:'POST', body: '{}'}); }catch{}
  delete localStorage.token; S.user=null; location.hash='#/'; render();
}

/* ---------- dashboard ---------- */
route(/^#\/$/, viewDash);
route(/^#\/admin$/, viewAdmin);
route(/^#\/services$/, viewServices);
route(/^#\/service\/(\d+)(?:\/(\w+))?$/, (id, tab) => viewService(+id, tab));
route(/^#\/components$/, viewComponents);
route(/^#\/debts$/, viewDebts);
route(/^#\/access$/, async () => { SVC_CACHE = await api('/services'); return viewAccess(); });

async function viewDash(){
  const d = await api('/dashboard');
  const st = s => d.by_review_status.find(x=>x.review_status===s)?.n||0;
  $('#view').innerHTML = `
  <h1>Дашборд соответствия стандарту</h1>
  <p class="mut"><a class="lnk" href="${d.standard_ref}" target="_blank">Общий архитектурный стандарт (Architecture Definition Set) ↗</a></p>
  <div class="grid g3" style="margin:18px 0">
    <div class="card vio"><div class="mut">Сервисов в реестре</div><div class="kpi">${d.total_services}</div></div>
    <div class="card"><div class="mut">На ревью / согласовано</div><div class="kpi">${st('in_review')} <span class="mut" style="font-size:16px">/</span> <span style="color:var(--ok)">${st('approved')}</span></div></div>
    <div class="card cya"><div class="mut">Нужны изменения</div><div class="kpi" style="color:var(--warn)">${st('changes_requested')}</div></div>
  </div>
  <h2>Последняя активность</h2>
  <div class="card"><table><tr><th>Сервис</th><th>Self-check</th><th>Статус ревью</th></tr>
  ${d.recent.map(r=>`<tr><td><a class="lnk" href="#/service/${r.id}"><b>${esc(r.name)}</b> <span class="mut">${esc(r.code)}</span></a></td>
    <td><div class="bar" style="width:130px"><i style="width:${r.score||0}%"></i></div><span class="small mut">${r.score||0}%</span></td>
    <td>${statusB(r.review_status)}</td></tr>`).join('')}
  </table></div>
  <h2>Переиспользование компонентов</h2>
  <div class="card"><table><tr><th>Компонент</th><th>Статус</th><th>Используют сервисов</th></tr>
  ${d.component_usage.map(c=>`<tr><td>${esc(c.name)}</td><td>${statusB(c.status)}</td><td><b>${c.used_by}</b></td></tr>`).join('')}
  </table></div>
  <footer>DeepArch MVP · BR-01…37 · источники: Architecture Definition Set (Confluence DA), self-check (10 пунктов), матрица типов проектов</footer>`;
}

/* ---------- services ---------- */
async function viewServices(){
  const list = await api('/services');
  $('#view').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center">
    <h1>Реестр сервисов</h1><button onclick="formService()">+ Сервис</button></div>
  <p class="mut">Карточка сервиса (BR-01, пункт 10 чек-листа) · тип проекта определяет обязательный набор артефактов</p>
  <div class="card" style="margin-top:16px"><table><tr><th>Сервис</th><th>Тип проекта</th><th>Владелец / архитектор</th><th>Self-check</th><th>Ревью</th><th>CMDB</th></tr>
  ${list.map(s=>`<tr><td><a class="lnk" href="#/service/${s.id}"><b>${esc(s.name)}</b></a><div class="small mut">${esc(s.code)} · ${esc(s.domain||'—')}</div></td>
    <td class="small">${esc(S.standard.project_types[s.project_type]?.title||s.project_type)}</td>
    <td class="small">${esc(s.owner||'—')} / ${esc(s.architect||'—')}</td>
    <td><div class="bar" style="width:110px"><i style="width:${s.last_score||0}%"></i></div><span class="small mut">${s.last_score||0}%</span></td>
    <td>${statusB(s.review_status)}</td>
    <td class="small">${s.cmdb_id?`<code>${esc(s.cmdb_id)}</code>`:'<span class="mut">—</span>'}</td></tr>`).join('')}
  </table></div>`;
}
function formService(){
  const opts = Object.entries(S.standard.project_types).map(([k,v])=>`<option value="${k}">${esc(v.title)}</option>`).join('');
  openModal(`Новый сервис`, `<label>Код (напр. MPR)</label><input id="f-code">
    <label>Название</label><input id="f-name">
    <label>Тип проекта</label><select id="f-pt">${opts}</select>
    <div class="grid g2"><div><label>Домен</label><input id="f-domain"></div>
    <div><label>Владелец</label><input id="f-owner"></div></div>
    <div class="btnrow"><button onclick="createService()">Создать</button></div>`);
}
async function createService(){
  try{
    const r = await api('/services', {method:'POST', body: JSON.stringify({
      code:$('#f-code').value, name:$('#f-name').value, project_type:$('#f-pt').value,
      domain:$('#f-domain').value, owner:$('#f-owner').value})});
    closeModal(); toast(`Сервис ${r.code} создан — 7 артефактов заведены по стандарту`);
    location.hash = `#/service/${r.id}`;
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- service detail ---------- */
const TABS = [['card','Карточка'],['artifacts','Артефакты (7)'],['diagrams','Диаграммы'],['check','Self-check'],['review','Ревью'],['components','Компоненты']];
let SERVICE = null;
async function viewService(id, tab='card'){
  const s = await api('/services/'+id); SERVICE = s;
  const active = tab||'card';
  const tabs = [...TABS, ['debt', 'Техдолг'+(s.debts.length?` (${s.debts.length})`:'')]];
  $('#view').innerHTML = `
  <p class="small"><a class="lnk" href="#/services">← Реестр сервисов</a></p>
  <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <h1>${esc(s.name)}</h1>${statusB(s.review_status)}
    ${s.my_scope?`<span class="badge ${s.my_scope==='full'?'b-approved':s.my_scope==='team'?'b-in_review':'b-draft'}"
      title="${s.my_scope==='full'?'Полные права (эксперт/админ)':s.my_scope==='team'?'Права команды (product-группа или owner в карточке)':'Только просмотр'}">
      ${s.my_scope==='full'?'полный доступ':s.my_scope==='team'?'доступ команды':'только просмотр'}</span>`:''}
    <span class="chip">тип: <b>${esc(S.standard.project_types[s.project_type]?.title||s.project_type)}</b></span>
    ${s.cmdb_id?`<span class="chip">CMDB: <b>${esc(s.cmdb_id)}</b></span>`:''}
  </div>
  <div class="tabs">${tabs.map(([k,t])=>`<a class="${k===active?'act':''}" href="#/service/${id}/${k}">${t}</a>`).join('')}</div>
  <div id="tabbody"></div>`;
  ({card:tabCard, artifacts:tabArtifacts, diagrams:tabDiagrams, check:tabCheck, review:tabReview,
    components:tabComponents, debt:tabDebt}[active])(s);
}

/* ---------- диаграммы (Mermaid) ---------- */
const _deb = {};
function liveDiagram(el){
  const id = el.id, kind = id.replace(/^d-/,'dv-');
  clearTimeout(_deb[id]);
  _deb[id] = setTimeout(()=>renderDiag(document.getElementById(kind), el.value), 700);
}
async function renderDiag(el, code){
  if(!el) return;
  if(!window.mermaid){ el.innerHTML = '<span class="mut small">Mermaid не загрузился</span>'; return; }
  if(!code || !code.trim()){
    el.innerHTML = '<div class="empty">Исходник диаграммы не задан.<br>Стандарт требует хранить исходники (dsl/json/mermaid) — вставьте Mermaid-код слева.</div>';
    return;
  }
  try{
    const {svg} = await mermaid.render('m'+Math.random().toString(36).slice(2), code.trim());
    el.classList.remove('diag-err'); el.innerHTML = svg;
  }catch(e){
    el.classList.add('diag-err');
    el.innerHTML = `<div class="small" style="color:var(--bad)">⚠ Ошибка синтаксиса Mermaid: ${esc(String(e.message||e)).slice(0,220)}</div>`;
  }
}
function tabDiagrams(s){
  const arts = S.standard.artifacts;
  const byKind = Object.fromEntries(s.artifacts.map(a=>[a.kind,a]));
  const withDiag = arts.filter(a=>(byKind[a.kind]?.diagram_code||'').trim());
  $('#tabbody').innerHTML = `<p class="mut small" style="margin-bottom:12px">
    Диаграммы рендерятся из исходников (Mermaid: C4 Context/Container/Deployment, erDiagram, flowchart) —
    исходник = единый источник правды, картинка вторична (требование стандарта о сохранении преемственности).</p>
  ${withDiag.length ? withDiag.map(a=>`
    <div class="card" style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>${esc(a.title)}</b><a class="lnk small" href="#/service/${s.id}/artifacts">редактировать →</a>
      </div>
      <div class="diag" id="dvx-${a.kind}"></div>
    </div>`).join('')
    : '<div class="card"><p class="mut">Ни у одного артефакта пока нет диаграммы. Откройте «Артефакты» и добавьте Mermaid-исходник.</p></div>'}`;
  withDiag.forEach(a => renderDiag(document.getElementById('dvx-'+a.kind), byKind[a.kind].diagram_code));
}

function tabCard(s){
  $('#tabbody').innerHTML = `<div class="grid g2">
  <div class="card vio"><h2 style="margin-top:0">Карточка сервиса</h2>
    <label>Название</label><input id="c-name" value="${esc(s.name)}">
    <div class="grid g2"><div><label>Код</label><input value="${esc(s.code)}" disabled></div>
    <div><label>Домен</label><input id="c-domain" value="${esc(s.domain||'')}"></div></div>
    <div class="grid g2"><div><label>Владелец</label><input id="c-owner" value="${esc(s.owner||'')}"></div>
    <div><label>Архитектор</label><input id="c-architect" value="${esc(s.architect||'')}"></div></div>
    <div class="grid g2"><div><label>Тип проекта</label><select id="c-pt">${Object.entries(S.standard.project_types).map(([k,v])=>`<option value="${k}" ${k===s.project_type?'selected':''}>${esc(v.title)}</option>`).join('')}</select></div>
    <div><label>Жизненный цикл</label><select id="c-lc">${['design','development','production','decommissioned'].map(l=>`<option ${l===s.lifecycle?'selected':''}>${l}</option>`).join('')}</select></div></div>
    <label>CMDB ID</label><input id="c-cmdb" value="${esc(s.cmdb_id||'')}" placeholder="CI из CMDB (BR-20)">
    <div class="btnrow"><button onclick="saveCard(${s.id})">Сохранить</button>
    <button class="cya" onclick="exportCatalog(${s.id})">Экспорт catalog-info.yaml (BR-21)</button></div></div>
  <div class="card"><h2 style="margin-top:0">Обязательные артефакты для типа</h2>
    <p class="mut small">Матрица «Минимальные наборы по типам проектов» из Навигатора стандарта</p>
    ${s.mandatory_artifacts.map(k=>`<span class="chip">● ${esc(S.standard.artifacts.find(a=>a.kind===k)?.title||k)}</span>`).join('')||'<span class="mut">—</span>'}
    <h2>Последний self-check</h2>
    ${s.checklist_runs[0]?`<div class="kpi">${s.checklist_runs[0].score_pct}%</div>
      <p class="small mut">обязательных не закрыто: <b style="color:${s.checklist_runs[0].mandatory_missing?'var(--bad)':'var(--ok)'}">${s.checklist_runs[0].mandatory_missing}</b> · ${new Date(s.checklist_runs[0].created_at*1000).toLocaleDateString('ru')}</p>`:'<p class="mut">— не проводился</p>'}
  </div></div>`;
}
async function saveCard(id){
  await api('/services/'+id, {method:'PATCH', body: JSON.stringify({
    name:$('#c-name').value, domain:$('#c-domain').value, owner:$('#c-owner').value,
    architect:$('#c-architect').value, project_type:$('#c-pt').value, lifecycle:$('#c-lc').value,
    cmdb_id:$('#c-cmdb').value||null})});
  toast('Карточка сохранена'); viewService(id,'card');
}
async function exportCatalog(id){
  const r = await api('/integrations/services/'+id+'/catalog-export');
  openModal('catalog-info.yaml (BR-21, mock)', `<textarea style="min-height:320px">${esc(JSON.stringify(r.catalog_entity,null,2))}</textarea>`);
}

function tabArtifacts(s){
  const arts = S.standard.artifacts;
  const byKind = Object.fromEntries(s.artifacts.map(a=>[a.kind,a]));
  $('#tabbody').innerHTML = arts.map(a=>{
    const cur = byKind[a.kind]||{};
    const mandatory = s.mandatory_artifacts.includes(a.kind);
    return `<div class="card" style="margin-bottom:14px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <div><b>${esc(a.title)}</b> ${mandatory?'<span class="badge b-mandatory">обязательный для типа</span>':''}
      <div class="small mut">${esc(a.question)}</div></div>
      <div class="small mut">v${cur.version||1} · ${cur.updated_by?esc(cur.updated_by):'—'}</div>
    </div>
    <div class="split">
      <div>
        <label style="margin-top:10px">Описание (markdown)</label>
        <textarea id="a-${a.kind}" placeholder="Что фиксируем: ${esc(a.captures)}">${esc(cur.content_md||'')}</textarea>
        <label>Исходник диаграммы (Mermaid: C4Context / C4Container / C4Deployment / erDiagram / flowchart)</label>
        <textarea class="diagcode" id="d-${a.kind}" oninput="liveDiagram(this)" placeholder="${a.kind==='vision_c4'?'C4Context · Person · System · Rel · SHOW_LEGEND()':a.kind==='data_model'?'erDiagram · USER ||--o{ ORDER : places':a.kind==='deployment'?'C4Deployment · Deployment_Node → Container':'flowchart LR · A --> B'}">${esc(cur.diagram_code||'')}</textarea>
      </div>
      <div>
        <label style="margin-top:10px">Превью диаграммы (live)</label>
        <div class="diag" id="dv-${a.kind}"></div>
        <div class="small mut" style="margin-top:6px">${esc(a.required_artifacts.join(' · '))}</div>
      </div>
    </div>
    <div class="btnrow">
      <label style="margin:0;flex:1"><input id="u-${a.kind}" placeholder="Ссылка на исходник / файл (успех = ссылка)" value="${esc(cur.source_url||'')}"></label>
      <button class="sec" onclick="aiDraft(${s.id},'${a.kind}')">✨ AI-черновик</button>
      <button onclick="saveArt(${s.id},'${a.kind}')">Сохранить (v${(cur.version||1)+1})</button>
    </div></div>`;
  }).join('');
  // первичный рендер превью
  arts.forEach(a => { const cur = byKind[a.kind]||{}; renderDiag(document.getElementById('dv-'+a.kind), cur.diagram_code||''); });
}
async function saveArt(sid, kind){
  await api(`/services/${sid}/artifacts/${kind}`, {method:'PUT', body: JSON.stringify({
    content_md:$(`#a-${kind}`).value, source_url:$(`#u-${kind}`).value,
    diagram_code:$(`#d-${kind}`).value})});
  toast('Артефакт и диаграмма сохранены, версия поднята'); viewService(sid,'artifacts');
}
async function aiDraft(sid, kind){
  try{
    const r = await api('/ai/draft', {method:'POST', body: JSON.stringify({service_id:sid, kind})});
    $(`#a-${kind}`).value = r.content_md;
    toast('AI-черновик (mock-провайдер) вставлен — <b>требует подтверждения автора</b> (BR-28/33)');
  }catch(e){ toast(esc(e.message), true); }
}

function tabCheck(s){
  const last = s.last_answers || [];
  const ans = Object.fromEntries(last.map(a=>[a.item_id, a]));
  const runs = s.checklist_runs[0];
  $('#tabbody').innerHTML = `
  <div class="card" style="margin-bottom:14px"><div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
    <div><div class="mut small">Текущий скор</div><div class="kpi">${runs?.score_pct||0}%</div></div>
    <div><div class="mut small">Обязательных не закрыто</div><div class="kpi" style="color:${runs?.mandatory_missing?'var(--bad)':'var(--ok)'}">${runs?.mandatory_missing??'—'}</div></div>
    <div style="flex:1"></div>
    <button class="cya" onclick="aiPrecheck(${s.id})">✨ AI-prediction (BR-29)</button>
    <button onclick="submitCheck(${s.id})">Пройти self-check →</button>
  </div><div id="ai-pre"></div></div>
  <div class="card"><table><tr><th>#</th><th>Пункт</th><th>Критерий «есть»</th><th>Вес</th><th>Оценка</th><th>Ссылка</th></tr>
  ${S.standard.checklist.map(it=>{
    const a = ans[it.id]||{};
    return `<tr><td>${it.id}</td><td><b>${esc(it.item)}</b></td><td class="small mut">${esc(it.expected)}</td><td>${weightB(it.weight)}</td>
    <td><select id="g-${it.id}" style="width:110px">${['N','Ch','E'].map(g=>`<option ${a.grade===g?'selected':''} value="${g}">${{N:'Нет',Ch:'Частично',E:'Есть'}[g]}</option>`).join('')}</select></td>
    <td><input id="l-${it.id}" value="${esc(a.link||'')}" placeholder="ссылка обязательна"></td></tr>`;}).join('')}
  </table><p class="small mut" style="margin-top:10px">Правило стандарта: пункт без ссылки не считается пройденным → «Есть» автоматически понижается до «Частично». Порог ревью: все обязательные пункты = «Есть».</p></div>`;
}
function collectCheck(){
  return S.standard.checklist.map(it => ({item_id: it.id, grade: $(`#g-${it.id}`).value, link: $(`#l-${it.id}`).value}));
}
async function submitCheck(sid){
  try{
    const r = await api(`/services/${sid}/checklist`, {method:'POST', body: JSON.stringify({answers:collectCheck()})});
    toast(`Self-check: <b>${r.score_pct}%</b> · блокирующих: ${r.mandatory_missing} → ${r.verdict==='ready_for_review'?'<b style="color:var(--ok)">готов к ревью</b>':'<b style="color:var(--bad)">не готов</b>'}`, r.verdict!=='ready_for_review');
    viewService(sid,'check');
  }catch(e){ toast(esc(e.message), true); }
}
async function aiPrecheck(sid){
  const r = await api('/ai/precheck', {method:'POST', body: JSON.stringify({service_id:sid})});
  $('#ai-pre').innerHTML = `<div style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px">
    <b style="color:var(--cyan)">AI Gate · прогноз чек-листа</b> <span class="badge b-draft">${r.provider} · advisory</span>
    <div class="small mut" style="margin:6px 0">${r.predictions.filter(p=>p.predicted!=='E').length} пунктов требует внимания</div>
    ${r.issues.map(i=>`<div class="chip">⚠ <b>${esc(i.item)}</b> — ${esc(i.hint)} ${i.severity==='blocking'?'<b style="color:var(--bad)">блокер</b>':''}</div>`).join('')}
    <div class="small mut" style="margin-top:8px">Recommendation: заполните артефакты и приложите ссылки — затем пройдите self-check вручную. Решение за человеком (BR-33).</div></div>`;
}

function tabReview(s){
  const expertNote = S.user.role==='domain_expert' && s.review_status==='in_review';
  const open = s.reviews.find(r=>r.status==='in_review');
  $('#tabbody').innerHTML = `
  <div class="card vio" style="margin-bottom:14px"><h2 style="margin-top:0">Workflow ревью</h2>
    <p class="small mut">draft → in_review → approved / changes_requested. Gate: self-check без блокирующих обязательных пунктов.</p>
    <div class="btnrow">
      ${s.review_status==='in_review'
        ? `<span class="chip">Ревью идёт · запрошено <b>${esc(open?.requested_by||'')}</b></span>`
        : `<button onclick="requestReview(${s.id})">Отправить на ревью</button>`}
      ${expertNote?`
        <button class="btn-ok" onclick="decide(${open.id},'approved')">✓ Approved</button>
        <button class="btn-bad" onclick="decide(${open.id},'changes_requested')">✗ Changes requested</button>`:''}
    </div>
    ${expertNote?`<textarea class="sm" id="rv-comment" placeholder="Комментарий решения (необязательно)"></textarea>`:''}
  </div>
  <div class="card"><table><tr><th>#</th><th>Запрошено</th><th>Ревьюер</th><th>Решение</th><th>Комментарий</th></tr>
  ${s.reviews.map(r=>`<tr><td>${r.id}</td>
    <td class="small">${esc(r.requested_by)}<br><span class="mut">${new Date(r.requested_at*1000).toLocaleString('ru')}</span></td>
    <td>${esc(r.reviewer||'—')}</td><td>${statusB(r.status)}</td><td class="small mut">${esc(r.comment||'')}</td></tr>`).join('')||'<tr><td colspan=5 class="mut">Ревью ещё не было</td></tr>'}
  </table></div>`;
}
async function requestReview(sid){
  try{
    await api(`/services/${sid}/reviews`, {method:'POST', body:'{}'});
    toast('Отправлено на ревью к эксперту домена'); viewService(sid,'review');
  }catch(e){ toast(esc(e.message), true); }
}
async function decide(rid, verdict){
  try{
    await api(`/reviews/${rid}/decision`, {method:'POST', body: JSON.stringify({verdict, comment:$('#rv-comment')?.value})});
    toast(`Решение: <b>${verdict}</b>`); render();
  }catch(e){ toast(esc(e.message), true); }
}

function tabComponents(s){
  $('#tabbody').innerHTML = `<div class="card">
    <h2 style="margin-top:0">Подключённые компоненты</h2>
    ${s.components.map(c=>`<span class="chip"><b>${esc(c.name)}</b> ${statusB(c.status)} · ${esc(c.kind)}</span>`).join('')||'<p class="mut">Пока ничего — подключите из каталога</p>'}
    <h2>Каталог переиспользуемых компонентов</h2>
    <p class="small mut">BR-14…16: approved-компонент закрывает связанные пункты стандарта (compliance by construction)</p>
    <table><tr><th>Компонент</th><th>Тип</th><th>Статус</th><th></th></tr>
    ${COMP_CACHE.map(c=>`<tr><td><b>${esc(c.name)}</b><div class="small mut">${esc(c.description||'')}</div></td>
      <td class="small">${esc(c.kind)}</td><td>${statusB(c.status)}</td>
      <td><button class="sec" onclick="attach(${s.id},${c.id})">Подключить</button></td></tr>`).join('')}
    </table></div>`;
}
async function attach(sid, cid){
  const r = await api(`/services/${sid}/components`, {method:'POST', body: JSON.stringify({component_id:cid})});
  toast(r.note?esc(r.note):'Компонент подключён'); viewService(sid,'components');
}

/* ---------- components catalog ---------- */
let COMP_CACHE = [];
async function viewComponents(){
  COMP_CACHE = await api('/components');
  $('#view').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center">
    <div><h1>Каталог переиспользуемых компонентов</h1>
    <p class="mut">Паттерны · референсы · shared-библиотеки · boilerplate · одобренные технологии (BR-14…19)</p></div>
    ${['domain_expert','admin'].includes(S.user.role)?'<button onclick="formComponent()">+ Компонент</button>':''}</div>
  <div class="card" style="margin-top:16px"><table><tr><th>Компонент</th><th>Тип</th><th>Статус</th><th>Стандарт / ADR</th><th>Используют</th><th>Репозиторий</th></tr>
  ${COMP_CACHE.map(c=>`<tr><td><b>${esc(c.name)}</b><div class="small mut">${esc(c.description||'')}</div><div class="small mut">владелец: ${esc(c.owner_team||'—')}</div></td>
    <td class="small">${esc(c.kind)}</td><td>${statusB(c.status)}</td>
    <td class="small">${esc(c.standard_ref||'—')}${c.adr_ref?' · '+esc(c.adr_ref):''}</td>
    <td><b>${c.used_by}</b></td>
    <td class="small">${c.repo_url?`<a class="lnk" href="${esc(c.repo_url)}" target="_blank">repo ↗</a>`:'—'}</td></tr>`).join('')}
  </table></div>`;
}
function formComponent(){
  openModal('Новый компонент', `<label>Название</label><input id="k-name">
    <div class="grid g2"><div><label>Тип</label><select id="k-kind">${S.standard.component_kinds.map(k=>`<option>${k}</option>`).join('')}</select></div>
    <div><label>Статус</label><select id="k-status">${S.standard.component_statuses.map(k=>`<option>${k}</option>`).join('')}</select></div></div>
    <label>Описание</label><textarea class="sm" id="k-desc"></textarea>
    <div class="grid g2"><div><label>Связь со стандартом</label><input id="k-ref" placeholder="напр. ADR-004"></div>
    <div><label>Репозиторий</label><input id="k-repo"></div></div>
    <div class="btnrow"><button onclick="createComponent()">Создать</button></div>`);
}
async function createComponent(){
  try{
    await api('/components', {method:'POST', body: JSON.stringify({
      name:$('#k-name').value, kind:$('#k-kind').value, status:$('#k-status').value,
      description:$('#k-desc').value, standard_ref:$('#k-ref').value, repo_url:$('#k-repo').value,
      owner_team:S.user.display_name})});
    closeModal(); toast('Компонент добавлен в каталог'); render();
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- технический долг (BR-38…40, реестр DA) ---------- */
const DEBT_STATUS_BADGE = {new:'b-draft', accepted:'b-desired', planned:'b-mandatory',
                           in_progress:'b-in_review', repaid:'b-approved', cancelled:'b-draft'};
const DEBT_STATUS_RU = {new:'Новый', accepted:'Принят', planned:'Запланирован',
                        in_progress:'В работе', repaid:'Погашен', cancelled:'Отменён'};
const PRIO_BADGE = {P0:'b-changes_requested', P1:'b-in_review', P2:'b-mandatory', P3:'b-draft'};
const RISK_BADGE = {Critical:'b-changes_requested', High:'b-in_review', Medium:'b-mandatory', Low:'b-draft'};
function debtRow(d, withService){
  return `<tr>
    <td><span class="badge ${d.dtype==='AD'?'b-changes_requested':'b-mandatory'}">${d.dtype}</span>
        <b class="small">${esc(d.debt_id)}</b></td>
    <td><b>${esc(d.title)}</b>${withService&&d.service_code?`<div class="small mut">${esc(d.service_code)} · ${esc(d.service_name||'')}</div>`:''}</td>
    <td><span class="badge ${RISK_BADGE[d.risk]||'b-draft'}">${esc(d.risk)}</span><div class="small mut">Ds ${d.probability}×${d.damage}=${d.ds}</div></td>
    <td><span class="badge ${PRIO_BADGE[d.priority]||'b-draft'}">${d.priority}</span></td>
    <td><span class="badge ${DEBT_STATUS_BADGE[d.status]||'b-draft'}">${DEBT_STATUS_RU[d.status]||esc(d.status)}</span></td>
    <td class="small">${esc(d.owner||'—')}</td>
    <td><button class="sec" onclick="debtOpen(${d.id})">Карточка</button></td></tr>`;
}
function tabDebt(s){
  const canAdd = ['admin','domain_expert','team_lead'].includes(S.user.role);
  $('#tabbody').innerHTML = `<div class="card">
    <h2 style="margin-top:0">Реестр технического долга — ${esc(s.code)}</h2>
    <p class="small mut">Каждая запись — осознанно зафиксированное отклонение от целевой архитектуры или
    инженерного стандарта: причина, последствия, владелец, стоимость, риск, план погашения
    (стандарт DA: «Реестр технического долга»). ID: <b>{AD|TD}-{ГГГГ}-{ММ}-{NNN}</b>, неизменяем.</p>
    ${s.debts.length?`<table><tr><th>ID</th><th>Долг</th><th>Риск</th><th>Приоритет</th><th>Статус</th><th>Владелец</th><th></th></tr>
      ${s.debts.map(d=>debtRow({...d, service_code:s.code}, false)).join('')}</table>`
      :'<p class="mut">Долг не зарегистрирован.</p>'}
    ${canAdd?'<div class="btnrow" style="margin-top:12px"><button onclick="formDebt('+s.id+')">+ Зарегистрировать долг</button></div>':''}
  </div>`;
}
async function viewDebts(){
  const [all, svcs] = await Promise.all([api('/debts'), api('/services')]);
  const kpi = t => all.filter(d=>t(d)).length;
  $('#view').innerHTML = `
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div><h1>Реестр технического долга</h1>
    <p class="mut">Архитектурный (AD) и технический (TD) долг · приоритет P0–P3 · риск = вероятность × ущерб
    (Confluence DA: pageId=915912594, pageId=918365931)</p></div>
    ${['admin','domain_expert','team_lead'].includes(S.user.role)?'<button onclick="formDebt(null)">+ Зарегистрировать долг</button>':''}
  </div>
  <div class="grid g4" style="margin:14px 0">
    ${[['P0', kpi(d=>d.priority==='P0')], ['P1', kpi(d=>d.priority==='P1')],
       ['AD', kpi(d=>d.dtype==='AD')], ['В работе', kpi(d=>d.status==='in_progress')]]
      .map(([t,n])=>`<div class="card vio" style="text-align:center"><div style="font-size:28px;font-weight:700">${n}</div><div class="small mut">${t}</div></div>`).join('')}
  </div>
  <div class="card"><table><tr><th>ID</th><th>Долг</th><th>Риск</th><th>Приоритет</th><th>Статус</th><th>Владелец</th><th></th></tr>
  ${all.map(d=>debtRow(d, true)).join('')||'<tr><td colspan="7" class="mut">Реестр пуст</td></tr>'}
  </table></div>`;
  window._SVC_LIST = svcs;
}
function formDebt(serviceId){
  const st = S.standard;
  openModal('Регистрация долга', `
    <div class="grid g2"><div><label>Тип долга</label><select id="d-type">
        <option value="TD">TD — технический</option><option value="AD">AD — архитектурный</option></select></div>
      <div><label>Сервис</label><select id="d-svc"><option value="">— без привязки (домен) —</option>
        ${(window._SVC_LIST||[]).map(s=>`<option value="${s.id}" ${s.id===serviceId?'selected':''}>${esc(s.code)}</option>`).join('')}</select></div></div>
    <label>Название</label><input id="d-title" placeholder="Краткое понятное описание">
    <label>Описание: что не соответствует целевому состоянию</label><textarea class="sm" id="d-desc"></textarea>
    <div class="grid g2"><div><label>Причина возникновения</label><textarea class="sm" id="d-cause"></textarea></div>
      <div><label>Архитектурное решение, породившее долг</label><textarea class="sm" id="d-adec"></textarea></div></div>
    <div class="grid g2"><div><label>Целевое состояние</label><textarea class="sm" id="d-target"></textarea></div>
      <div><label>Последствия</label><textarea class="sm" id="d-cons"></textarea></div></div>
    <div class="grid g3"><div><label>Риск</label><select id="d-risk">${st.debt_risks.map(r=>`<option ${r==='Medium'?'selected':''}>${r}</option>`).join('')}</select></div>
      <div><label>Вероятность 1–5</label><input id="d-prob" type="number" min="1" max="5" value="3"></div>
      <div><label>Ущерб 1–5</label><input id="d-dmg" type="number" min="1" max="5" value="3"></div></div>
    <div class="grid g2"><div><label>Приоритет</label><select id="d-prio">${st.debt_priorities.map(p=>`<option ${p==='P2'?'selected':''}>${p}</option>`).join('')}</select></div>
      <div><label>Владелец</label><input id="d-owner" value="${esc(S.user.username)}"></div></div>
    <div class="grid g2"><div><label>Стоимость обслуживания</label><input id="d-mcost" placeholder="часы / деньги"></div>
      <div><label>Стоимость погашения</label><input id="d-rcost"></div></div>
    <div class="grid g2"><div><label>Срок пересмотра</label><input id="d-review" type="date"></div>
      <div><label>Зависимости</label><input id="d-dep"></div></div>
    <label>План погашения (epic / действия)</label><textarea class="sm" id="d-plan"></textarea>
    <div class="btnrow"><button onclick="createDebt()">Зарегистрировать</button></div>`);
}
async function createDebt(){
  try{
    const r = await api('/debts', {method:'POST', body: JSON.stringify({
      dtype:$('#d-type').value, service_id:$('#d-svc').value?+$('#d-svc').value:null,
      title:$('#d-title').value, description:$('#d-desc').value,
      cause:$('#d-cause').value, arch_decision:$('#d-adec').value,
      target_state:$('#d-target').value, consequences:$('#d-cons').value,
      risk:$('#d-risk').value, probability:+$('#d-prob').value, damage:+$('#d-dmg').value,
      priority:$('#d-prio').value, owner:$('#d-owner').value,
      maintenance_cost:$('#d-mcost').value, repayment_cost:$('#d-rcost').value,
      review_date:$('#d-review').value, dependencies:$('#d-dep').value,
      repayment_plan:$('#d-plan').value})});
    closeModal(); toast(`Долг зарегистрирован: <b>${esc(r.debt_id)}</b> (риск Ds ${r.ds})`); render();
  }catch(e){ toast(esc(e.message), true); }
}
async function debtOpen(id){
  const d = (await api('/debts')).find(x=>x.id===id);
  const st = S.standard;
  openModal(`${d.dtype} · ${esc(d.debt_id)}`, `
    <h2 style="margin:0 0 4px">${esc(d.title)}</h2>
    <div class="btnrow" style="margin-bottom:10px">
      <span class="badge ${PRIO_BADGE[d.priority]}">${d.priority}</span>
      <span class="badge ${RISK_BADGE[d.risk]}">${esc(d.risk)} · Ds ${d.ds}</span>
      <span class="badge ${DEBT_STATUS_BADGE[d.status]}">${DEBT_STATUS_RU[d.status]}</span>
      ${d.service_code?`<span class="chip"><b>${esc(d.service_code)}</b></span>`:''}
    </div>
    ${[['Описание / расхождение', d.description], ['Причина возникновения', d.cause],
       ['Архитектурное решение', d.arch_decision], ['Целевое состояние', d.target_state],
       ['Последствия', d.consequences], ['Бизнес-влияние', d.business_impact],
       ['Техническое влияние', d.tech_impact], ['Стоимость обслуживания', d.maintenance_cost],
       ['Стоимость погашения', d.repayment_cost], ['План погашения', d.repayment_plan],
       ['Зависимости', d.dependencies]]
      .filter(([,v])=>v).map(([k,v])=>`<p class="small" style="margin:4px 0"><b>${k}:</b> ${esc(v)}</p>`).join('')}
    <p class="small mut" style="margin:8px 0 0">Владелец: <b>${esc(d.owner||'—')}</b>
      · срок пересмотра: ${esc(d.review_date||'—')}</p>
    <div class="btnrow" style="margin-top:12px"><label style="margin:0 6px 0 0">Статус:</label>
      <select id="d-newstatus">${st.debt_statuses.map(s=>`<option value="${s}" ${s===d.status?'selected':''}>${DEBT_STATUS_RU[s]}</option>`).join('')}</select>
      <button class="sec" onclick="debtStatus(${d.id})">Сменить статус</button></div>`);
}
async function debtStatus(id){
  try{
    await api(`/debts/${id}/status`, {method:'POST', body: JSON.stringify({status:$('#d-newstatus').value})});
    closeModal(); toast('Статус долга обновлён'); render();
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- ролевая модель (Доступ) ---------- */
const KIND_BADGE = {domain:'b-desired', committee:'b-mandatory', product:'b-in_review', security:'b-changes_requested'};
const KIND_TITLE = {domain:'домен', committee:'комитет', product:'продукт', security:'security'};
async function viewAccess(){
  let d; try{ d = await api('/admin/access'); }catch(e){
    $('#view').innerHTML = `<h1>Доступ</h1><div class="card"><p class="mut">${esc(e.message)}</p></div>`; return;
  }
  const isAdmin = S.user.role === 'admin';
  $('#view').innerHTML = `
  <h1>Ролевая модель и группы доступа</h1>
  <p class="mut">Роль = что умеет человек · Группа = к чему применимо (домен / комитет / продукт / security).
  Доступ к сервису: role domain_expert/admin ИЛИ product-группа с грантом ИЛИ owner/architect в карточке.</p>
  <h2>Пользователи</h2>
  <div class="card"><table><tr><th>Логин</th><th>Имя</th><th>Роль</th><th>Группы</th></tr>
  ${d.users.map(u=>`<tr>
    <td><b>${esc(u.username)}</b>${u.username===S.user.username?' <span class="small mut">(вы)</span>':''}</td>
    <td>${esc(u.display_name)}</td>
    <td>${isAdmin?`<select class="role-sel" data-u="${esc(u.username)}" style="width:150px">
        ${d.roles.map(r=>`<option ${r===u.role?'selected':''}>${r}</option>`).join('')}</select>`
        :`<span class="badge b-draft">${esc(u.role)}</span>`}</td>
    <td>${u.groups.map(g=>`<span class="chip">${esc(g)}</span>`).join('')||'<span class="mut">—</span>'}</td>
  </tr>`).join('')}
  </table></div>
  <h2>Группы доступа</h2>
  <div class="grid g2">
  ${d.groups.map(g=>`<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <b>${esc(g.name)}</b> <span class="badge ${KIND_BADGE[g.kind]||'b-draft'}">${KIND_TITLE[g.kind]||esc(g.kind)}</span>
    </div>
    <div class="small mut" style="margin:4px 0 8px">${esc(g.description||'')}</div>
    <div class="small" style="margin-bottom:2px"><b>Участники:</b></div>
    <div>${g.members.map(m=>`<span class="chip">${esc(m)}${isAdmin?` <a class="lnk" onclick="grpRemove('${g.id}','${esc(m)}')" style="cursor:pointer">×</a>`:''}</span>`).join('')||'<span class="mut small">нет участников</span>'}</div>
    ${isAdmin?`<div class="btnrow" style="margin-top:6px">
      <select id="gm-${g.id}" style="width:auto;flex:1">${d.users.filter(u=>!g.members.includes(u.username)).map(u=>`<option>${esc(u.username)}</option>`).join('')||'<option>— все добавлены</option>'}</select>
      <button class="sec" onclick="grpAdd(${g.id})">+ участник</button></div>`:''}
    <div class="small" style="margin:10px 0 2px"><b>Доступ к сервисам:</b></div>
    <div>${g.services.map(s=>`<span class="chip"><b>${esc(s.code)}</b> ${esc(s.name)}${isAdmin?` <a class="lnk" onclick="svcRevoke(${g.id},${s.id})" style="cursor:pointer">×</a>`:''}</span>`).join('')||'<span class="mut small">нет грантов</span>'}</div>
    ${isAdmin&&g.kind==='product'?`<div class="btnrow" style="margin-top:6px">
      <select id="gs-${g.id}" style="width:auto;flex:1">${SVC_CACHE.filter(s=>!g.services.some(x=>x.id===s.id)).map(s=>`<option value="${s.id}">${esc(s.code)} · ${esc(s.name)}</option>`).join('')||'<option>— все грантованы</option>'}</select>
      <button class="sec" onclick="svcGrant(${g.id})">+ сервис</button></div>`:''}
  </div>`).join('')}
  </div>
  ${isAdmin?`<div class="card" style="margin-top:14px"><div class="btnrow" style="margin:0">
    <input id="ng-name" placeholder="Название группы" style="width:220px">
    <select id="ng-kind" style="width:130px">${d.kinds.map(k=>`<option value="${k}">${KIND_TITLE[k]}</option>`).join('')}</select>
    <input id="ng-desc" placeholder="Описание" style="flex:1">
    <button onclick="grpCreate()">+ Группа</button></div></div>`:''}`;
  // обработчик смены роли
  document.querySelectorAll('.role-sel').forEach(sel => sel.addEventListener('change', async () => {
    try{ await api(`/admin/users/${sel.dataset.u}/role`, {method:'PATCH', body: JSON.stringify({role:sel.value})});
      toast(`Роль ${esc(sel.dataset.u)} → <b>${sel.value}</b>`); }catch(e){ toast(esc(e.message), true); }
  }));
}
let SVC_CACHE = [];
async function viewAccessWithServices(){ SVC_CACHE = await api('/services'); return viewAccess(); }
async function grpAdd(gid){ try{ await api(`/admin/groups/${gid}/members`, {method:'POST', body: JSON.stringify({username:$(`#gm-${gid}`).value})}); render(); }catch(e){ toast(esc(e.message), true);} }
async function grpRemove(gid, username){ try{ await api(`/admin/groups/${gid}/members/remove`, {method:'POST', body: JSON.stringify({username})}); render(); }catch(e){ toast(esc(e.message), true);} }
async function svcGrant(gid){ try{ await api(`/admin/groups/${gid}/services`, {method:'POST', body: JSON.stringify({service_id:+$(`#gs-${gid}`).value})}); render(); }catch(e){ toast(esc(e.message), true);} }
async function svcRevoke(gid, sid){ try{ await api(`/admin/groups/${gid}/services/remove`, {method:'POST', body: JSON.stringify({service_id:sid})}); render(); }catch(e){ toast(esc(e.message), true);} }
async function grpCreate(){
  try{
    await api('/admin/groups', {method:'POST', body: JSON.stringify({
      name:$('#ng-name').value, kind:$('#ng-kind').value, description:$('#ng-desc').value})});
    toast('Группа создана'); render();
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- admin / integrations ---------- */
async function viewAdmin(){
  const can = ['domain_expert','admin'].includes(S.user.role);
  $('#view').innerHTML = `<h1>Интеграции</h1>
  <div class="grid g2" style="margin-top:14px">
    <div class="card vio"><h2 style="margin-top:0">Backstage Catalog (BR-21)</h2>
      <p class="small mut">Импорт сервисов из catalog-info.yaml (GitLab autodiscovery). MVP — mock-коннектор с dry-run.</p>
      <div class="btnrow"><button class="cya" onclick="importBackstage(true)" ${can?'':'disabled'}>Dry-run импорт</button>
      <button onclick="importBackstage(false)" ${can?'':'disabled'}>Импортировать</button></div>
      <div id="imp-res"></div></div>
    <div class="card"><h2 style="margin-top:0">CMDB (BR-20/22)</h2>
      <p class="small mut">DataGerry — REST API + ObjectTypes (контур кибербезопасности). Матрица владения полями:
      ИС → архитектурные атрибуты, CMDB → операционные (CI, health, алерты). Подключение — после финализации выбора CMDB.</p>
      <span class="badge b-draft">запланировано</span></div>
    <div class="card"><h2 style="margin-top:0">AI-Buddy (BR-27)</h2>
      <p class="small mut">Все AI-сценарии через корпоративную LLM-платформу. MVP работает на mock-провайдере
      (детерминированные эвристики) — контракт API уже финальный.</p>
      <span class="badge b-Ch">mock → production</span></div>
    <div class="card"><h2 style="margin-top:0">Журнал аудита</h2>
      <p class="small mut">Все действия фиксируются (BR-33). Просмотр: expert/admin.</p>
      <div class="btnrow">${can?'<button class="sec" onclick="showAudit()">Открыть журнал</button>':'<span class="mut small">нужна роль domain_expert+</span>'}</div>
      <div id="audit-res"></div></div>
  </div>`;
}
async function importBackstage(dry){
  try{
    const r = await api('/integrations/backstage/import', {method:'POST', body: JSON.stringify({dry_run:dry})});
    $('#imp-res').innerHTML = `<div style="margin-top:12px;border-top:1px solid var(--line);padding-top:10px">
      ${r.created.map(c=>`<div class="chip">${dry?'DRY-RUN ·':''} <b>${esc(c.code)}</b> ${esc(c.name||'')}</div>`).join('')||'<span class="mut small">новых нет</span>'}
      ${r.skipped.map(c=>`<div class="chip">${esc(c.code)} — ${esc(c.reason)}</div>`).join('')}
    </div>`;
    if(!dry) toast(`Импортировано сервисов: ${r.created.length}`);
  }catch(e){ toast(esc(e.message), true); }
}
async function showAudit(){
  try{
    const rows = await api('/audit');
    $('#audit-res').innerHTML = `<table style="margin-top:10px"><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Объект</th></tr>
    ${rows.slice(0,12).map(a=>`<tr><td class="small mut">${new Date(a.ts*1000).toLocaleString('ru')}</td><td>${esc(a.user)}</td><td class="small">${esc(a.action)}</td><td class="small mut">${esc(a.entity)}</td></tr>`).join('')}</table>`;
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- modal ---------- */
function openModal(title, html){
  let m = $('#modal');
  if(m) m.remove();
  m = document.createElement('div'); m.id='modal';
  m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:40';
  m.innerHTML = `<div class="card vio" style="width:min(560px,92vw);max-height:86vh;overflow:auto"><h2>${esc(title)}</h2>${html}</div>`;
  m.addEventListener('click', e=>{ if(e.target===m) m.remove(); });
  document.body.append(m);
}
const closeModal = () => $('#modal')?.remove();
window.addEventListener('hashchange', render);
// восстановление сессии по сохранённому токену
(async () => {
  if(localStorage.token){
    try{ S.user = await api('/me'); }catch{ delete localStorage.token; }
  }
  render();
})();
