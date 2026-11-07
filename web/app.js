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
  const nav = {'#/':'Дашборд','#/services':'Сервисы','#/assistant':'Ассистент','#/debts':'Техдолг','#/components':'Компоненты','#/access':'Доступ','#/admin':'Интеграции'};
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
route(/^#\/assistant$/, viewAssistant);
route(/^#\/access$/, async () => { SVC_CACHE = await api('/services'); return viewAccess(); });

const FIT_DOT = f => !f ? '<span class="mut" title="Фитнес-проверки не запускались">○ нет</span>'
  : f.failed ? `<span style="color:var(--bad)" title="${f.failed} красных">● ${f.failed} красн.</span>`
  : f.warned ? `<span style="color:var(--warn)" title="${f.warned} предупреждений">● ${f.warned} предупр.</span>`
  : '<span style="color:var(--ok)" title="Все проверки зелёные">● ok</span>';
const fmtTs = t => t ? new Date(t * 1000).toLocaleString('ru-RU', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}) : '';

async function viewDash(){
  const d = await api('/dashboard');
  const st = s => d.by_review_status.find(x=>x.review_status===s)?.n||0;
  const dp = p => d.debt_by_priority.find(x=>x.priority===p)?.n||0;
  const debtOpen = dp('P0') + dp('P1') + dp('P2') + dp('P3');
  const covCard = (t, list, link) => `<div class="card"><div class="mut">${t}</div>
    <div class="kpi" style="color:${list.length ? 'var(--warn)' : 'var(--ok)'}">${list.length}</div>
    <div class="small mut">${list.length ? esc(list.map(x=>x.code).join(', ')) : 'покрыто полностью'}${link ? ` · <a class="lnk" href="${link}">реестр</a>` : ''}</div></div>`;
  $('#view').innerHTML = `
  <h1>Дашборд соответствия стандарту</h1>
  <p class="mut"><a class="lnk" href="${d.standard_ref}" target="_blank">Общий архитектурный стандарт (Architecture Definition Set) ↗</a></p>
  <div class="grid g4" style="margin:18px 0">
    <div class="card vio"><div class="mut">Сервисов в реестре</div><div class="kpi">${d.total_services}</div></div>
    <div class="card"><div class="mut">На ревью / согласовано</div><div class="kpi">${st('in_review')} <span class="mut" style="font-size:16px">/</span> <span style="color:var(--ok)">${st('approved')}</span></div></div>
    <div class="card cya"><div class="mut">Нужны изменения</div><div class="kpi" style="color:var(--warn)">${st('changes_requested')}</div></div>
    <div class="card"><div class="mut">Открытый техдолг P0+P1</div><div class="kpi" style="color:${dp('P0')+dp('P1') ? 'var(--bad)' : 'var(--ok)'}">${dp('P0')+dp('P1')}</div><div class="small mut">всего открытых: ${debtOpen}</div></div>
  </div>
  ${(d.my_tasks.pending_reviews.length || d.my_tasks.blockers.length) ? `
  <h2>Мои задачи</h2>
  <div class="grid g2" style="margin:14px 0">
    ${d.my_tasks.pending_reviews.length ? `<div class="card"><div class="mut" style="margin-bottom:8px">Ждут моего решения по ревью</div>
      ${d.my_tasks.pending_reviews.map(r=>`<div style="margin:6px 0"><a class="lnk" href="#/service/${r.service_id}"><b>${esc(r.code)}</b> ${esc(r.name)}</a>
        <span class="small mut">· запросил ${esc(r.requested_by)} ${fmtTs(r.requested_at)}</span></div>`).join('')}</div>` : ''}
    ${d.my_tasks.blockers.length ? `<div class="card"><div class="mut" style="margin-bottom:8px">Блокеры в моих сервисах</div>
      ${d.my_tasks.blockers.map(b=>`<div style="margin:6px 0"><a class="lnk" href="#/service/${b.id}"><b>${esc(b.code)}</b> ${esc(b.name)}</a>
        <span class="small mut">· ${b.why.map(esc).join(' · ')}</span></div>`).join('')}</div>` : ''}
  </div>` : `<p class="mut" style="margin:14px 0">На вас ничего не висит — ожидающих ревью и блокеров в ваших сервисах нет.</p>`}
  <h2>Готовность к ревью</h2>
  <div class="card"><table><tr><th>Сервис</th><th>Обязательные артефакты</th><th>Self-check</th><th>Фитнес</th><th>Техдолг</th><th>Ревью</th><th>Следующий шаг</th></tr>
  ${d.readiness.map(r=>{
    const fill = r.mandatory_total - r.mandatory_missing.length;
    return `<tr><td><a class="lnk" href="#/service/${r.id}"><b>${esc(r.name)}</b> <span class="mut">${esc(r.code)}</span></a></td>
    <td><b>${fill}/${r.mandatory_total}</b>${r.mandatory_missing.length ? `<div class="small mut">нет: ${esc(r.mandatory_missing.map(m=>m.title).join(', '))}</div>` : '<div class="small" style="color:var(--ok)">все обязательные заполнены</div>'}</td>
    <td>${r.self_check == null ? '<span class="mut">не проводился</span>' : `<div class="bar" style="width:110px"><i style="width:${r.self_check}%"></i></div><span class="small mut">${r.self_check}%</span>`}</td>
    <td>${FIT_DOT(r.fitness)}</td>
    <td>${r.debts_open ? `<span ${r.debts_p0 ? 'style="color:var(--bad);font-weight:600"' : ''}>${r.debts_open}</span> <span class="mut small">откр.</span>` : '<span class="mut">—</span>'}</td>
    <td>${statusB(r.review_status)}</td>
    <td class="small">${esc(r.hint)}</td></tr>`;
  }).join('')}
  </table></div>
  <h2>Риски и техдолг</h2>
  <div class="grid g4" style="margin:14px 0">
    ${['P0','P1','P2','P3'].map(p=>`<div class="card"><div class="mut">Приоритет ${p}</div>
      <div class="kpi" style="color:${p==='P0'&&dp(p) ? 'var(--bad)' : dp(p) ? 'var(--txt)' : 'var(--ok)'}">${dp(p)}</div></div>`).join('')}
  </div>
  ${d.debt_top.length ? `<div class="card"><table><tr><th>ID</th><th>Пункт долга</th><th>Сервис</th><th>Приоритет</th><th>Риск</th><th>Статус</th></tr>
  ${d.debt_top.map(t=>`<tr><td class="small mut">${esc(t.debt_id)}</td><td>${esc(t.title)}</td>
    <td>${t.service_id ? `<a class="lnk" href="#/service/${t.service_id}">${esc(t.code)}</a>` : '<span class="mut">—</span>'}</td>
    <td><b>${esc(t.priority)}</b></td><td>${esc(t.risk)}</td><td>${statusB(t.status)}</td></tr>`).join('')}
  </table><p class="small mut" style="margin:10px 0 0"><a class="lnk" href="#/debts">весь техдолг →</a></p></div>`
  : '<p class="mut">Открытых пунктов P0/P1 нет.</p>'}
  <h2>Покрытие процессом</h2>
  <div class="grid g3" style="margin:14px 0">
    ${covCard('Сервисов без требований (ФТ/НФТ)', d.coverage.no_requirements, '#/services')}
    ${covCard('Сервисов без C4-модели', d.coverage.no_c4, '#/services')}
    ${covCard('Сервисов без self-check', d.coverage.no_checklist, '#/services')}
  </div>
  ${d.activity.length ? `<h2>Последние события</h2>
  <div class="card"><table class="small">${d.activity.slice(0,8).map(a=>`<tr><td class="mut" style="white-space:nowrap">${fmtTs(a.ts)}</td><td>${esc(a.user)}</td>
    <td>${esc(a.action)}</td><td class="mut">${esc(a.entity)}${a.detail ? ' · ' + esc(String(a.detail)).slice(0,60) : ''}</td></tr>`).join('')}</table></div>` : ''}
  <h2>Переиспользование компонентов</h2>
  <div class="card"><table><tr><th>Компонент</th><th>Статус</th><th>Используют сервисов</th></tr>
  ${d.component_usage.map(c=>`<tr><td>${esc(c.name)}</td><td>${statusB(c.status)}</td><td><b>${c.used_by}</b>${c.used_by ? '' : ' <span class="small mut">— нет потребителей</span>'}</td></tr>`).join('')}
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
  openModal('Service Factory — новый сервис (BR-45…47)', `
    <p class="small mut">Генерирует стартовый архитектурный пакет: 7 артефактов по шаблонам стандарта,
    пустой self-check и подключение всех approved-компонентов каталога (compliance by construction).</p>
    <div class="grid g2"><div><label>Код (напр. MPR)</label><input id="f-code"></div>
    <div><label>Название</label><input id="f-name"></div></div>
    <div class="grid g2"><div><label>Тип проекта</label><select id="f-pt">${opts}</select></div>
    <div><label>Домен</label><input id="f-domain"></div></div>
    <div class="grid g2"><div><label>Владелец</label><input id="f-owner" value="${esc(S.user.username)}"></div>
    <div><label>Архитектор</label><input id="f-arch" value="${esc(S.user.username)}"></div></div>
    <div class="btnrow"><button onclick="createService()">Сгенерировать пакет</button></div>`);
}
async function createService(){
  try{
    const r = await api('/factory/scaffold', {method:'POST', body: JSON.stringify({
      code:$('#f-code').value, name:$('#f-name').value, project_type:$('#f-pt').value,
      domain:$('#f-domain').value, owner:$('#f-owner').value, architect:$('#f-arch').value})});
    closeModal();
    openModal(`Сервис ${esc(r.code)} создан`, `
      <p class="small mut">Сгенерировано: ${r.artifacts} артефактов по шаблонам стандарта ·
      подключено компонентов: ${r.components_attached.length}
      (${esc(r.components_attached.join(', ')||'—')}).</p>
      <h2 style="margin:10px 0 4px">Next steps</h2>
      <ol class="small">${r.next_steps.map(s=>`<li style="margin:4px 0">${esc(s)}</li>`).join('')}</ol>
      <div class="btnrow"><button onclick="closeModal();location.hash='#/service/${r.id}'">Открыть сервис</button></div>`);
    toast(`Пакет для ${esc(r.code)} сгенерирован Service Factory`);
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- service detail ---------- */
const TABS = [['card','Карточка'],['artifacts','Артефакты (7)'],['diagrams','Диаграммы'],['check','Self-check'],['review','Ревью'],['components','Компоненты']]; // базовый список (полный собирается в viewService)
let SERVICE = null;
async function viewService(id, tab='card'){
  const s = await api('/services/'+id); SERVICE = s;
  const active = tab||'card';
  const tabs = [['card','Карточка'],
    ['reqs', 'Требования' + (s.requirements?.length ? ` (${s.requirements.length})` : '')],
    ['design', 'Проектирование'],
    ['artifacts','Артефакты (7)'],['diagrams','Диаграммы'],['check','Self-check'],['review','Ревью'],['components','Компоненты'],
    ['debt', 'Техдолг'+(s.debts.length?` (${s.debts.length})`:'')],
    ['fitness', 'Fitness'], ['nfr', 'NFR']];
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
  ({card:tabCard, reqs:tabReqs, design:tabDesign, artifacts:tabArtifacts, diagrams:tabDiagrams, check:tabCheck, review:tabReview,
    components:tabComponents, debt:tabDebt, fitness:tabFitness, nfr:tabNfr}[active])(s);
}

/* ---------- диаграммы (Mermaid) ---------- */
const _deb = {};
function liveDiagram(el){
  const id = el.id, kind = id.replace(/^d-/,'dv-');
  clearTimeout(_deb[id]);
  _deb[id] = setTimeout(()=>renderDiag(document.getElementById(kind), el.value), 700);
}
// В diagram_code может лежать несколько диаграмм подряд (напр. C4Context + C4Container).
// Разбиваем на отдельные блоки по заголовкам типов — Mermaid принимает один исходник за раз.
const DIAG_HEAD_RE = /^(C4Context|C4Container|C4Deployment|C4Component|C4Dynamic|erDiagram|flowchart|sequenceDiagram|classDiagram|stateDiagram|graph|gantt|pie|mindmap|timeline|gitGraph|journey)\b/;
const DIAG_TITLES = {
  C4Context:'C4 L1 — Контекст', C4Container:'C4 L2 — Контейнеры',
  C4Deployment:'C4 — Deployment', C4Component:'C4 L3 — Компоненты', C4Dynamic:'C4 — Dynamic',
  erDiagram:'ER — модель данных', flowchart:'Flowchart', sequenceDiagram:'Sequence',
  classDiagram:'Class diagram', stateDiagram:'State diagram',
};
function splitDiagrams(code){
  const blocks = []; let cur = null;
  for(const ln of code.split('\n')){
    const m = ln.trim().match(DIAG_HEAD_RE);
    if(m){
      if(cur) blocks.push(cur);
      cur = {type: m[1], code: ln};
    } else if(cur){
      cur.code += '\n' + ln;
    }
  }
  if(cur) blocks.push(cur);
  return blocks.filter(b=>b.code.trim());
}
async function renderDiag(el, code){
  if(!el) return;
  if(!window.mermaid){ el.innerHTML = '<span class="mut small">Mermaid не загрузился</span>'; return; }
  if(!code || !code.trim()){
    el.innerHTML = '<div class="empty">Исходник диаграммы не задан.<br>Стандарт требует хранить исходники (dsl/json/mermaid) — вставьте Mermaid-код слева.</div>';
    return;
  }
  const blocks = splitDiagrams(code);
  if(!blocks.length){
    el.innerHTML = '<div class="empty">Исходник диаграммы не задан.</div>';
    return;
  }
  const multi = blocks.length > 1;
  el.classList.toggle('diag-stack', multi);
  const parts = []; let bad = false;
  for(const b of blocks){
    try{
      const {svg} = await mermaid.render('m'+Math.random().toString(36).slice(2), b.code.trim());
      const cap = multi ? `<div class="small mut" style="margin-bottom:6px">${esc(DIAG_TITLES[b.type] || b.type)}</div>` : '';
      parts.push(`<div style="flex:0 0 auto;max-width:100%;margin-bottom:14px">${cap}${svg}</div>`);
    }catch(e){
      bad = true;
      parts.push(`<div class="small" style="color:var(--bad)">⚠ Ошибка синтаксиса Mermaid${multi ? ` (${DIAG_TITLES[b.type] || b.type})` : ''}: ${esc(String(e.message||e)).slice(0,220)}</div>`);
    }
  }
  el.classList.toggle('diag-err', bad);
  el.innerHTML = parts.join('');
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
    <button class="cya" onclick="exportCatalog(${s.id})">Экспорт catalog-info.yaml (BR-21)</button>
    <button class="sec" onclick="askAssistantAbout(${s.id})">▲ Спросить ассистента</button></div></div>
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
  const mandatoryCount = s.mandatory_artifacts.filter(k => {
    const c = byKind[k]; return !c || !(c.content_md||'').trim();
  }).length;
  $('#tabbody').innerHTML = `
  <div class="card" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
    <div><b>Артефакты сервиса</b>
      <span class="small mut">· обязательных для типа: ${s.mandatory_artifacts.length}${mandatoryCount?`, без контента: <b style="color:var(--bad)">${mandatoryCount}</b>`:''}</span>
    </div>
    <button class="cya" onclick="scaffoldArtifacts(${s.id}, this)">⚡ Сгенерировать скелеты обязательных артефактов</button>
  </div>` + arts.map(a=>{
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
      <button class="sec" onclick="aiDraft(${s.id},'${a.kind}',this)">✨ AI-черновик</button>
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
async function aiDraft(sid, kind, btn){
  const old = btn ? btn.textContent : '';
  if(btn){ btn.disabled = true; btn.textContent = '✨ Генерирую…'; }
  try{
    const r = await api('/ai/draft', {method:'POST', body: JSON.stringify({
      service_id:sid, kind, model: chatModelSel()})});
    $(`#a-${kind}`).value = r.content_md;
    toast(r.provider === 'ai-buddy'
      ? `AI-черновик (${esc(r.model||'AI-Buddy')}) вставлен — <b>требует подтверждения автора</b> (BR-28/33)`
      : esc(r.note || 'Черновик вставлен — требует подтверждения автора (BR-28/33)'));
  }catch(e){ toast(esc(e.message), true); }
  if(btn){ btn.disabled = false; btn.textContent = old; }
}
async function scaffoldArtifacts(sid, btn){
  btn.disabled = true; btn.textContent = '⏳ Генерирую…';
  try{
    const r = await api(`/services/${sid}/artifacts/scaffold`, {method:'POST'});
    if(r.created.length){
      toast(`Созданы скелеты обязательных артефактов: <b>${r.created.map(esc).join(', ')}</b> — заполните заготовки`);
      viewService(sid, 'artifacts');
      return;   // view перерисован — кнопка уже новая
    }
    toast('Все обязательные артефакты уже заполнены или имеют скелеты');
  }catch(e){ toast(esc(e.message), true); }
  btn.disabled = false; btn.textContent = '⚡ Сгенерировать скелеты обязательных артефактов';
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

/* ---------- MVP2: fitness functions (BR-41…44) ---------- */
const VERDICT_BADGE = {pass:'b-approved', fail:'b-changes_requested', warn:'b-in_review', unknown:'b-draft', breach:'b-changes_requested', ok:'b-approved', partial:'b-in_review'};
function tabFitness(s){
  const last = s.fitness_last;
  $('#tabbody').innerHTML = `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2 style="margin-top:0">Fitness functions — автопроверка правил архитектуры (BR-41…42)</h2>
      <button onclick="runFitness(${s.id})">▶ Прогнать проверки</button></div>
    <p class="small mut">Правила — проверяемые утверждения стандарта (pageId=894079737): исходники диаграмм,
    3+ эндпоинта API, NFR в цифрах, ADR-001…005, docker compose. blocker проваливает прогон, warning — нет.</p>
    ${last?`<div class="btnrow" style="margin:10px 0">
      <span class="badge ${VERDICT_BADGE.pass}">✔ ${last.passed}</span>
      <span class="badge ${VERDICT_BADGE.fail}">✖ ${last.failed}</span>
      <span class="badge ${VERDICT_BADGE.warn}">⚠ ${last.warned}</span>
      <span class="small mut">последний прогон: ${new Date(last.created_at*1000).toLocaleString('ru')} · ${esc(last.created_by)}</span></div>`
      :'<p class="mut">Прогонов ещё не было.</p>'}
    <div id="fit-res"></div>
    <div class="btnrow" style="margin-top:14px"><button class="sec" onclick="showCi(${s.id})">⬇ CI-пак (gitlab-ci + python)</button></div>
    <p class="small mut">BR-43/44: тот же набор правил экспортируется в CI — проверка в репозитории до ревью.</p>
  </div>`;
}
async function runFitness(sid){
  try{
    const r = await api(`/services/${sid}/fitness`, {method:'POST'});
    toast(`Прогон: ✔ ${r.passed} · ✖ ${r.failed} · ⚠ ${r.warned}`);
    render();
  }catch(e){ toast(esc(e.message), true); }
}
async function showCi(sid){
  try{
    const r = await fetch(`/api/services/${sid}/fitness/ci.txt`, {headers:{'X-Token':localStorage.token}});
    const text = await r.text();
    openModal('CI-пак fitness-проверок', `
      <p class="small mut">1) <code>fitness_check.py</code> — в репозиторий сервиса; 2) job — в <code>.gitlab-ci.yml</code>.
      Правила синхронизированы с DeepArch: изменение стандарта подтягивается перегенерацией.</p>
      <pre class="sm" style="max-height:46vh;overflow:auto;background:var(--bg2,#f5f6fa);padding:10px;border-radius:8px;white-space:pre-wrap">${esc(text)}</pre>
      <div class="btnrow"><button onclick="downloadCi(${sid})">Скачать файлом</button></div>`);
  }catch(e){ toast(esc(e.message), true); }
}
async function downloadCi(sid){
  const r = await fetch(`/api/services/${sid}/fitness/ci.txt`, {headers:{'X-Token':localStorage.token}});
  const blob = new Blob([await r.text()], {type:'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `fitness_${SERVICE.code.toLowerCase()}.txt`; a.click();
}

/* ---------- MVP2: NFR-валидация (BR-51…53) ---------- */
const METRIC_RU = {rps:'RPS (пиковый)', p95_ms:'Время ответа p95, ms', sla_pct:'SLA, %',
                   rto_h:'RTO, ч', rpo_min:'RPO, мин'};
function tabNfr(s){
  const nfr = s.nfr || {metrics:[]};
  $('#tabbody').innerHTML = `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2 style="margin-top:0">NFR-валидация: цель vs факт (BR-51…53)</h2>
      <button onclick="nfrExtract(${s.id})">⇣ Извлечь цели из артефакта NFR</button></div>
    <p class="small mut">Цели (RPS, p95, SLA, RTO, RPO) извлекаются из артефакта «NFR &amp; Security»;
    факт вносится по данным нагрузочного стенда / мониторинга. breach — факт хуже цели.</p>
    <div class="btnrow" style="margin:10px 0">
      <span class="badge ${VERDICT_BADGE[nfr.verdict]||'b-draft'}">вердикт: ${esc(nfr.verdict||'—')}</span>
      ${nfr.breaches?`<span class="badge ${VERDICT_BADGE.breach}">breach: ${nfr.breaches}</span>`:''}
      ${nfr.unknown?`<span class="badge b-draft">не измерено: ${nfr.unknown}</span>`:''}</div>
    ${nfr.metrics.length?`<table><tr><th>Метрика</th><th>Цель</th><th>Факт</th><th>Статус</th><th>Источник</th><th></th></tr>
      ${nfr.metrics.map(m=>`<tr>
        <td><b>${METRIC_RU[m.metric]||esc(m.metric)}</b></td>
        <td>${m.target_value!=null?`<code>${m.target_value}</code>`:'—'}${m.target_note?`<div class="small mut">${esc(m.target_note)}</div>`:''}</td>
        <td><input id="nfr-act-${m.id}" type="number" step="any" value="${m.actual_value??''}" style="width:110px" placeholder="факт"></td>
        <td><span class="badge ${VERDICT_BADGE[m.status]||'b-draft'}">${m.status}</span><div class="small mut">${esc(m.detail||'')}</div></td>
        <td class="small mut">${esc(m.source||'—')}</td>
        <td><button class="sec" onclick="nfrSave(${m.id})">Сохранить</button></td></tr>`).join('')}</table>`
      :'<p class="mut">Метрик нет — извлеките цели из артефакта NFR или заполните артефакт цифрами.</p>'}
  </div>`;
}
async function nfrExtract(sid){
  try{
    const r = await api(`/services/${sid}/nfr/extract`, {method:'POST'});
    toast(r.saved.length?`Извлечены и сохранены цели: ${r.saved.map(m=>METRIC_RU[m]||m).join(', ')}`
         :'Цифры в артефакте NFR не найдены — заполните RPS/p95/SLA/RTO/RPO');
    render();
  }catch(e){ toast(esc(e.message), true); }
}
async function nfrSave(mid){
  try{
    const v = $(`#nfr-act-${mid}`).value;
    const r = await api(`/nfr/${mid}`, {method:'PATCH', body: JSON.stringify({actual_value:v===''?null:+v})});
    toast(`Факт сохранён · вердикт сервиса: ${r.verdict}`); render();
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- Требования (ФТ/НФТ): вход в архитектурную работу ---------- */
const REQ_TYPE_BADGE = {func: 'b-desired', nonfunc: 'b-mandatory'};
const REQ_TYPE_RU = {func: 'ФТ', nonfunc: 'НФТ'};
const REQ_STATUS_RU = {new: 'новое', in_work: 'в работе', covered: 'покрыто'};
let REQS_PREVIEW = [];   // разобранный документ на подтверждении импорта

function artTitle(kind){
  const a = (S.standard.artifacts || []).find(x => x.kind === kind);
  return a ? a.title : kind;
}

function tabReqs(s){
  const rs = s.requirements || [];
  const nF = rs.filter(r => r.req_type === 'func').length, nN = rs.length - nF;
  const uncovered = rs.filter(r => !(r.covered_by || []).length).length;
  $('#tabbody').innerHTML = `<div class="grid g2" style="align-items:start">
  <div class="card">
    <h2 style="margin-top:0">Вход: требования к сервису</h2>
    <p class="small mut">Архитектурная работа начинается с требований. Вставьте документ
    с бизнес- (ФТ) и нефункциональными (НФТ) требованиями — AI-Buddy разберёт его на
    отдельные требования (advisory, вы подтверждаете импорт). Далее: AI-черновики
    артефактов проектируются <b>с учётом этих требований</b>, НФТ переносятся в
    NFR profile, а покрытие (упоминание ФТ-N в артефактах) показывает, что ни одно
    требование не потерялось.</p>
    <div class="btnrow">
      <button class="cya" onclick="reqNfrDraft(${s.id}, this)">⇥ Сгенерировать NFR profile из НФТ</button>
      <span class="small mut">${nF} ФТ · ${nN} НФТ${uncovered?` · <b style="color:var(--bad)">не покрыто: ${uncovered}</b>`:''}</span>
    </div>
    <div style="margin:12px 0 6px"><button class="sec" onclick="reqToggleParse()">🧠 Вставить документ требований</button></div>
    <div id="req-parse" style="display:none">
      <textarea id="req-doc" rows="8" style="width:100%"
        placeholder="Вставьте текст ФТ/НФТ из Confluence, Jira или документа…"></textarea>
      <div class="btnrow"><button onclick="reqParse(${s.id})">🧠 Разобрать документ</button>
      <span class="small mut" id="req-parse-note"></span></div>
      <div id="req-preview"></div>
    </div>
    <label style="margin-top:12px">Добавить вручную</label>
    <div class="grid g2">
      <select id="req-type"><option value="func">ФТ — функция</option><option value="nonfunc">НФТ — качество</option></select>
      <input id="req-src" placeholder="Источник: Confluence / Jira (ссылка)">
    </div>
    <textarea id="req-text" rows="2" style="width:100%;margin-top:6px" placeholder="Текст требования"></textarea>
    <div class="btnrow"><button onclick="reqAdd(${s.id})">＋ Добавить требование</button></div>
  </div>
  <div class="card">
    <h2 style="margin-top:0">Реестр требований</h2>
    ${rs.length ? `<table><tr><th>ID</th><th>Требование</th><th>Статус</th><th>Покрытие</th><th></th></tr>
    ${rs.map(r => `<tr>
      <td><span class="badge ${REQ_TYPE_BADGE[r.req_type]}">${REQ_TYPE_RU[r.req_type]}</span>
          <div class="small mut" style="margin-top:2px"><b>${esc(r.ext_id||'')}</b>${r.source_url?`<br><a class="lnk" href="${esc(r.source_url)}" target="_blank">источник ↗</a>`:''}</div></td>
      <td style="max-width:340px">${esc(r.text)}</td>
      <td><select onchange="reqStatus(${r.id}, this.value)">
        ${['new','in_work','covered'].map(st => `<option value="${st}" ${st===r.status?'selected':''}>${REQ_STATUS_RU[st]}</option>`).join('')}
      </select></td>
      <td>${(r.covered_by||[]).length
        ? r.covered_by.map(k => `<span class="badge b-approved" title="${esc(artTitle(k))}">${esc(k)}</span>`).join(' ')
        : '<span class="badge b-N">не покрыто</span>'}</td>
      <td><button class="sec" onclick="reqDel(${r.id}, ${s.id})" title="Удалить">✕</button></td></tr>`).join('')}
    </table>` : '<p class="mut">Требований пока нет — вставьте документ или добавьте вручную. Затем откройте «Артефакты»: AI-черновик учтёт требования.</p>'}
  </div></div>`;
}

function reqToggleParse(){
  const el = document.getElementById('req-parse');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function reqParse(sid){
  const text = document.getElementById('req-doc').value.trim();
  if(!text) return toast('Вставьте текст документа', true);
  const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('Разобрать документ'));
  if(btn){ btn.disabled = true; btn.textContent = '⏳ Разбираю…'; }
  try{
    const r = await api(`/services/${sid}/requirements/parse`,
      {method:'POST', body: JSON.stringify({text, model: chatModelSel()})});
    REQS_PREVIEW = r.items;
    document.getElementById('req-parse-note').textContent =
      r.provider === 'ai-buddy' ? 'разобрано AI-Buddy' : 'простой разбор по строкам (LLM недоступна)';
    if(!r.items.length) toast('Требования в документе не найдены', true);
    reqPreviewRender(sid);
  }catch(e){ toast(esc(e.message), true); }
  if(btn){ btn.disabled = false; btn.textContent = '🧠 Разобрать документ'; }
}

function reqPreviewRender(sid){
  const box = document.getElementById('req-preview');
  if(!REQS_PREVIEW.length){ box.innerHTML = ''; return; }
  box.innerHTML = `<p class="small mut" style="margin:10px 0 4px">Проверьте разбор — отметьте и поправьте, что импортировать:</p>
  <table><tr><th></th><th>Тип</th><th>Требование</th></tr>
  ${REQS_PREVIEW.map((it,i) => `<tr>
    <td><input type="checkbox" id="rp-c${i}" checked></td>
    <td><select id="rp-t${i}">
      <option value="func" ${it.req_type==='func'?'selected':''}>ФТ</option>
      <option value="nonfunc" ${it.req_type==='nonfunc'?'selected':''}>НФТ</option></select></td>
    <td><input id="rp-x${i}" value="${esc(it.text)}" style="width:100%"></td></tr>`).join('')}
  </table>
  <div class="btnrow"><button onclick="reqImport(${sid})">⇣ Импортировать в сервис</button></div>`;
}

async function reqImport(sid){
  const items = REQS_PREVIEW.map((it, i) => {
    if(!document.getElementById(`rp-c${i}`).checked) return null;
    return {req_type: document.getElementById(`rp-t${i}`).value,
            text: document.getElementById(`rp-x${i}`).value};
  }).filter(Boolean);
  if(!items.length) return toast('Ничего не отмечено', true);
  try{
    const r = await api(`/services/${sid}/requirements/import`,
      {method:'POST', body: JSON.stringify({items, source_url: document.getElementById('req-src').value.trim()})});
    REQS_PREVIEW = [];
    toast(`Импортировано требований: <b>${r.created.length}</b> — теперь AI-черновики артефактов учитывают их`);
    viewService(sid, 'reqs');
  }catch(e){ toast(esc(e.message), true); }
}

async function reqAdd(sid){
  const text = document.getElementById('req-text').value.trim();
  if(!text) return toast('Введите текст требования', true);
  try{
    await api(`/services/${sid}/requirements`, {method:'POST', body: JSON.stringify({
      req_type: document.getElementById('req-type').value, text,
      source_url: document.getElementById('req-src').value.trim()})});
    viewService(sid, 'reqs');
  }catch(e){ toast(esc(e.message), true); }
}

async function reqStatus(rid, status){
  try{ await api(`/requirements/${rid}`, {method:'PATCH', body: JSON.stringify({status})}); }
  catch(e){ toast(esc(e.message), true); }
}

async function reqDel(rid, sid){
  try{
    await api(`/requirements/${rid}`, {method:'DELETE'});
    viewService(sid, 'reqs');
  }catch(e){ toast(esc(e.message), true); }
}

async function reqNfrDraft(sid, btn){
  btn.disabled = true; btn.textContent = '⏳ Генерирую…';
  try{
    const r = await api(`/services/${sid}/nfr/from-requirements`, {method:'POST'});
    await viewService(sid, 'artifacts');
    const el = document.getElementById('a-nfr_security');
    if(el) el.value = r.content_md;
    toast(`NFR profile из НФТ (${r.provider === 'ai-buddy' ? esc(r.model||'AI-Buddy') : 'перенос без LLM'}) вставлен в артефакт — <b>требует подтверждения автора</b>`);
  }catch(e){ toast(esc(e.message), true); btn.disabled = false; btn.textContent = '⇥ Сгенерировать NFR profile из НФТ'; }
}

/* ---------- Проектирование: визуальный C4-редактор (L1/L2) ---------- */
const C4_TYPES = [
  {t:'person',    ru:'Персона',          icon:'👤', fill:'#eef2ff', line:'#6366f1', dash:''},
  {t:'system',    ru:'Наша система',     icon:'🖥️', fill:'#ecfdf5', line:'#10b981', dash:''},
  {t:'external',  ru:'Внешняя система',  icon:'☁️', fill:'#fff7ed', line:'#f59e0b', dash:'6 3'},
  {t:'container', ru:'Контейнер',        icon:'📦', fill:'#f0f9ff', line:'#0ea5e9', dash:''},
  {t:'db',        ru:'База данных',      icon:'🗄️', fill:'#fdf4ff', line:'#c026d3', dash:''}
];
const C4_TYPE = Object.fromEntries(C4_TYPES.map(x => [x.t, x]));
const C4_W = 160, C4_H = 64;
const C4_VIEWS = {context: 'Контекст (L1)', container: 'Контейнеры (L2)'};
let DSGN = {sid: null, models: {}, view: 'context', sel: null, selType: null, linkFrom: null, saveT: null, pending: null};

const c4M = () => DSGN.models[DSGN.view];
const c4Node = id => c4M() && (c4M().nodes || []).find(n => n.id === id);
const c4Edge = id => c4M() && (c4M().edges || []).find(e => e.id === id);

async function tabDesign(s){
  c4FlushSave();                      // недосейвенный вид предыдущего сервиса уходит под своим {sid, view}
  DSGN.sid = s.id; DSGN.sel = null; DSGN.selType = null; c4CancelLink();
  const r = await api(`/services/${s.id}/c4`).catch(() => ({models: {}}));
  DSGN.models = r.models || {};
  for(const v of Object.keys(C4_VIEWS))
    if(!DSGN.models[v]) DSGN.models[v] = {nodes: [], edges: []};
  DSGN.view = DSGN.models.context.nodes.length ? 'context'
            : DSGN.models.container.nodes.length ? 'container' : 'context';
  $('#tabbody').innerHTML = `
  <div class="card" style="margin-bottom:14px">
    <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">
      <div><b>Проектирование архитектуры — C4</b>
        <div class="small mut">Сценарий 1 — рисуйте вручную палитрой слева. Сценарий 2 —
        «AI-структура» спроектирует модель из требований и фактов сервиса, затем правьте её же редактором.
        Модель хранится как JSON; «Экспорт в Mermaid» кладёт C4-исходник в артефакт Vision для self-check.</div></div>
      <div class="btnrow">
        <button onclick="c4AI('${DSGN.view}', this)">🧠 AI-структура</button>
        <button class="sec" onclick="c4Preview(this)">👁 Mermaid-предпросмотр</button>
        <button class="cya" onclick="c4Export(this)">⇥ Экспорт в артефакт Vision</button>
      </div>
    </div>
  </div>
  <div class="design-shell">
    <div class="c4-side">
      <b class="small">ПАЛИТРА ЭЛЕМЕНТОВ</b>
      <div class="c4-palette">
        ${C4_TYPES.map(x => `<button onclick="c4Add('${x.t}')" title="Добавить: ${x.ru}">${x.icon} ${x.ru}</button>`).join('')}
      </div>
      <div class="btnrow">
        <button class="sec" id="c4-linkbtn" onclick="c4LinkMode()">🔗 Связать</button>
        <button class="sec" onclick="c4DeleteSel()">🗑 Удалить</button>
      </div>
      <b class="small" style="margin-top:8px">СВОЙСТВА</b>
      <div id="c4-props"></div>
      <div id="c4-status" class="small mut" style="margin-top:8px"></div>
    </div>
    <div class="c4-main">
      <div class="c4-views">
        ${Object.entries(C4_VIEWS).map(([v, t]) =>
          `<button class="sec ${v===DSGN.view?'c4-vact':''}" data-view="${v}" onclick="c4SetView('${v}')">${t}</button>`).join('')}
      </div>
      <svg id="c4-svg" viewBox="0 0 960 560" xmlns="http://www.w3.org/2000/svg">
        <defs><marker id="c4-arrow" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker></defs>
        <rect x="0" y="0" width="960" height="560" fill="none"/>
        <g id="c4-g"></g>
      </svg>
    </div>
  </div>
  <pre id="c4-preview" class="chatcode" style="display:none;margin-top:12px;max-height:300px;overflow:auto"></pre>`;
  c4Draw(); c4Props(); c4Status();
  c4BindSvg();
}

function c4SetView(v){
  c4FlushSave();                      // правки текущего вида сохраняются до переключения
  DSGN.view = v; DSGN.sel = null; DSGN.selType = null; c4CancelLink();
  document.querySelectorAll('.c4-views button').forEach(b => b.classList.toggle('c4-vact', b.dataset.view === v));
  const btn = [...document.querySelectorAll('.card button')].find(b => b.textContent.includes('AI-структура'));
  if(btn) btn.setAttribute('onclick', `c4AI('${v}', this)`);
  c4Draw(); c4Props(); c4Status();
}

function c4Draw(){
  const g = document.getElementById('c4-g'); if(!g) return;
  const m = c4M();
  const center = n => ({x: n.x + C4_W/2, y: n.y + C4_H/2});
  const trim = (a, b) => {   // обрезка линии по границам прямоугольников
    const dx = b.x - a.x, dy = b.y - a.y;
    if(!dx && !dy) return {a, b};
    const t = Math.min(dx ? (C4_W/2) / Math.abs(dx) : 1e9, dy ? (C4_H/2) / Math.abs(dy) : 1e9);
    return {a: {x: a.x + dx * t, y: a.y + dy * t}, b: {x: b.x - dx * t, y: b.y - dy * t}};
  };
  let edges = '';
  for(const e of (m.edges || [])){
    const f = c4Node(e.from), t = c4Node(e.to);
    if(!f || !t) continue;
    const p = trim(center(f), center(t));
    const selE = DSGN.selType === 'edge' && DSGN.sel === e.id;
    const lbl = esc(e.label || 'взаимодействует');
    edges += `<line data-eid="${esc(e.id)}" x1="${p.a.x}" y1="${p.a.y}" x2="${p.b.x}" y2="${p.b.y}"
      stroke="${selE ? '#e11d48' : '#64748b'}" stroke-width="${selE ? 3 : 1.6}" marker-end="url(#c4-arrow)"/>
      <line data-eid="${esc(e.id)}" x1="${p.a.x}" y1="${p.a.y}" x2="${p.b.x}" y2="${p.b.y}"
      stroke="transparent" stroke-width="12"/>
      <text x="${(p.a.x + p.b.x)/2}" y="${(p.a.y + p.b.y)/2 - 5}" text-anchor="middle"
      font-size="10.5" fill="#334155" style="paint-order:stroke" stroke="#f8fafc" stroke-width="4"
      font-weight="600">${lbl}${e.tech ? ` · ${esc(e.tech)}` : ''}</text>`;
  }
  let nodes = '';
  for(const n of (m.nodes || [])){
    const ty = C4_TYPE[n.type] || C4_TYPE.container;
    const selN = DSGN.selType === 'node' && DSGN.sel === n.id;
    const isLinkFrom = DSGN.linkFrom === n.id;
    const nm = n.name.length > 21 ? n.name.slice(0, 20) + '…' : n.name;
    nodes += `<g data-nid="${esc(n.id)}" transform="translate(${n.x},${n.y})" style="cursor:grab">
      <rect width="${C4_W}" height="${C4_H}" rx="10" fill="${ty.fill}"
        stroke="${selN || isLinkFrom ? '#e11d48' : ty.line}" stroke-width="${selN || isLinkFrom ? 3 : ty.t==='system'?2.4:1.6}"
        ${ty.dash ? `stroke-dasharray="${ty.dash}"` : ''}/>
      <text x="${C4_W/2}" y="22" text-anchor="middle" font-size="14">${ty.icon}</text>
      <text x="${C4_W/2}" y="39" text-anchor="middle" font-size="12" font-weight="700" fill="#0f172a">${esc(nm)}</text>
      <text x="${C4_W/2}" y="54" text-anchor="middle" font-size="9.5" fill="#475569">${esc((n.tech || ty.ru).slice(0, 26))}</text>
    </g>`;
  }
  g.innerHTML = edges + nodes;
}

function c4Point(e){
  const svg = document.getElementById('c4-svg');
  const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}

let C4DRAG = null;
function c4BindSvg(){
  const svg = document.getElementById('c4-svg'); if(!svg) return;
  svg.onmousedown = e => {
    const eg = e.target.closest('[data-eid]');
    if(eg && !c4LinkOn()){          // в режиме связи клики по связям игнорируем — работаем с узлами
      DSGN.sel = eg.dataset.eid; DSGN.selType = 'edge';
      c4Draw(); c4Props(); return;
    }
    const ng = e.target.closest('[data-nid]');
    if(!ng){ c4CancelLink(); c4Draw(); c4Sel(null); return; }
    const n = c4Node(ng.dataset.nid);
    const p = c4Point(e);
    C4DRAG = {id: n.id, sx: p.x, sy: p.y, ox: n.x, oy: n.y, moved: false};
    e.preventDefault();
  };
  svg.onmousemove = e => {
    if(!C4DRAG) return;
    const n = c4Node(C4DRAG.id); if(!n) return;
    const p = c4Point(e);
    const dx = p.x - C4DRAG.sx, dy = p.y - C4DRAG.sy;
    if(Math.abs(dx) + Math.abs(dy) > 3) C4DRAG.moved = true;
    n.x = Math.max(0, Math.min(960 - C4_W, C4DRAG.ox + dx));
    n.y = Math.max(0, Math.min(560 - C4_H, C4DRAG.oy + dy));
    c4Draw();
  };
  svg.onmouseup = () => {
    if(C4DRAG && !C4DRAG.moved){
      const id = C4DRAG.id;
      if(c4LinkOn() && !DSGN.linkFrom){          // первый клик — источник связи
        DSGN.linkFrom = id; c4Draw(); c4Status();
      } else if(DSGN.linkFrom && DSGN.linkFrom !== id){   // второй клик — цель: создаём связь
        const m = c4M();
        m.edges.push({id: 'e' + Date.now(), from: DSGN.linkFrom, to: id, label: '', tech: ''});
        c4CancelLink();
        c4Draw(); c4Props(); c4Status(); c4SaveSoon();
      } else if(DSGN.linkFrom){                  // клик по самому источнику — отмена
        c4CancelLink(); c4Draw(); c4Status();
      } else { c4Sel(id, 'node'); }
    } else if(C4DRAG && C4DRAG.moved){ c4SaveSoon(); }
    C4DRAG = null;
  };
  svg.onmouseleave = () => { if(C4DRAG && C4DRAG.moved) c4SaveSoon(); C4DRAG = null; };
}

document.addEventListener('keydown', e => {
  if(!document.getElementById('c4-svg')) return;
  if(e.target.matches('input,textarea,select')) return;
  // удаление по клавише — только когда фокус на холсте или теле документа,
  // а не на кнопках/ссылках (иначе Backspace «съедает» выбранный узел под модалкой)
  const onCanvas = e.target === document.body || e.target.closest?.('#c4-svg');
  if((e.key === 'Delete' || e.key === 'Backspace') && DSGN.sel && onCanvas){ e.preventDefault(); c4DeleteSel(); }
  if(e.key === 'Escape'){ c4CancelLink(); c4Sel(null); c4Draw(); }
});

function c4Sel(id, type){
  DSGN.sel = id; DSGN.selType = id ? type : null;
  c4Draw(); c4Props();
}

function c4Add(type){
  const m = c4M();
  const n = {id: 'n' + Date.now(), type, name: C4_TYPE[type].ru, desc: '', tech: '',
             x: 60 + Math.round(Math.random() * 14) * 40, y: 60 + Math.round(Math.random() * 9) * 40};
  m.nodes.push(n);
  c4Sel(n.id, 'node'); c4Status(); c4SaveSoon();
}

const c4LinkOn = () => { const b = document.getElementById('c4-linkbtn'); return !!b && b.classList.contains('c4-vact'); };
const c4CancelLink = () => { DSGN.linkFrom = null; const b = document.getElementById('c4-linkbtn'); if(b) b.classList.remove('c4-vact'); };

function c4LinkMode(){
  const btn = document.getElementById('c4-linkbtn');
  const on = !btn.classList.contains('c4-vact');
  btn.classList.toggle('c4-vact', on);
  DSGN.linkFrom = null;               // источник ещё не выбран — выбирается первым кликом по узлу
  if(on) toast('Режим связи: кликните <b>источник</b>, затем <b>цель</b> (Esc — отмена)');
  c4Status();
}

function c4DeleteSel(){
  const m = c4M(); if(!DSGN.sel) return toast('Ничего не выбрано', true);
  if(DSGN.selType === 'node'){
    m.nodes = m.nodes.filter(n => n.id !== DSGN.sel);
    m.edges = m.edges.filter(e => e.from !== DSGN.sel && e.to !== DSGN.sel);
  } else {
    m.edges = m.edges.filter(e => e.id !== DSGN.sel);
  }
  c4Sel(null); c4Status(); c4SaveSoon();
}

function c4Props(){
  const el = document.getElementById('c4-props'); if(!el) return;
  if(!DSGN.sel){ el.innerHTML = '<p class="small mut">Выберите элемент на холсте.<br>🔗 Связать: кликните источник → цель.</p>'; return; }
  if(DSGN.selType === 'node'){
    const n = c4Node(DSGN.sel); if(!n) return;
    el.innerHTML = `
      <label>Тип</label><select onchange="c4Set('type', this.value)">
        ${C4_TYPES.map(x => `<option value="${x.t}" ${x.t===n.type?'selected':''}>${x.icon} ${x.ru}</option>`).join('')}</select>
      <label>Название</label><input value="${esc(n.name)}" oninput="c4Set('name', this.value)">
      <label>Технология</label><input value="${esc(n.tech)}" oninput="c4Set('tech', this.value)" placeholder="FastAPI, PostgreSQL…">
      <label>Описание</label><textarea rows="2" oninput="c4Set('desc', this.value)">${esc(n.desc)}</textarea>`;
  } else {
    const e = c4Edge(DSGN.sel); if(!e) return;
    const f = c4Node(e.from), t = c4Node(e.to);
    el.innerHTML = `
      <p class="small mut" style="margin:0 0 6px">${esc(f?.name||'?')} → ${esc(t?.name||'?')}</p>
      <label>Что передаёт</label><input value="${esc(e.label)}" oninput="c4Set('label', this.value)" placeholder="запросы, платежи…">
      <label>Технология</label><input value="${esc(e.tech)}" oninput="c4Set('tech', this.value)" placeholder="HTTPS, gRPC…">`;
  }
}

function c4Set(k, v){
  const o = DSGN.selType === 'node' ? c4Node(DSGN.sel) : c4Edge(DSGN.sel);
  if(!o) return;
  o[k] = v;
  c4Draw(); c4Status(); c4SaveSoon();
}

function c4Status(note){
  const el = document.getElementById('c4-status'); if(!el) return;
  const m = c4M();
  el.innerHTML = `<b>${esc(C4_VIEWS[DSGN.view])}</b>: узлов ${m.nodes.length} · связей ${m.edges.length}`
    + (note ? ` · ${esc(note)}` : '')
    + (DSGN.linkFrom ? ' · <b style="color:#e11d48">режим связи: выберите цель</b>' : '');
}

function c4SaveSoon(){
  clearTimeout(DSGN.saveT);
  // снимок фиксируется сейчас: таймер обязан сохранить тот {sid, view, данные}, при которых
  // была правка, а не те, что станут актуальными через 1.2 с (иначе правка молча теряется)
  DSGN.pending = {sid: DSGN.sid, view: DSGN.view,
                  model: JSON.parse(JSON.stringify({nodes: c4M().nodes, edges: c4M().edges}))};
  DSGN.saveT = setTimeout(() => { DSGN.saveT = null; c4Save(); }, 1200);
}

function c4FlushSave(){
  if(!DSGN.saveT) return;
  clearTimeout(DSGN.saveT); DSGN.saveT = null;
  const job = DSGN.pending; DSGN.pending = null;
  if(job) c4Save(job);              // немедленный досейв под старым видом (при смене вида/таба)
}

async function c4Save(job){
  const use = job || DSGN.pending;
  if(!job) DSGN.pending = null;
  if(!use) return;
  try{
    await api(`/services/${use.sid}/c4/${use.view}`,
      {method:'PUT', body: JSON.stringify({model: use.model})});
    c4Status('сохранено');
  }catch(e){ toast(esc(e.message), true); }
}

async function c4AI(view, btn){
  if(c4M().nodes.length && !confirm('Заменить текущую модель ' + C4_VIEWS[view] + ' AI-структурой?')) return;
  const old = btn.textContent;
  btn.disabled = true; btn.textContent = '⏳ Проектирую…';
  try{
    const r = await api(`/services/${DSGN.sid}/c4/${view}/ai`,
      {method:'POST', body: JSON.stringify({model: chatModelSel()})});
    DSGN.models[view] = {nodes: r.model_json.nodes, edges: r.model_json.edges};
    c4SetView(view);
    toast(`${r.provider === 'ai-buddy' ? 'AI-структура (' + esc(r.model||'') + ')' : 'Стартовая структура'} для ${esc(C4_VIEWS[view])} загружена в редактор — <b>проверьте и поправьте</b>`);
  }catch(e){ toast(esc(e.message), true); }
  btn.disabled = false; btn.textContent = old;
}

async function c4Preview(btn){
  try{
    const r = await api(`/services/${DSGN.sid}/c4/export`,
      {method:'POST', body: JSON.stringify({dry_run: true})});
    const pre = document.getElementById('c4-preview');
    if(!r.code){ pre.style.display = 'none'; return toast('Модели пусты — предпросмотра нет', true); }
    pre.style.display = 'block';
    pre.textContent = r.code;
    toast('Предпросмотр Mermaid-исходника ниже (в артефакт не записан)');
  }catch(e){ toast(esc(e.message), true); }
}

async function c4Export(btn){
  btn.disabled = true; const old = btn.textContent; btn.textContent = '⏳ Экспортирую…';
  try{
    const r = await api(`/services/${DSGN.sid}/c4/export`, {method:'POST'});
    toast(r.updated
      ? `Mermaid C4-исходник (${r.code_len} симв.) записан в артефакт <b>Vision</b> — «Диаграммы» и self-check увидят L1/L2`
      : 'Модели пусты — исходник диаграммы очищен');
  }catch(e){ toast(esc(e.message), true); }
  btn.disabled = false; btn.textContent = old;
}

/* ---------- MVP2: AI-ассистент по стандарту (BR-48…50) — чат в стиле ChatGPT ---------- */
const PROVIDER_RU = {'ai-buddy': 'AI-Buddy (корпоративная LLM)', 'local-rag': 'локальная база знаний (LLM не подключена)', 'none': ''};
let CHAT = [];            // [{role:'user'|'bot', text, provider, model, confidence, citations}]
let CHAT_ID = null;       // id текущего чата-сессии на сервере (null = новый чат)
let CHAT_BUSY = false;
let ASK_SERVICE = null;   // контекст сервиса (ассистент из карточки сервиса)
let ASK_SVC_NAME = '';

const CHAT_SUGGESTIONS = [
  ['Какие документы обязательны для проекта?', 'Матрица обязательных артефактов по типам проектов'],
  ['Как генерируется ID техдолга?', 'Правило формирования AD/TD-идентификаторов'],
  ['Что не является техническим долгом?', 'Границы понятия TD по стандарту'],
  ['Когда идти к эксперту домена?', 'Сценарии обязательного ревью'],
];

function mdLite(src){
  // безопасный мини-markdown: экранируем всё, потом ограниченные замены
  let t = esc(src);
  t = t.replace(/```([\s\S]*?)```/g, (m,c)=>`<pre class="chatcode"><code>${c.trim()}</code></pre>`);
  t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  t = t.replace(/^#{2,4}\s+(.+)$/gm, '<b class="ch">$1</b>');
  t = t.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/^(\s*)[·\-•]\s+(.+)$/gm, '$1• $2');   // буллеты → единый вид
  return t;
}

const CHAT_MODEL_KEY = 'darch_chat_model';

function chatModelSel(){
  const s = $('#chat-model');
  return s && s.value ? s.value : '';
}

async function chatLoadModels(){
  // селектор моделей в строке чата (скрыт, если LLM не подключена)
  try{
    const r = await api('/assistant/models');
    const sel = $('#chat-model'); if(!sel || !r.models || !r.models.length) return;
    sel.innerHTML = r.models.map(m =>
      `<option value="${esc(m)}"${m === r.default ? ' selected' : ''}>${esc(m)}</option>`).join('');
    const saved = localStorage.getItem(CHAT_MODEL_KEY);
    if(saved && r.models.includes(saved)) sel.value = saved;
    sel.style.display = '';
  }catch{ /* селектор остаётся скрыт */ }
}

function chatModelPick(){
  const s = $('#chat-model');
  if(s && s.value) localStorage.setItem(CHAT_MODEL_KEY, s.value);
}

async function loadChats(){
  // список чатов пользователя для левой панели
  try{
    const r = await api('/assistant/chats');
    const el = $('#chat-list'); if(!el) return;
    el.innerHTML = (r.chats || []).map(c => `
      <div class="chat-item${c.id === CHAT_ID ? ' active' : ''}" onclick="chatOpen(${c.id})" title="${esc(c.title||'')}">
        <span class="chat-item-title">${esc(c.title || 'Чат')}</span>
        <span class="chat-item-del" onclick="event.stopPropagation(); chatDelete(${c.id})" title="Удалить чат">✕</span>
      </div>`).join('');
  }catch{ /* нет доступа — панель пустая */ }
}

async function chatOpen(id){
  if(CHAT_BUSY) return;
  try{
    const r = await api('/assistant/history?chat_id=' + id);
    CHAT_ID = id;
    CHAT = (r.messages || []).map(m => ({
      role: m.role === 'assistant' ? 'bot' : 'user',
      text: m.content, provider: m.provider, model: m.model,
      confidence: m.confidence, citations: m.citations || []}));
    renderChat(); loadChats();
  }catch{}
}

async function chatDelete(id){
  if(CHAT_BUSY) return;
  try{ await api('/assistant/chats/' + id, {method:'DELETE'}); }catch{}
  if(CHAT_ID === id){ CHAT_ID = null; CHAT = []; renderChat(); }
  loadChats();
}

async function viewAssistant(){
  let st = {provider:'local-rag', kb_pages:'…', kb_chunks:''};
  try{ st = await api('/assistant/status'); }catch{}
  const badge = st.provider === 'ai-buddy'
    ? `<span class="badge b-approved">● AI-Buddy</span>`
    : `<span class="badge b-in_review">● fallback: локальная база знаний</span>`;
  const svcChip = ASK_SERVICE
    ? `<span class="chip" id="svc-ctx-chip">🧩 ${esc(ASK_SVC_NAME || ('service #' + ASK_SERVICE))}
       <span style="cursor:pointer" onclick="clearAskService()" title="Убрать контекст сервиса">✕</span></span>`
    : '';
  $('#view').innerHTML = `
  <div class="chat-shell">
    <aside class="chat-side">
      <button class="chat-new-btn" onclick="chatNew()">＋ Новый чат</button>
      <div class="chat-side-label">История</div>
      <div class="chat-list" id="chat-list"></div>
    </aside>
    <div class="chat-wrap">
      <div class="chat-head">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <b style="font-size:15px">AI-ассистент стандарта</b>${badge}${svcChip}
          <span class="chip small">база знаний: ${st.kb_pages} стр · ${st.kb_chunks} чанков</span>
        </div>
      </div>
      <div class="chat-scroll" id="chat-scroll"><div class="chat-log" id="chat-log"></div></div>
      <div class="composer">
        <div class="composer-box">
          <textarea id="q" rows="1" placeholder="Спросите про стандарт — артефакты, ревью, техдолг, fitness…"
            onkeydown="chatKeydown(event)" oninput="chatAutogrow(this)"></textarea>
          <select id="chat-model" class="chat-model" style="display:none"
            onchange="chatModelPick()" title="Модель LLM"></select>
          <button class="send-btn" id="send-btn" onclick="askAssistant()" title="Отправить (Enter)">↑</button>
        </div>
        <p class="small mut" style="text-align:center;margin-top:8px">
          Advisory-режим (BR-33): ассистент ничего не меняет, решение за человеком.
          Ответы генерируются по страницам стандарта, но могут содержать неточности — проверяйте по первоисточнику.</p>
      </div>
    </div>
  </div>`;
  const chats = await api('/assistant/chats').catch(() => ({chats: []}));
  if((chats.chats || []).length) await chatOpen(chats.chats[0].id);   // последний чат
  else renderChat();
  $('#q').focus();
  chatLoadModels();
  loadChats();
}

async function askAssistantAbout(sid){
  ASK_SERVICE = sid;
  try{ const sv = await api('/services/' + sid); ASK_SVC_NAME = sv.name; }
  catch{ ASK_SVC_NAME = ''; }
  location.hash = '#/assistant';
}
function clearAskService(){
  ASK_SERVICE = null; ASK_SVC_NAME = '';
  const el = document.getElementById('svc-ctx-chip'); if(el) el.remove();
}

function chatMsgHtml(m){
  if(m.role === 'user')
    return `<div class="msg user"><div class="bubble">${mdLite(m.text)}</div></div>`;
  const cites = (m.citations || []).length ? `<div class="btnrow chat-cites">${m.citations.map(c =>
    `<span class="chip">📄 <a class="lnk" href="${esc(c.url)}" target="_blank">${esc(c.title)}</a>
     <span class="small mut">pageId=${c.page_id}</span></span>`).join('')}</div>` : '';
  const meta = `<div class="btnrow chat-meta">
      <span class="badge ${m.provider==='ai-buddy'?'b-approved':'b-in_review'} small-badge">${esc(PROVIDER_RU[m.provider]||m.provider||'')}</span>
      <span class="small mut">уверенность ${Math.round((m.confidence||0)*100)}% · advisory</span></div>`;
  return `<div class="msg bot"><div class="avatar">▲</div><div class="body">
    <div class="bot-text">${mdLite(m.text)}</div>${cites}${meta}</div></div>`;
}

function chatEmptyHtml(){
  return `<div class="chat-empty">
    <div class="avatar big">▲</div>
    <div class="greet">Чем помочь по стандарту?</div>
    <p class="mut" style="text-align:center">Спрашивайте про Architecture Definition Set — отвечаю по реальным страницам Confluence dats.tech, с цитатами.</p>
    <div class="sugg-grid">${CHAT_SUGGESTIONS.map(([q,d]) =>
      `<button class="sugg" onclick="askQ(${JSON.stringify(q).replace(/"/g,'&quot;')})">
        <b>${esc(q)}</b><span class="small mut">${esc(d)}</span></button>`).join('')}</div>
  </div>`;
}

function renderChat(typing=false){
  const log = $('#chat-log'); if(!log) return;
  log.innerHTML = CHAT.length ? CHAT.map(chatMsgHtml).join('') : chatEmptyHtml();
  if(typing){
    log.insertAdjacentHTML('beforeend',
      `<div class="msg bot" id="typing"><div class="avatar">▲</div><div class="body">
       <div class="typing"><span></span><span></span><span></span></div></div></div>`);
  }
  const sc = $('#chat-scroll');
  sc.scrollTop = (CHAT.length || typing) ? sc.scrollHeight : 0;
}

function chatNew(){
  if(CHAT_BUSY) return;
  CHAT_ID = null; CHAT = []; renderChat(); loadChats(); $('#q').focus();
}
function chatKeydown(e){
  if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); askAssistant(); }
}
function chatAutogrow(t){
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 160) + 'px';
}
function askQ(q){ $('#q').value = q; chatAutogrow($('#q')); askAssistant(); }

async function askAssistant(){
  if(CHAT_BUSY) return;
  const box = $('#q'); if(!box) return;
  const question = box.value.trim();
  if(!question) return;
  CHAT.push({role:'user', text:question});
  box.value = ''; chatAutogrow(box);
  CHAT_BUSY = true; $('#send-btn').disabled = true;
  renderChat(true);   // индикатор набора, пока летит запрос
  const history = CHAT.slice(0, -1).map(m => ({role: m.role === 'bot' ? 'assistant' : 'user',
                                               content: m.text}));
  const model = chatModelSel();
  const ok = await chatStream(question, history, model);
  if(!ok) await chatFallback(question, history, model);
  CHAT_BUSY = false; if($('#send-btn')) $('#send-btn').disabled = false;
  renderChat();
  loadChats();   // новый чат появился в списке / обновился порядок
}

/* Стриминговый ответ: SSE от /assistant/stream + посимвольная «допечатка».
   Возвращает true, если стриминг состоялся. */
async function chatStream(question, history, model){
  let resp;
  try{
    resp = await fetch('/api/assistant/stream', {
      method:'POST',
      headers:{'Content-Type':'application/json', 'X-Token': localStorage.token||''},
      body: JSON.stringify({question, history, model, chat_id: CHAT_ID, service_id: ASK_SERVICE})});
  }catch{ return false; }
  if(!resp.ok || !resp.body) return false;

  const log = $('#chat-log'); if(!log) return false;
  let settle; const finished = new Promise(r => settle = r);   // resolve в finalize()

  const msg = {role:'bot', text:'', provider:'ai-buddy', model:null,
               confidence:0, citations:[]};
  const node = document.createElement('div');
  node.className = 'msg bot';
  node.innerHTML = `<div class="avatar">▲</div><div class="body">
    <div class="bot-text streaming"></div></div>`;
  // узел добавляется в лог при первой дельте — до этого виден typing-индикатор
  const txtEl = node.querySelector('.bot-text');

  let full = '', shown = 0, metaDone = false, streamEnd = false, failed = false, pumpStarted = false;
  const sc = $('#chat-scroll');
  const nearBottom = () => sc.scrollHeight - sc.scrollTop - sc.clientHeight < 110;

  const finalize = () => {
    msg.text = full; msg.streaming = false;
    CHAT.push(msg);
    settle(true);
  };
  const applyMeta = m => {
    if(m.chat_id) CHAT_ID = m.chat_id;
    if(m.provider !== undefined) msg.provider = m.provider;
    if(m.model !== undefined) msg.model = m.model;
    if(m.confidence !== undefined && m.confidence !== null) msg.confidence = m.confidence;
    if(m.citations) msg.citations = m.citations;
    metaDone = true;
  };
  const pump = () => {
    if(shown < full.length){
      // адаптивный шаг: плавно догоняем поток без рывков
      const step = Math.max(2, Math.ceil((full.length - shown) / 10));
      shown = Math.min(full.length, shown + step);
      txtEl.textContent = full.slice(0, shown) + '▍';
      if(nearBottom()) sc.scrollTop = sc.scrollHeight;
    }
    if(streamEnd && shown >= full.length){ finalize(); return; }
    requestAnimationFrame(pump);
  };
  const handle = ev => {
    if(ev.type === 'meta') applyMeta(ev);
    else if(ev.type === 'delta'){
      if(!metaDone) applyMeta({provider:'local-rag', model:null, confidence:0, citations:[]});
      full += ev.text;
      if(!pumpStarted){
        pumpStarted = true;
        const t = document.getElementById('typing'); if(t) t.remove();
        log.appendChild(node);
        requestAnimationFrame(pump);
      }
    } else if(ev.type === 'done') streamEnd = true;
  };

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  try{
    while(true){
      const {done:rd, value} = await reader.read();
      if(rd){ streamEnd = true; break; }
      buf += dec.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf('\n\n')) >= 0){
        const part = buf.slice(0, idx); buf = buf.slice(idx + 2);
        if(!part.startsWith('data:')) continue;
        const payload = part.slice(5).trim();
        if(payload === '[DONE]'){ streamEnd = true; continue; }
        try{ handle(JSON.parse(payload)); }catch{ /* пропуск битого события */ }
      }
    }
  }catch{ failed = true; }
  if(!pumpStarted){
    return false;      // ответ не пришёл стримом → обычный запрос (узел не добавлялся)
  }
  if(failed) streamEnd = true;   // соединение оборвалось — дорисовываем что есть
  await finished;      // ждём, пока допечатка завершится и сообщение попадёт в CHAT
  return true;
}

/* Fallback: обычный запрос к /assistant (если стриминг недоступен) */
async function chatFallback(question, history, model){
  const msg = {role:'bot', text:'', provider:'local-rag', model:null, confidence:0, citations:[]};
  try{
    const r = await api('/assistant', {method:'POST', body: JSON.stringify({question, history, model, chat_id: CHAT_ID, service_id: ASK_SERVICE})});
    msg.text = r.answer; msg.provider = r.provider; msg.model = r.model;
    msg.confidence = r.confidence; msg.citations = r.citations || [];
    if(r.chat_id) CHAT_ID = r.chat_id;
  }catch(e){
    msg.text = `⚠ ${e.message}`; msg.provider = 'none';
  }
  CHAT.push(msg);
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
    <div class="card"><h2 style="margin-top:0">AI-Buddy: корпоративная LLM</h2>
      <p class="small mut">Подключение LLM для AI-ассистента (BR-48…50) и будущих AI-сценариев (BR-27…29).
      OpenAI-совместимый контракт: <code>{URL}/chat/completions</code>. Токен хранится в настройках
      платформы и никогда не возвращается в UI целиком. «Проверить связь» можно до сохранения —
      используются значения из полей формы.</p>
      <div id="llm-status"></div>
      <div id="llm-form" style="margin-top:8px">
        <label>Base URL</label><input id="llm-url" placeholder="https://aibuddy.internal.company/v1">
        <div class="grid g2"><div><label>Токен</label><input id="llm-token" type="password" placeholder="сервисный токен"></div>
        <div><label>Модель</label><input id="llm-model" list="llm-models" placeholder="ai-buddy-large"></div></div>
        <div class="btnrow"><button onclick="llmSave()">Подключить</button>
          <button class="sec" onclick="llmTest()">Проверить связь</button>
          <button class="sec" onclick="llmModels()">Модели</button>
          <button class="sec" onclick="llmRemove()">Отключить</button></div>
        <datalist id="llm-models"></datalist>
      </div>
      <div id="llm-res" style="margin-top:8px"></div>
    </div>
    <div class="card"><h2 style="margin-top:0">Confluence: реестр техдолга (BR-54…56)</h2>
      <p class="small mut">Двусторонняя синхронизация со страницей «Реестр технического долга»
      (pageId=915912594): экспорт XHTML (storage format) и импорт markdown-таблицы.
      ID долга сохраняется как есть — неизменяем по правилу (pageId=918365931).</p>
      <div class="btnrow"><button class="cya" onclick="cfExport()" ${can?'':'disabled'}>Сформировать XHTML</button></div>
      <div id="cf-exp" style="margin-top:10px"></div>
      <label style="margin-top:12px">Импорт из markdown-таблицы страницы</label>
      <textarea class="sm" id="cf-md" rows="5" placeholder="| ID | Тип долга | Название | Система / домен | ... |"></textarea>
      <div class="btnrow"><button class="sec" onclick="cfImport()" ${['domain_expert','admin'].includes(S.user.role)?'':'disabled'}>Импортировать долги</button></div>
    </div>
    <div class="card"><h2 style="margin-top:0">Журнал аудита</h2>
      <p class="small mut">Все действия фиксируются (BR-33). Просмотр: expert/admin.</p>
      <div class="btnrow">${can?'<button class="sec" onclick="showAudit()">Открыть журнал</button>':'<span class="mut small">нужна роль domain_expert+</span>'}</div>
      <div id="audit-res"></div></div>
  </div>`;
  if (S.user.role === 'admin') renderLlm();
}
async function renderLlm(){
  try{
    const c = await api('/admin/llm');
    $('#llm-status').innerHTML = c.configured
      ? `<div class="btnrow"><span class="badge b-approved">● LLM подключена</span>
         <span class="chip small">${esc(c.url)}</span><span class="chip small">${esc(c.model)}</span>
         <span class="chip small">токен ${esc(c.token_masked)}</span></div>`
      : `<div class="btnrow"><span class="badge b-in_review">● LLM не подключена — ассистент в fallback-режиме</span></div>`;
    $('#llm-url').value = c.url || '';
    $('#llm-model').value = c.model || '';
    $('#llm-token').placeholder = c.token_set ? `задан (${c.token_masked}) — введите новый для замены` : 'сервисный токен';
  }catch(e){ $('#llm-status').innerHTML = `<p class="small mut">${esc(e.message)}</p>`; }
}
async function llmSave(){
  try{
    const c = await api('/admin/llm', {method:'POST', body: JSON.stringify({
      url:$('#llm-url').value, token:$('#llm-token').value, model:$('#llm-model').value})});
    $('#llm-token').value = '';
    toast(c.configured ? `LLM подключена: ${esc(c.model)}` : 'URL пуст — LLM отключена');
    renderLlm();
  }catch(e){ toast(esc(e.message), true); }
}
async function llmTest(){
  $('#llm-res').innerHTML = '<p class="small mut">Проверяю связь с LLM…</p>';
  try{
    const r = await api('/admin/llm/test', {method:'POST', body: JSON.stringify({
      url:$('#llm-url').value, token:$('#llm-token').value, model:$('#llm-model').value})});
    $('#llm-res').innerHTML = `<div class="btnrow">
      <span class="badge ${r.ok?'b-approved':'b-changes_requested'}">${r.ok?'✔ связь есть':'✖ ошибка связи'}</span>
      <span class="small mut">${esc(r.detail)} · ${r.latency_ms} мс</span></div>`;
  }catch(e){ toast(esc(e.message), true); $('#llm-res').innerHTML = ''; }
}
async function llmModels(){
  $('#llm-res').innerHTML = '<p class="small mut">Запрашиваю список моделей…</p>';
  try{
    const r = await api('/admin/llm/models', {method:'POST', body: JSON.stringify({
      url:$('#llm-url').value, token:$('#llm-token').value})});
    if(r.ok){
      $('#llm-models').innerHTML = r.models.map(m => `<option value="${esc(m)}">`).join('');
      $('#llm-res').innerHTML = `<div class="btnrow" style="flex-wrap:wrap">
        <span class="badge b-approved">✔ ${r.models.length} моделей доступно</span>
        ${r.models.map(m => `<span class="chip small" style="cursor:pointer" title="выбрать" onclick="document.getElementById('llm-model').value='${esc(m)}'">${esc(m)}</span>`).join('')}
      </div><p class="small mut">Кликните по модели, чтобы подставить её в поле «Модель».</p>`;
    } else {
      $('#llm-res').innerHTML = `<div class="btnrow">
        <span class="badge b-changes_requested">✖ список недоступен</span>
        <span class="small mut">${esc(r.detail)}</span></div>`;
    }
  }catch(e){ toast(esc(e.message), true); $('#llm-res').innerHTML = ''; }
}
async function llmRemove(){  try{
    await api('/admin/llm/remove', {method:'POST'});
    $('#llm-res').innerHTML = '';
    toast('LLM отключена, настройки удалены'); renderLlm();
  }catch(e){ toast(esc(e.message), true); }
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
async function cfExport(){
  try{
    const r = await api('/integrations/confluence/export', {method:'POST', body: '{}'});
    $('#cf-exp').innerHTML = `<p class="small mut">Записей: ${r.records} · целевая страница: pageId=${r.page_id}</p>
      <pre class="sm" style="max-height:24vh;overflow:auto;background:var(--bg2,#f5f6fa);padding:10px;border-radius:8px;white-space:pre-wrap">${esc(r.xhtml.slice(0,1500))}${r.xhtml.length>1500?'…':''}</pre>`;
    window._CF_XHTML = r.xhtml;
    toast(`XHTML сформирован: ${r.records} записей`);
  }catch(e){ toast(esc(e.message), true); }
}
async function cfImport(){
  try{
    const md = $('#cf-md').value.trim();
    if(!md) return toast('Вставьте markdown-таблицу реестра', true);
    const r = await api('/integrations/confluence/import', {method:'POST', body: JSON.stringify({markdown: md})});
    toast(`Импорт: создано ${r.created.length} · обновлено ${r.updated.length}`);
    $('#cf-md').value = '';
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
