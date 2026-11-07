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
/* права на изменение сервиса: full (эксперт/админ) или team (владелец/product-группа) */
const canEditSvc = s => s.my_scope === 'full' || s.my_scope === 'team';
const canCreateSvc = () => ['admin','domain_expert','team_lead'].includes(S.user.role);
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
  // пункты меню показываем только там, где у роли есть хоть какие-то права
  // (иначе страница встречает 403-текстом или стеной disabled-кнопок)
  const nav = {'#/':'Дашборд','#/services':'Сервисы','#/debts':'Техдолг','#/components':'Компоненты'};
  if(['admin','domain_expert'].includes(S.user.role)) nav['#/access'] = 'Доступ';
  if(['admin','domain_expert','infosec'].includes(S.user.role)) nav['#/admin'] = 'Интеграции';
  $('#nav').innerHTML = Object.entries(nav).map(([u,t]) =>
    `<a href="${u}" class="${h.startsWith(u)&&u!=='#/'||h===u?'act':''}">${t}</a>`).join('');
  $('#userbox').innerHTML = `<b class="u-name">${esc(S.user.display_name)}</b><span class="u-role"> · ${S.user.role}</span> <button class="sec" onclick="logout()">Выйти</button>`;
  aiTriggerMount();
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
  document.getElementById('aipanel')?.remove();
  document.getElementById('ai-trigger')?.remove();   // на экране логина чат-иконки быть не должно
  CHAT = []; CHAT_ID = null; ASK_SERVICE = null; ASK_SVC_NAME = '';   // диалог не должен пережить logout (чужой чат — чужой контекст)
  document.body.classList.remove('ai-open', 'ai-full');
  delete localStorage.token; S.user=null; location.hash='#/'; render();
}

/* ---------- dashboard ---------- */
route(/^#\/$/, viewDash);
route(/^#\/admin$/, viewAdmin);
route(/^#\/services$/, viewServices);
route(/^#\/service\/(\d+)(?:\/(\w+))?$/, (id, tab) => viewService(+id, tab));
route(/^#\/components$/, viewComponents);
route(/^#\/debts$/, viewDebts);
// ассистент больше не страница, а панель поверх любого экрана;
// старые ссылки #/assistant открывают панель поверх дашборда
route(/^#\/assistant$/, async () => { location.replace('#/'); await aiPanelOpen(); });
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
  const covCard = (t, list, link) => {
    const shown = list.slice(0, 5);
    const more = list.length - shown.length;
    return `<div class="card"><div class="mut">${t}</div>
    <div class="kpi" style="color:${list.length ? 'var(--warn)' : 'var(--ok)'}">${list.length}</div>
    <div class="small mut">${list.length
      ? shown.map(x=>`<a class="lnk" href="#/service/${x.id}">${esc(x.code)}</a>`).join(', ')
        + (more > 0 ? ` · <a class="lnk" href="${link}">+${more} ещё</a>` : '')
      : 'покрыто полностью'}</div></div>`;
  };
  $('#view').innerHTML = `
  <h1>Дашборд соответствия стандарту</h1>
  <p class="mut"><a class="lnk" href="${d.standard_ref}" target="_blank">Общий архитектурный стандарт (Architecture Definition Set) ↗</a></p>
  <div class="grid g4" style="margin:18px 0">
    <a class="card vio kpi-link" href="#/services" onclick="S.showArchived=${d.archived_services>0}"><div class="mut">Сервисов в реестре</div><div class="kpi">${d.total_services}</div><div class="small mut">${d.archived_services ? `в архиве: ${d.archived_services}` : 'все активные'}</div></a>
    <a class="card kpi-link" href="#/services"><div class="mut">На ревью / согласовано</div><div class="kpi">${st('in_review')} <span class="mut" style="font-size:16px">/</span> <span style="color:var(--ok)">${st('approved')}</span></div></a>
    <a class="card cya kpi-link" href="#/services"><div class="mut">Нужны изменения</div><div class="kpi" style="color:${st('changes_requested') ? 'var(--warn)' : 'var(--ok)'}">${st('changes_requested')}</div></a>
    <a class="card kpi-link" href="#/debts"><div class="mut">Открытый техдолг P0+P1</div><div class="kpi" style="color:${dp('P0')+dp('P1') ? 'var(--bad)' : 'var(--ok)'}">${dp('P0')+dp('P1')}</div><div class="small mut">всего открытых: ${debtOpen}</div></a>
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
  <div class="card"><table><tr><th>Сервис</th><th>Обязательные артефакты</th><th>Готовность</th><th>Фитнес</th><th>Техдолг</th><th>Ревью</th><th>Следующий шаг</th></tr>
  ${d.readiness.map(r=>{
    const fill = r.mandatory_total - r.mandatory_missing.length;
    return `<tr><td><a class="lnk" href="#/service/${r.id}"><b>${esc(r.name)}</b> <span class="mut">${esc(r.code)}</span></a></td>
    <td><b>${fill}/${r.mandatory_total}</b>${r.mandatory_missing.length ? `<div class="small mut">нет: ${esc(r.mandatory_missing.map(m=>m.title).join(', '))}</div>` : '<div class="small" style="color:var(--ok)">все обязательные заполнены</div>'}</td>
    <td>${r.self_check == null ? '<span class="mut">не проводился</span>' : `<div class="bar" style="width:110px"><i style="width:${r.self_check}%"></i></div><span class="small mut">${r.self_check}%</span>`}</td>
    <td><a class="lnk no-ul" href="#/service/${r.id}/fitness" title="Открыть fitness-проверки">${FIT_DOT(r.fitness)}</a></td>
    <td>${r.debts_open ? `<a class="lnk no-ul" href="#/service/${r.id}/debt" title="Открыть техдолг сервиса"><span ${r.debts_p0 ? 'style="color:var(--bad);font-weight:600"' : ''}>${r.debts_open}</span> <span class="mut small">откр.</span></a>` : '<span class="mut">—</span>'}</td>
    <td>${statusB(r.review_status)}</td>
    <td class="small"><a class="lnk" href="#${r.hint_link}">${esc(r.hint)}</a></td></tr>`;
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
    ${covCard('Без проверки готовности', d.coverage.no_checklist, '#/services')}
  </div>
  ${d.activity.length ? `<h2>Последние события</h2>
  <div class="card"><table class="small">${d.activity.slice(0,8).map(a=>`<tr><td class="mut" style="white-space:nowrap">${fmtTs(a.ts)}</td><td>${esc(a.user)}</td>
    <td>${esc(a.action_label || a.action)}</td><td class="mut" title="${esc(a.entity || '')}">${esc(a.entity_label || a.entity || '')}${a.detail ? ' · ' + esc(String(a.detail)).slice(0,60) : ''}</td></tr>`).join('')}</table></div>` : ''}
  <h2>Переиспользование компонентов</h2>
  <div class="card"><table><tr><th>Компонент</th><th>Статус</th><th>Используют сервисов</th></tr>
  ${d.component_usage.map(c=>`<tr><td>${esc(c.name)}</td><td>${statusB(c.status)}</td><td><b>${c.used_by}</b>${c.used_by ? '' : ' <span class="small mut">— нет потребителей</span>'}</td></tr>`).join('')}
  </table></div>
  <footer>DeepArch MVP · BR-01…37 · источники: Architecture Definition Set (Confluence DA), авто-проверка готовности к ревью, матрица типов проектов</footer>`;
}

/* ---------- services ---------- */
async function viewServices(){
  const list = await api('/services'+(S.showArchived?'?include_archived=1':''));
  $('#view').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center">
    <h1>Реестр сервисов</h1>
    <div style="display:flex;gap:10px;align-items:center">
      <label class="small mut" style="cursor:pointer"><input type="checkbox" ${S.showArchived?'checked':''}
        onchange="S.showArchived=this.checked;viewServices()"> показать архив</label>
      <button onclick="formService()" ${canCreateSvc()?'':'disabled title="Создание сервисов: team_lead, domain_expert, admin"'}>+ Сервис</button></div></div>
  <p class="mut">Карточка сервиса (BR-01, пункт 10 чек-листа) · тип проекта определяет обязательный набор артефактов</p>
  <div class="card" style="margin-top:16px"><table><tr><th>Сервис</th><th>Тип проекта</th><th>Владелец / архитектор</th><th>Готовность</th><th>Ревью</th><th>CMDB</th></tr>
  ${list.map(s=>`<tr><td><a class="lnk" href="#/service/${s.id}"><b>${esc(s.name)}</b></a>${s.lifecycle==='decommissioned'?' <span class="badge b-decommissioned">выведен</span>':''}<div class="small mut">${esc(s.code)} · ${esc(s.domain||'—')}</div></td>
    <td class="small">${esc(S.standard.project_types[s.project_type]?.title||s.project_type)}</td>
    <td class="small">${esc(s.owner||'—')} / ${esc(s.architect||'—')}</td>
    <td><div class="bar" style="width:110px"><i style="width:${s.last_score||0}%"></i></div><span class="small mut">${s.last_score||0}%</span></td>
    <td>${statusB(s.review_status)}</td>
    <td class="small">${s.cmdb_id?`<code>${esc(s.cmdb_id)}</code>`:'<span class="mut">—</span>'}</td></tr>`).join('')}
  </table></div>`;
}
async function setLifecycle(id, lc){
  await api('/services/'+id, {method:'PATCH', body: JSON.stringify({lifecycle:lc})});
  toast(lc==='decommissioned' ? 'Сервис выведен из эксплуатации (архив)' : 'Сервис возвращён в работу');
  viewService(id,'card');
}
async function deleteService(id){
  const s = await api('/services/'+id).catch(()=>null);
  if(!s) return;
  const code = prompt(`Необратимо удалить сервис ${s.name} и ВСЕ его данные (артефакты, C4, ревью, техдолг)?\nДля подтверждения введите код сервиса: ${s.code}`);
  if(code===null) return;
  try{
    await api('/services/'+id, {method:'DELETE', body: JSON.stringify({confirm:code.trim()})});
    toast('Сервис удалён'); location.hash = '#/services'; viewServices();
  }catch(e){ toast(e.message, true); }
}
function formService(){
  const opts = Object.entries(S.standard.project_types).map(([k,v])=>`<option value="${k}">${esc(v.title)}</option>`).join('');
  openModal('Service Factory — новый сервис (BR-45…47)', `
    <p class="small mut">Генерирует стартовый архитектурный пакет: все артефакты по шаблонам стандарта
    (${S.standard.artifacts.length} шт.) и подключение всех approved-компонентов каталога (compliance by construction).
    Готовность к ревью проверяется автоматически.</p>
    <div class="grid g2"><div><label>Код (напр. MPR)</label><input id="f-code"></div>
    <div><label>Название</label><input id="f-name"></div></div>
    <div class="grid g2"><div><label>Тип проекта</label><select id="f-pt">${opts}</select></div>
    <div><label>Домен</label><input id="f-domain"></div></div>
    <div class="grid g2"><div><label>Владелец</label><input id="f-owner" value="${esc(S.user.username)}"></div>
    <div><label>Архитектор</label><input id="f-arch" value="${esc(S.user.username)}"></div></div>
    <div style="margin-top:10px"><label>Из документа — ТЗ / письмо / описание задачи (Design Session)</label>
    <textarea id="f-doc" style="min-height:90px" placeholder="Вставьте текст — извлечём черновик карточки и требования (advisory, проверьте перед созданием)"></textarea></div>
    <div class="btnrow"><button class="sec" onclick="extractFromDoc()">⎘ Заполнить из документа</button></div>
    <div class="btnrow"><button onclick="createService()">Сгенерировать пакет</button>
    <button class="sec" onclick="closeModal()">Отмена</button></div>`);
}
let _REQ_DRAFT = [];  // требования, разобранные из документа до создания сервиса
async function extractFromDoc(){
  const text = $('#f-doc').value.trim();
  if(!text){ toast('Вставьте текст документа', true); return; }
  const btn = [...document.querySelectorAll('#modal button')].find(b=>b.textContent.includes('Заполнить из документа'));
  if(btn){ btn.disabled = true; btn.textContent = '⏳ Извлекаю…'; }
  try{
    const r = await api('/ai/service-extract', {method:'POST', body: JSON.stringify({text})});
    const d = r.draft || {};
    if(d.code) $('#f-code').value = d.code;
    if(d.name) $('#f-name').value = d.name;
    if(d.domain) $('#f-domain').value = d.domain;
    if(d.project_type && S.standard.project_types[d.project_type]) $('#f-pt').value = d.project_type;
    _REQ_DRAFT = (d.requirements||[]).map(x=>({req_type: x.req_type || (String(x.type||'')[0]==='Н'?'nonfunc':'func'),
                                               text: x.text||''})).filter(x=>x.text);
    toast(`Извлечено (${r.provider}): ${_REQ_DRAFT.length} требований. Проверьте поля — решение за вами.`);
  }catch(e){ toast(esc(e.message), true); }
  finally{ if(btn){ btn.disabled = false; btn.textContent = '⎘ Заполнить из документа'; } }
}
async function createService(){
  try{
    const r = await api('/factory/scaffold', {method:'POST', body: JSON.stringify({
      code:$('#f-code').value, name:$('#f-name').value, project_type:$('#f-pt').value,
      domain:$('#f-domain').value, owner:$('#f-owner').value, architect:$('#f-arch').value})});
    let reqNote = '';
    if(_REQ_DRAFT.length){
      try{
        const ri = await api('/services/'+r.id+'/requirements/import',
                             {method:'POST', body: JSON.stringify({items:_REQ_DRAFT})});
        reqNote = `<p class="small mut">Импортировано требований из документа: <b>${ri.created.length}</b>.</p>`;
      }catch(e){ reqNote = `<p class="small" style="color:var(--bad)">Требования не импортированы: ${esc(e.message)} — добавьте вручную на вкладке «Требования».</p>`; }
      _REQ_DRAFT = [];
    }
    closeModal();
    openModal(`Сервис ${esc(r.code)} создан`, `
      <p class="small mut">Сгенерировано: ${r.artifacts} артефактов по шаблонам стандарта ·
      подключено компонентов: ${r.components_attached.length}
      (${esc(r.components_attached.join(', ')||'—')}).</p>${reqNote}
      <h2 style="margin:10px 0 4px">Next steps</h2>
      <ol class="small">${r.next_steps.map(s=>`<li style="margin:4px 0">${esc(s)}</li>`).join('')}</ol>
      <div class="btnrow"><button onclick="closeModal();location.hash='#/service/${r.id}'">Открыть сервис</button></div>`);
    toast(`Пакет для ${esc(r.code)} сгенерирован Service Factory`);
  }catch(e){ toast(esc(e.message), true); }
}

/* ---------- service detail ---------- */
const ARTIFACT_TAB = () => ['artifacts','Артефакты' + (S.standard ? ` (${S.standard.artifacts.length})` : '')]; // число видов артефактов — из стандарта, не хардкод
const TABS = [['card','Карточка'],ARTIFACT_TAB(),['review','Ревью'],['components','Компоненты']]; // базовый список (полный собирается в viewService)
let SERVICE = null;
let _VS_GEN = 0;                    // защита от гонки: у каждого вызова viewService свой номер
async function viewService(id, tab='card'){
  if(tab === 'check'){                          // self-check интегрирован в «Ревью» — старые ссылки работают
    location.hash = `#/service/${id}/review`; return;
  }
  if(tab === 'diagrams'){                       // «Диаграммы» слиты в «Проектирование» — старые ссылки работают
    location.hash = `#/service/${id}/design`; return;
  }
  const gen = ++_VS_GEN;
  const s = await api('/services/'+id);
  if(gen !== _VS_GEN) return;       // пока летел запрос, навигация ушла дальше — рендер устарел
  SERVICE = s;
  const active = tab||'card';
  const tabs = [['card','Карточка'],
    ['reqs', 'Требования' + (s.requirements?.length ? ` (${s.requirements.length})` : '')],
    ['design', 'Проектирование'],
    ARTIFACT_TAB(),['review','Ревью'],['components','Компоненты'],
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
  ({card:tabCard, reqs:tabReqs, design:tabDesign, artifacts:tabArtifacts, review:tabReview,
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
const _stepLink = (sid, t) =>
  /Заполнить артефакты/.test(t) ? `#/service/${sid}/artifacts` :
  /C4-модель/.test(t) ? `#/service/${sid}/design` :
  /ревью/i.test(t) ? `#/service/${sid}/review` :
  `#/service/${sid}/review`;
function tabCard(s){
  const chk = s.checklist_runs[0];
  // свёрка сигналов: self-check пройден, но next_steps видят незаполненные артефакты
  const stepsFill = (s.next_steps||[]).some(t=>/Заполнить артефакты/.test(t));
  const mismatch = chk && !chk.mandatory_missing && (chk.score_pct||0) >= 100 && stepsFill;
  const ed = canEditSvc(s);
  const dis = ed ? '' : 'disabled';
  $('#tabbody').innerHTML = `<div class="grid g2">
  <div class="card vio"><h2 style="margin-top:0">Карточка сервиса ${ed?'':'<span class="badge b-draft">только просмотр</span>'}</h2>
    <label>Название</label><input id="c-name" value="${esc(s.name)}" ${dis}>
    <div class="grid g2"><div><label>Код</label><input value="${esc(s.code)}" disabled></div>
    <div><label>Домен</label><input id="c-domain" value="${esc(s.domain||'')}" ${dis}></div></div>
    <div class="grid g2"><div><label>Владелец</label><input id="c-owner" value="${esc(s.owner||'')}" ${dis}></div>
    <div><label>Архитектор</label><input id="c-architect" value="${esc(s.architect||'')}" ${dis}></div></div>
    <div class="grid g2"><div><label>Тип проекта</label><select id="c-pt" ${dis}>${Object.entries(S.standard.project_types).map(([k,v])=>`<option value="${k}" ${k===s.project_type?'selected':''}>${esc(v.title)}</option>`).join('')}</select></div>
    <div><label>Жизненный цикл</label><select id="c-lc" ${dis}>${['design','development','production','decommissioned'].map(l=>`<option ${l===s.lifecycle?'selected':''}>${l}</option>`).join('')}</select></div></div>
    <label>CMDB ID</label><input id="c-cmdb" value="${esc(s.cmdb_id||'')}" placeholder="CI из CMDB (BR-20)" ${dis}>
    <div class="btnrow"><button onclick="saveCard(${s.id})" ${ed?'':'disabled'}>Сохранить</button>
    <button class="cya" onclick="exportCatalog(${s.id})">Экспорт catalog-info.yaml (BR-21)</button>
    <button class="sec" onclick="askAssistantAbout(${s.id})">▲ Спросить ассистента</button>
    ${['admin','domain_expert'].includes(S.user.role) ? (s.lifecycle==='decommissioned'
      ? `<button class="sec" onclick="setLifecycle(${s.id},'production')">↩ Вернуть в работу</button>`
      : `<button class="sec" onclick="setLifecycle(${s.id},'decommissioned')">🗄 Вывести из эксплуатации</button>`) : ''}
    ${S.user.role==='admin' ? `<button class="sec" style="color:var(--bad);border-color:var(--bad-line)" onclick="deleteService(${s.id})">🗑 Удалить</button>` : ''}
    </div></div>
  <div class="card"><h2 style="margin-top:0">Обязательные артефакты для типа</h2>
    <p class="mut small">Матрица «Минимальные наборы по типам проектов» из Навигатора стандарта</p>
    ${s.mandatory_artifacts.map(k=>`<span class="chip">● ${esc(S.standard.artifacts.find(a=>a.kind===k)?.title||k)}</span>`).join('')||'<span class="mut">—</span>'}
    <h2>Последняя проверка готовности</h2>
    ${chk?`<div class="kpi">${chk.score_pct}%</div>
      <p class="small mut">обязательных не закрыто: <b style="color:${chk.mandatory_missing?'var(--bad)':'var(--ok)'}">${chk.mandatory_missing}</b> · ${new Date(chk.created_at*1000).toLocaleDateString('ru')}</p>`:'<p class="mut">— не проводилась (фиксируется при отправке на ревью)</p>'}
  </div>
  <div class="card"><h2 style="margin-top:0">Следующие шаги</h2>
    <p class="mut small">Живой список: пересчитывается по фактическому состоянию сервиса · клик ведёт на нужную вкладку</p>
    ${mismatch?`<p class="small" style="background:var(--warn-soft);border:1px solid var(--warn-line);color:var(--warn);border-radius:8px;padding:8px 11px;margin-bottom:8px">⚠ Последняя проверка показывала ${chk.score_pct}%, но часть артефактов теперь пуста — актуальная готовность в <a class="lnk" href="#/service/${s.id}/review">«Ревью»</a></p>`:''}
    <ol class="small">${(s.next_steps||[]).map(t=>`<li style="margin:5px 0"><a class="lnk" href="${_stepLink(s.id,t)}">${esc(t)} →</a></li>`).join('')}</ol>
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

/* Виды артефактов, для которых диаграмма осмысленна: у остальных поле диаграммы
   скрыто (шум, растягивающий карточку), существующий diagram_code сохраняется */
const DIAG_KINDS = ['vision_c4', 'deployment', 'data_model'];
let ART_JUMP = null;              // переход из галереи «Проектирования»: открыть и проскроллить
const _artFilled = k => !!(k && (((k.content_md||'').trim()) || ((k.diagram_code||'').trim())));

function tabArtifacts(s){
  const ed = canEditSvc(s);
  const arts = S.standard.artifacts;
  const byKind = Object.fromEntries(s.artifacts.map(a=>[a.kind,a]));
  const mandatoryCount = s.mandatory_artifacts.filter(k => {
    const c = byKind[k]; return !_artFilled(c);      // как в readiness: текст ИЛИ диаграмма
  }).length;
  $('#tabbody').innerHTML = `
  <div class="card" style="margin-bottom:14px">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
      <div><b>Артефакты сервиса</b>
        <span class="small mut">· обязательных для типа: ${s.mandatory_artifacts.length}${mandatoryCount?`, без контента: <b style="color:var(--bad)">${mandatoryCount}</b>`:''}</span>
      </div>
      <button class="cya" onclick="scaffoldArtifacts(${s.id}, this)" ${ed?'':'disabled title="Нет прав на изменение сервиса"'}>⚡ Сгенерировать скелеты обязательных артефактов</button>
    </div>
    <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
      ${arts.map(a=>{
        const f = _artFilled(byKind[a.kind]);
        const mand = s.mandatory_artifacts.includes(a.kind);
        const st = f ? '<span style="color:#047857">✓</span>'
          : mand ? '<span style="color:#be123c">✗</span>' : '<span style="color:#52525b">○</span>';
        return `<button class="chip art-idx" onclick="artJump('${a.kind}')" title="Перейти к артефакту">${st} ${esc(a.title)}</button>`;
      }).join('')}
    </div>
  </div>` + arts.map(a=>{
    const cur = byKind[a.kind]||{};
    const mandatory = s.mandatory_artifacts.includes(a.kind);
    const dis = ed ? '' : 'disabled';
    const f = _artFilled(cur);
    const diagKind = DIAG_KINDS.includes(a.kind);
    // подсказка (решение 2026-11-07): у обязательных пустых диаграмм AI-черновик — старт, а не опция
    const diagBoost = mandatory && !f && diagKind && a.kind !== 'vision_c4';
    const open = !f && mandatory;   // пустой обязательный раскрыт; опциональный пустой — свёрнут,
                                    // чтобы пустой draft не превращался обратно в простыню (ревью 2026-11-07)
    return `<details class="art-card" id="art-${a.kind}" ${open?'open':''}>
    <summary>
      <b>${esc(a.title)}</b> ${mandatory?'<span class="badge b-mandatory">обязательный для типа</span>':''}
      ${f?'<span class="chip" style="background:#ecfdf5;color:#047857">✓ заполнен</span>'
        :`<span class="chip" style="background:${mandatory?'#fff1f2;color:#be123c':'var(--surface2);color:#52525b'}">${mandatory?'✗ пуст · блокер готовности':'○ пуст'}</span>`}
      <span class="small mut" style="margin-left:auto">v${cur.version||1} · ${cur.updated_by?esc(cur.updated_by):'—'}</span>
    </summary>
    <div class="small mut" style="margin:8px 0 0">${esc(a.question)}</div>
    <div class="split">
      <div>
        <label style="margin-top:10px">Описание (markdown)</label>
        <textarea id="a-${a.kind}" placeholder="Что фиксируем: ${esc(a.captures)}" ${dis}>${esc(cur.content_md||'')}</textarea>
        ${diagKind?`
        ${a.kind==='vision_c4'?'<p class="small mut" style="margin:6px 0 0">Mermaid-исходник L1/L2 — производная C4-модели из вкладки «Проектирование» и обновляется ею автоматически; правьте модель там.</p>':''}
        <label>Исходник диаграммы (Mermaid: C4Context / C4Container / C4Deployment / erDiagram)</label>
        <textarea class="diagcode" id="d-${a.kind}" oninput="liveDiagram(this)" ${dis} ${a.kind==='vision_c4'?'readonly title="Синхронизируется из «Проектирования»"':''} placeholder="${a.kind==='vision_c4'?'C4Context · Person · System · Rel · SHOW_LEGEND()':a.kind==='data_model'?'erDiagram · USER ||--o{ ORDER : places':'C4Deployment · Deployment_Node → Container'}">${esc(cur.diagram_code||'')}</textarea>
        ${diagBoost?'<p class="small mut" style="margin:6px 0 0">Обязателен для типа — начните с «✨ AI-черновик»: он сгенерирует и описание, и черновик диаграммы, затем правьте текст.</p>':''}`
        :''}
      </div>
      <div>
        ${diagKind?`<label style="margin-top:10px">Превью диаграммы (live)</label><div class="diag" id="dv-${a.kind}"></div>`:''}
        <div class="small mut" style="margin-top:6px">${esc(a.required_artifacts.join(' · '))}</div>
      </div>
    </div>
    <div class="btnrow">
      <label style="margin:0;flex:1"><input id="u-${a.kind}" placeholder="Ссылка на внешнее доказательство (Confluence, репозиторий) — необязательно" value="${esc(cur.source_url||'')}" ${dis}></label>
      <button class="sec" onclick="aiDraft(${s.id},'${a.kind}',this)" ${dis}>✨ AI-черновик${diagBoost?' + диаграмма':''}</button>
      <button onclick="saveArt(${s.id},'${a.kind}')" ${dis}>Сохранить (v${(cur.version||1)+1})</button>
    </div></details>`;
  }).join('');
  // первичный рендер превью — только у видов с диаграммами
  arts.forEach(a => {
    if(DIAG_KINDS.includes(a.kind))
      renderDiag(document.getElementById('dv-'+a.kind), (byKind[a.kind]||{}).diagram_code||'');
  });
  if(ART_JUMP){ const k = ART_JUMP; ART_JUMP = null; artJump(k); }
}
/* Переход к артефакту из индекса/галереи: раскрыть карточку и проскроллить к ней */
function artJump(kind){
  const d = document.getElementById('art-'+kind);
  if(!d) return;
  d.open = true;
  d.scrollIntoView({behavior:'smooth', block:'start'});
}
async function saveArt(sid, kind){
  const dEl = document.getElementById('d-'+kind);
  const body = {content_md:$(`#a-${kind}`).value, source_url:$(`#u-${kind}`).value};
  if(dEl && !dEl.readOnly) body.diagram_code = dEl.value;   // vision_c4 — производная редактора; у остальных поле отсутствует
  await api(`/services/${sid}/artifacts/${kind}`, {method:'PUT', body: JSON.stringify(body)});
  toast('Артефакт сохранён, версия поднята');
  // после перерисовки карточка заполненного артефакта свернётся по умолчанию —
  // возвращаем пользователя к сохранённой карточке, а не к стене/индексу
  ART_JUMP = kind;
  viewService(sid,'artifacts');
}
async function aiDraft(sid, kind, btn){
  const old = btn ? btn.textContent : '';
  // перезапись несохранённой диаграммы — с подтверждением (ревью 2026-11-07)
  const dEl = document.getElementById('d-'+kind);
  if(dEl && !dEl.readOnly && dEl.value.trim() &&
     !confirm('Текущая (несохранённая) диаграмма будет заменена AI-черновиком. Продолжить?')){
    if(btn){ btn.disabled = false; btn.textContent = old; }
    return;
  }
  if(btn){ btn.disabled = true; btn.textContent = '✨ Генерирую…'; }
  try{
    const r = await api('/ai/draft', {method:'POST', body: JSON.stringify({
      service_id:sid, kind, model: chatModelSel()})});
    $(`#a-${kind}`).value = r.content_md;
    let diagNote = '';
    const dEl = document.getElementById('d-'+kind);
    if(r.diagram_code && dEl && !dEl.readOnly){
      dEl.value = r.diagram_code;                       // черновик диаграммы (deployment/data_model)
      renderDiag(document.getElementById('dv-'+kind), r.diagram_code);
      diagNote = ' + черновик диаграммы';
    }
    toast(r.provider === 'ai-buddy'
      ? `AI-черновик${diagNote} (${esc(r.model||'AI-Buddy')}) вставлен — <b>требует подтверждения автора</b> (BR-28/33)`
      : esc((r.note || 'Черновик вставлен — требует подтверждения автора (BR-28/33)')) + diagNote);
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


function tabReview(s){
  const canSend = canEditSvc(s);                       // бэкенд: can_edit_service
  const canDecide = !!s.can_decide_review && s.review_status==='in_review' && s.reviews.find(r=>r.status==='in_review');
  const open = s.reviews.find(r=>r.status==='in_review');
  $('#tabbody').innerHTML = `
  <div class="card vio" style="margin-bottom:14px"><h2 style="margin-top:0">Готовность к ревью</h2>
    <div id="svc-readiness"><p class="small mut">Считаю по данным сервиса…</p></div>
    <p class="small mut" style="margin:6px 0 10px">Гейт — формальная полнота артефактов; AI-ревью —
    содержательные риски и несоответствия. Advisory (BR-33): находки не блокируют отправку —
    решение за автором и ревьюером.</p>
    <div class="btnrow">
      ${s.review_status==='in_review'
        ? `<span class="chip">Ревью идёт · запрошено <b>${esc(open?.requested_by||'')}</b></span>`
        : `<button id="btn-send-review" onclick="requestReview(${s.id})" ${canSend?'':'disabled'}>Отправить на ревью</button>
           <button class="sec" id="btn-ai-review" onclick="aiReview(${s.id})" ${canSend?'':'disabled'}
             title="Предварительное AI-ревью пакета до отправки (advisory, BR-33)">🧠 AI-ревью</button>
           ${canSend?'':'<span class="small mut">Отправка на ревью: владелец/архитектор или product-группа</span>'}`}
      ${canDecide?`
        <button class="btn-ok" onclick="decide(${open.id},'approved')">✓ Approved</button>
        <button class="btn-bad" onclick="decide(${open.id},'changes_requested')">✗ Changes requested</button>`:''}
    </div>
    ${canDecide?`<textarea class="sm" id="rv-comment" placeholder="Комментарий решения (необязательно)"></textarea>`:''}
    <div id="svc-aireview" style="margin-top:12px"></div>
  </div>
  <div class="card"><table><tr><th>#</th><th>Запрошено</th><th>Ревьюер</th><th>Решение</th><th>Комментарий</th></tr>
  ${s.reviews.map(r=>`<tr><td>${r.id}</td>
    <td class="small">${esc(r.requested_by)}<br><span class="mut">${new Date(r.requested_at*1000).toLocaleString('ru')}</span></td>
    <td>${esc(r.reviewer||'—')}</td><td>${statusB(r.status)}</td><td class="small mut">${esc(r.comment||'')}</td></tr>`).join('')||'<tr><td colspan=5 class="mut">Ревью ещё не было</td></tr>'}
  </table></div>`;
  svcReadiness(s.id);
  svcAiReviewLoad(s.id);
}
/* Живой ответ на «всё ли у меня есть перед отправкой на ревью?» — расчёт бэкенда по данным DeepArch */
async function svcReadiness(sid){
  const el = document.getElementById('svc-readiness'); if(!el) return;
  try{
    const r = await api(`/services/${sid}/readiness`);
    const chip = i => i.grade === 'E'
      ? `<span class="chip" style="background:#ecfdf5;color:#047857">✓ <a class="lnk" style="color:inherit" href="${i.link}">${esc(i.item)}</a></span>`
      : `<span class="chip" style="background:${i.blocking?'#fff1f2;color:#be123c':'var(--surface2);color:#52525b'}">
         ${i.blocking?'✗':'○'} <a class="lnk" style="color:inherit" href="${i.link}">${esc(i.item)}</a>${i.blocking?' · блокер':i.matrix==='desired'?' · желательный':' · не обязателен'}</span>`;
    const missing = r.items.filter(i => i.blocking);
    const approved = SERVICE && SERVICE.review_status==='approved';
    el.innerHTML = `
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0 10px">
        <span class="badge ${r.ready?'b-approved':'b-draft'}" style="font-size:13px">
          ${r.ready?'✓ Готов к отправке на ревью':'✗ Не готов: не закрыто обязательных — '+missing.length}</span>
        <span id="ai-verdict"></span>
        <span class="small mut">текущая готовность ${r.score_pct}%</span>
        ${r.last_run?`<span class="small mut">фиксация при последней отправке: ${new Date(r.last_run.created_at*1000).toLocaleDateString('ru')} — ${r.last_run.score_pct}% (${esc(r.last_run.created_by||'')})</span>`:''}
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${r.items.map(chip).join('')}</div>
      ${r.ready ? '' : `<p class="small" style="margin:10px 0 0">Отправка заблокируется на: <b>${r.blockers.map(esc).join('; ')}</b> — заполните соответствующие артефакты.</p>`}
      ${approved?`<p class="small" style="margin:10px 0 0">Сервис уже approved — повторная отправка перезапустит процесс ревью.</p>`:''}`;
    paintAiVerdict();     // слот уже в DOM: закрашиваем вердикт AI (устраняет гонку двух async-рендеров)
    const btn = document.getElementById('btn-send-review');
    if(btn && !r.ready){
      btn.disabled = true;
      btn.title = 'Не закрыто обязательных пунктов: ' + r.blockers.join('; ');
    }
  }catch(e){ el.innerHTML = `<p class="small mut">Готовность недоступна: ${esc(e.message)}</p>`; }
}
/* ---------- AI-ревью до отправки (advisory, BR-33) ---------- */
let AI_LAST = null;      // последний прогон для текущего сервиса (кэш вердикта между async-рендерами)
let AI_SID = null;       // сервис текущего прогона (кнопки «Исправить» должны знать цель)
const AI_KIND = {противоречие:'Противоречие', риск:'Риск', пробел:'Не хватает', несоответствие:'Расхождение'};
function paintAiVerdict(){
  /* Вердикт AI-ревью живёт в строке рядом с гейтом готовности — один сводный статус */
  const slot = document.getElementById('ai-verdict'); if(!slot) return;
  if(!AI_LAST){
    slot.innerHTML = `<span class="chip" style="background:var(--surface2);color:#52525b">🧠 AI-ревью: ещё не проводилось</span>`;
    return;
  }
  const warn = AI_LAST.findings.filter(f=>f.severity==='warning').length;
  slot.innerHTML = `<span class="chip" style="background:#eef2ff;color:#4338ca">🧠 AI-ревью: ${warn?`⚠ серьёзных — ${warn}`:'✓ серьёзных нет'} из ${AI_LAST.findings.length}</span>`;
}
function aiGroupFindings(fs){
  /* Однотипные формальные находки («нет ссылки на исходник» ×7) схлопываем в одну раскрываемую */
  const groups = [];
  const key = f => `${f.layer}|${f.kind}|${f.severity}|${(f.detail||'').replace(/«[^»]+»/g,'«…»')}`;
  const map = {};
  for(const f of fs){
    const k = key(f);
    if(map[k] && f.layer==='formal') map[k].items.push(f);
    else { const g = {lead:f, items:[f]}; map[k]=g; groups.push(g); }
  }
  return groups;
}
function aiSection(title, cls, findings){
  if(!findings.length) return '';
  const card = f => {
    const kind = esc(AI_KIND[f.kind] || f.kind);
    const art = esc(f.artifact || f.artifact_kind || '');
    const aiTag = f.layer==='llm' ? ` <span class="aireview-ai">AI-анализ</span>` : '';
    const stdTag = f.std ? ` <span class="aireview-std" title="Пункт корпоративного стандарта">📖 ${esc(f.std)}</span>` : '';
    const idx = AI_LAST ? AI_LAST.findings.indexOf(f) : -1;
    const fixAct = (f.fix && idx >= 0 && AI_SID) ? `<div class="aireview-act">
      <button class="sec aireview-fixbtn" onclick="aiReviewFix(${AI_SID},${idx})"
        title="AI подготовит черновик правки артефакта с учётом находки — примените после проверки (advisory)">🔧 Исправить</button>
      ${f.target?`<a class="lnk small" href="${esc(f.target)}">Перейти →</a>`:''}</div>` : '';
    const inner = `<b>${kind}${art?` · ${art}`:''}: ${esc(f.title)}</b>${aiTag}${stdTag}
      ${f.detail?`<div class="small">${esc(f.detail)}</div>`:''}
      ${f.evidence?`<div class="small mut">Доказательство: ${esc(f.evidence)}</div>`:''}`;
    const cls2 = `aireview-item${f.severity==='warning'?' aireview-warn':''}`;
    return (f.fix && idx >= 0 && AI_SID)
      ? `<div class="${cls2}">${inner}${fixAct}</div>`
      : f.target
        ? `<a class="${cls2} lnk" href="${esc(f.target)}">${inner}</a>`
        : `<div class="${cls2}">${inner}</div>`;
  };
  const groupCard = g => g.items.length === 1 ? card(g.lead) : (() => {
    const lead = g.lead;
    const generic = lead.title.replace(/«[^»]+»/g, '«…»');
    const list = g.items.map(f => f.artifact || f.artifact_kind
      ? `<li><a class="lnk" href="${esc(f.target||'#')}">${esc(f.artifact || f.artifact_kind)}</a></li>`
      : '').join('');
    return `<details class="aireview-item${lead.severity==='warning'?' aireview-warn':''}">
      <summary><b>${esc(AI_KIND[lead.kind]||lead.kind)}: ${esc(generic)}</b> <span class="mut">· ${g.items.length} артефактов</span></summary>
      ${lead.detail?`<div class="small" style="margin-top:4px">${esc(lead.detail)}</div>`:''}
      <ul class="small" style="margin:6px 0 0">${list}</ul></details>`;
  })();
  return `<div class="aireview-sec"><div class="aireview-h ${cls}">${title}</div>${aiGroupFindings(findings).map(groupCard).join('')}</div>`;
}
function renderAiReview(el, r){
  if(!r){
    el.innerHTML = `<p class="small mut">🧠 AI-ревью ещё не проводилось — запустите перед отправкой,
      чтобы поймать замечания заранее и не получить changes_requested с первого раза.</p>`;
    return;
  }
  const warn = r.findings.filter(f=>f.severity==='warning');
  const info = r.findings.filter(f=>f.severity!=='warning');
  const dyn = r.previous ? ` · прошлый прогон: ${r.previous.total} → ${r.findings.length} находок` : '';
  el.innerHTML = `
    <div id="svc-aireview-fix"></div>
    ${r.note?`<p class="small mut" style="margin:0 0 8px">${esc(r.note)}</p>`:''}
    ${aiSection(`⚠ Серьёзные — ${warn.length}`, 'aireview-h-warn', warn)}
    ${aiSection(`ℹ️ Замечания — ${info.length}`, 'aireview-h-info', info)}
    ${r.findings.length ? '' : '<p class="small" style="margin:0 0 6px">Находок нет — формальные проверки и AI-анализ чистые.</p>'}
    <p class="small mut" style="margin:8px 0 0">Прогон ${new Date(r.created_at*1000).toLocaleString('ru')} · ${esc(r.created_by||'')}${dyn}.
    Advisory (BR-33): находки — рекомендации, отправку не блокируют.</p>`;
}
async function svcAiReviewLoad(sid){
  AI_LAST = null; AI_SID = sid; paintAiVerdict();   // чужой вердикт не переживает смену сервиса
  const el = document.getElementById('svc-aireview'); if(!el) return;
  try{
    const r = await api(`/services/${sid}/ai-review`);
    if(!el.isConnected) return;
    AI_LAST = r; paintAiVerdict();
    renderAiReview(el, r);            // null — ещё не проводилось: показываем подсказку
  }catch(e){ el.innerHTML = `<p class="small mut">AI-ревью недоступно: ${esc(e.message)}</p>`; }
}
async function aiReview(sid){
  const btn = document.getElementById('btn-ai-review');
  const el = document.getElementById('svc-aireview');   // до await: вкладка могла смениться за время LLM (~30 с)
  if(btn){ btn.disabled = true; btn.textContent = '⏳ AI-ревью…'; }
  try{
    const r = await api(`/services/${sid}/ai-review`, {method:'POST', body:'{}'});
    if(!el || !el.isConnected) return;   // ответ устаревшего прогона не рендерим
    AI_LAST = r; paintAiVerdict();
    renderAiReview(el, r);
    const warn = r.findings.filter(f=>f.severity==='warning').length;
    toast(warn ? `AI-ревью: серьёзных находок — <b>${warn}</b> (см. список ниже)`
               : 'AI-ревью: серьёзных находок нет');
  }catch(e){ toast(esc(e.message), true); }
  if(btn){ btn.disabled = false; btn.textContent = '🧠 AI-ревью'; }
}
async function aiReviewFix(sid, idx){
  const f = ((AI_LAST||{}).findings||[])[idx]; if(!f) return;
  const slot = document.getElementById('svc-aireview-fix'); if(!slot) return;
  slot.innerHTML = `<div class="aireview-fixbox"><p class="small mut">⏳ Готовлю предложение исправления (LLM, до ~1 мин)…</p></div>`;
  try{
    const r = await api(`/services/${sid}/ai-review/fix`, {method:'POST', body: JSON.stringify({
      kind:f.kind, artifact_kind:f.artifact_kind, title:f.title, detail:f.detail,
      std:f.std||'', severity:f.severity, layer:f.layer||''})});
    if(!slot.isConnected) return;   // вкладка сменилась за время LLM
    const before = r.before||{}, after = r.after||{};
    slot.innerHTML = `
      <div class="aireview-fixbox">
        <div class="aireview-h aireview-h-info">🔧 Предложение исправления · ${esc(r.artifact||r.artifact_kind||'')}</div>
        <p class="small mut" style="margin:4px 0 8px">${esc(r.note||'')} Advisory (BR-33): правка применяется только после вашего подтверждения, ничего не сохраняется до кнопки «Применить».</p>
        <label class="small"><b>Новый текст артефакта</b> (можно отредактировать перед применением):</label>
        <textarea id="aifix-content" class="aifix-ta">${esc(after.content_md||'')}</textarea>
        ${after.diagram_code?`<label class="small"><b>Mermaid-диаграмма:</b></label>
        <textarea id="aifix-diagram" class="aifix-ta">${esc(after.diagram_code)}</textarea>`:''}
        ${before.content_md?`<details class="small" style="margin:4px 0 0"><summary>Текущий текст артефакта (до правки)</summary><pre class="aifix-pre">${esc(before.content_md)}</pre></details>`:''}
        <div style="display:flex;gap:8px;margin-top:10px">
          <button class="pri" onclick="aiReviewFixApply(${sid},'${esc(r.artifact_kind)}')">✓ Применить</button>
          <button class="sec" onclick="aiReviewFixCancel()">✕ Отмена</button>
        </div>
      </div>`;
    toast('Предложение готово — проверьте, при необходимости отредактируйте и примените');
  }catch(e){ slot.innerHTML = `<div class="aireview-fixbox"><p class="small">Не удалось подготовить предложение: ${esc(e.message)}</p></div>`; }
}
async function aiReviewFixApply(sid, kind){
  const content = document.getElementById('aifix-content'); if(!content) return;
  const diag = document.getElementById('aifix-diagram');
  try{
    await api(`/services/${sid}/artifacts/${kind}`, {method:'PUT', body: JSON.stringify(
      diag ? {content_md: content.value, diagram_code: diag.value} : {content_md: content.value})});
    toast('Исправление применено — перепрогоните 🧠 AI-ревью, чтобы обновить находки');
    aiReviewFixCancel();
  }catch(e){ toast(esc(e.message), true); }
}
function aiReviewFixCancel(){
  const s = document.getElementById('svc-aireview-fix'); if(s) s.innerHTML = '';
}
async function requestReview(sid){
  if(SERVICE && SERVICE.id===sid && SERVICE.review_status==='approved'
     && !confirm('Сервис уже approved — повторная отправка перезапустит процесс ревью. Продолжить?')) return;
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
    <td style="white-space:nowrap"><span class="badge ${d.dtype==='AD'?'b-changes_requested':'b-mandatory'}">${d.dtype}</span>
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
      <button onclick="runFitness(${s.id})" ${canEditSvc(s)?'':'disabled title="Нет прав на изменение сервиса"'}>▶ Прогнать проверки</button></div>
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
  const ed = canEditSvc(s);
  const nfr = s.nfr || {metrics:[]};
  $('#tabbody').innerHTML = `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2 style="margin-top:0">NFR-валидация: цель vs факт (BR-51…53)</h2>
      <button onclick="nfrExtract(${s.id})" ${ed?'':'disabled title="Нет прав на изменение сервиса"'}>⇣ Извлечь цели из артефакта NFR</button></div>
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
        <td><input id="nfr-act-${m.id}" type="number" step="any" value="${m.actual_value??''}" style="width:110px" placeholder="факт" ${ed?'':'disabled'}></td>
        <td><span class="badge ${VERDICT_BADGE[m.status]||'b-draft'}">${m.status}</span><div class="small mut">${esc(m.detail||'')}</div></td>
        <td class="small mut">${esc(m.source||'—')}</td>
        <td><button class="sec" onclick="nfrSave(${m.id})" ${ed?'':'disabled'}>Сохранить</button></td></tr>`).join('')}</table>`
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
  const ed = canEditSvc(s);
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
      <button class="cya" onclick="reqNfrDraft(${s.id}, this)" ${ed?'':'disabled title="Нет прав на изменение сервиса"'}>⇥ Сгенерировать NFR profile из НФТ</button>
      <span class="small mut">${nF} ФТ · ${nN} НФТ${uncovered?` · <b style="color:var(--bad)">не покрыто: ${uncovered}</b>`:''}</span>
    </div>
    <div style="margin:12px 0 6px"><button class="sec" onclick="reqToggleParse()" ${ed?'':'disabled'}>🧠 Вставить документ требований</button></div>
    <div id="req-parse" style="display:none">
      <textarea id="req-doc" rows="8" style="width:100%"
        placeholder="Вставьте текст ФТ/НФТ из Confluence, Jira или документа…"></textarea>
      <div class="btnrow"><button onclick="reqParse(${s.id})" ${ed?'':'disabled'}>🧠 Разобрать документ</button>
      <span class="small mut" id="req-parse-note"></span></div>
      <div id="req-preview"></div>
    </div>
    <label style="margin-top:12px">Добавить вручную</label>
    <div class="grid g2">
      <select id="req-type" ${ed?'':'disabled'}><option value="func">ФТ — функция</option><option value="nonfunc">НФТ — качество</option></select>
      <input id="req-src" placeholder="Источник: Confluence / Jira (ссылка)" ${ed?'':'disabled'}>
    </div>
    <textarea id="req-text" rows="2" style="width:100%;margin-top:6px" placeholder="Текст требования" ${ed?'':'disabled'}></textarea>
    <div class="btnrow"><button onclick="reqAdd(${s.id})" ${ed?'':'disabled title="Нет прав на изменение сервиса"'}>＋ Добавить требование</button></div>
  </div>
  <div class="card">
    <h2 style="margin-top:0">Реестр требований</h2>
    ${rs.length ? `<table><tr><th>ID</th><th>Требование</th><th>Статус</th><th>Покрытие</th><th></th></tr>
    ${rs.map(r => `<tr>
      <td><span class="badge ${REQ_TYPE_BADGE[r.req_type]}">${REQ_TYPE_RU[r.req_type]}</span>
          <div class="small mut" style="margin-top:2px"><b>${esc(r.ext_id||'')}</b>${r.source_url?`<br><a class="lnk" href="${esc(r.source_url)}" target="_blank">источник ↗</a>`:''}</div></td>
      <td style="max-width:340px">${esc(r.text)}</td>
      <td><select onchange="reqStatus(${r.id}, this.value)" ${ed?'':'disabled'}>
        ${['new','in_work','covered'].map(st => `<option value="${st}" ${st===r.status?'selected':''}>${REQ_STATUS_RU[st]}</option>`).join('')}
      </select></td>
      <td>${(r.covered_by||[]).length
        ? r.covered_by.map(k => `<span class="badge b-approved" title="${esc(artTitle(k))}">${esc(k)}</span>`).join(' ')
        : '<span class="badge b-N">не покрыто</span>'}</td>
      <td><button class="sec" onclick="reqDel(${r.id}, ${s.id})" title="Удалить" ${ed?'':'disabled'}>✕</button></td></tr>`).join('')}
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
const C4_W = 160, C4_H = 64, C4_GRID = 20;   // GRID — шаг сетки и привязки (snap)
const c4Snap = v => Math.round(v / C4_GRID) * C4_GRID;
const C4_VIEWS = {context: 'Контекст (L1)', container: 'Контейнеры (L2)', er: 'Модель данных (ER)'};
const ER_TYPES = [{t:'entity', ru:'Сущность', icon:'🗂️', fill:'#f0fdfa', line:'#0d9488', dash:''}];
const ER_CARD_RU = {'||--||': '1 — 1', '||--o{': '1 — N', '}o--||': 'N — 1', '}o--o{': 'N — M'};
let DSGN = {sid: null, models: {}, view: 'context', sel: null, selType: null, linkFrom: null,
            saveT: null, pending: null, zoom: 1};

const c4M = () => DSGN.models[DSGN.view];
const c4Node = id => c4M() && (c4M().nodes || []).find(n => n.id === id);
const c4Edge = id => c4M() && (c4M().edges || []).find(e => e.id === id);

async function tabDesign(s){
  c4FlushSave();                      // недосейвенный вид предыдущего сервиса уходит под своим {sid, view}
  DSGN.sid = s.id; DSGN.sel = null; DSGN.selType = null; c4CancelLink();
  DSGN.readonly = !canEditSvc(s);     // viewer/infosec/чужой сервис: без правок и автосейва
  const r = await api(`/services/${s.id}/c4`).catch(() => ({models: {}}));
  DSGN.models = r.models || {};
  for(const v of Object.keys(C4_VIEWS))
    if(!DSGN.models[v]) DSGN.models[v] = {nodes: [], edges: []};
  DSGN.view = DSGN.models.context.nodes.length ? 'context'
            : DSGN.models.container.nodes.length ? 'container'
            : DSGN.models.er.nodes.length ? 'er' : 'context';
  $('#tabbody').innerHTML = `
  <div class="card c4-toolbar">
    <div class="c4-toolbar-row">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <b>Проектирование архитектуры — C4 и ER</b>
        <button class="c4-help" onclick="c4HelpToggle(this)" title="Как работает проектирование"
          aria-expanded="false" aria-controls="c4-help">?</button>
        ${DSGN.readonly?'<span class="badge b-in_review small-badge">🔒 только просмотр</span>':''}
      </div>
      <div class="btnrow">
        <button class="c4-aibtn" onclick="c4AI('${DSGN.view}', this)" ${DSGN.readonly?'disabled title="Нет прав на изменение сервиса"':''}>🧠 AI-структура</button>
        <button class="sec" id="c4-previewbtn" onclick="c4Preview(this)">👁 Mermaid</button>
      </div>
    </div>
    <p class="c4-help-text small mut" id="c4-help" hidden>Сценарий 1 — рисуйте вручную палитрой слева.
      Сценарий 2 — «AI-структура» спроектирует модель из требований и фактов сервиса
      (для контейнеров — в согласии с уже сохранённой L1, для ER — из API-спецификации и БД из L2),
      затем правьте её же редактором.
      Модель хранится как JSON и при сохранении сама синхронизирует Mermaid-исходник
      в артефакты: C4 (L1/L2) — в «Видение (C4)», ER — в «Модель данных» —
      готовность к ревью и галерея диаграмм ниже видят их сразу.</p>
  </div>
  <div class="design-shell">
    <div class="c4-side">
      <b class="c4-cap">Палитра</b>
      <div class="c4-palette" id="c4-palette"></div>
      <p class="small mut" style="margin:auto 0 0;padding-top:10px">Модель хранится как JSON<br>и сохраняется автоматически.</p>
    </div>
    <div class="c4-main">
      <div class="c4-head">
        <div id="c4-chips" class="c4-chips"></div>
        <div class="c4-headbtns">
          <div class="c4-views" role="tablist">
            ${Object.entries(C4_VIEWS).map(([v, t]) =>
              `<button class="${v===DSGN.view?'c4-vact':''}" data-view="${v}" onclick="c4SetView('${v}')" role="tab">${t}</button>`).join('')}
          </div>
          <button class="sec c4-ibtn" id="c4-linkbtn" onclick="c4LinkMode()" title="Режим связи: кликните источник, затем цель">🔗</button>
          <button class="sec c4-ibtn" onclick="c4DeleteSel()" title="Удалить выбранное (Delete)">🗑</button>
          <span class="c4-zoom">
            <button onclick="c4Zoom(-1)" title="Уменьшить">−</button>
            <button class="c4-zlbl" id="c4-zlbl" onclick="c4Zoom(0)" title="Сбросить масштаб">100%</button>
            <button onclick="c4Zoom(1)" title="Увеличить">＋</button>
          </span>
        </div>
      </div>
      <div class="c4-canvas">
        <svg id="c4-svg" viewBox="0 0 960 560" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="c4-grid" width="20" height="20" patternUnits="userSpaceOnUse">
              <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#e2e8f0" stroke-width="1"/>
            </pattern>
            <marker id="c4-arrow" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker>
          </defs>
          <rect width="960" height="560" fill="#fff"/>
          <rect width="960" height="560" fill="url(#c4-grid)"/>
          <g id="c4-g"></g>
        </svg>
        <div id="c4-empty" class="c4-empty">
          <div class="c4-empty-ic">📐</div>
          <b>Модель ${esc(C4_VIEWS[DSGN.view])} пуста</b>
          <p class="small mut">Добавьте элементы палитрой слева — или доверьте черновик AI<br>и правьте его прямо на холсте.</p>
          <div class="btnrow">
            <button class="c4-aibtn" onclick="c4AI('${DSGN.view}', this)" ${DSGN.readonly?'disabled':''}>🧠 AI-структура</button>
            <button class="sec" id="c4-empty-add" onclick="c4Add('system')" ${DSGN.readonly?'disabled':''}>🖥 Наша система</button>
          </div>
        </div>
      </div>
    </div>
    <div class="c4-props-col">
      <b class="c4-cap">Свойства</b>
      <div id="c4-props"></div>
    </div>
  </div>
  <div id="c4-gallery"></div>
  <pre id="c4-preview" class="chatcode" style="display:none;margin-top:12px;max-height:300px;overflow:auto"></pre>`;
  c4Palette(); c4Draw(); c4Props(); c4Status();
  DSGN.zoom = 1;                      // зум — настройка экрана, между сервисами не переносится
  c4ApplyZoom();
  c4BindSvg();
  c4Gallery(s);
}

/* палитра и кнопки пустого состояния зависят от вида: C4-типы или ER-сущности */
function c4Palette(){
  const pal = document.getElementById('c4-palette'); if(!pal) return;
  const er = DSGN.view === 'er';
  const types = er ? ER_TYPES : C4_TYPES;
  pal.innerHTML = types.map(x =>
    `<button onclick="c4Add('${x.t}')" title="Добавить: ${x.ru}" ${DSGN.readonly?'disabled':''}>${x.icon} ${x.ru}</button>`).join('');
  const eb = document.getElementById('c4-empty-add');
  if(eb){
    eb.textContent = er ? '➕ Сущность' : '🖥 Наша система';
    eb.setAttribute('onclick', `c4Add('${er ? 'entity' : 'system'}')`);
  }
  const pv = document.getElementById('c4-previewbtn');
  if(pv){                             // предпросмотр/экспорт пока только для C4-видов (vision_c4)
    pv.disabled = er;
    pv.title = er ? 'Предпросмотр Mermaid — для C4-видов; ER-исходник виден в галерее и артефакте «Модель данных»' : '';
  }
}

/* Галерея диаграмм из артефактов — «взгляд читателя» внутри «Проектирования»
   (таб «Диаграммы» слит сюда): видеть картинки, не открывая редактор и тексты */
function c4Gallery(s){
  const el = document.getElementById('c4-gallery'); if(!el) return;
  const byKind = Object.fromEntries(s.artifacts.map(a=>[a.kind,a]));
  const withDiag = S.standard.artifacts.filter(a=>(byKind[a.kind]?.diagram_code||'').trim());
  el.innerHTML = `<div class="card" style="margin-top:12px">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
      <b>Диаграммы сервиса</b>
      <span class="small mut">исходник = единый источник правды, картинка вторична</span>
    </div>
    ${withDiag.length ? withDiag.map(a=>`
      <div style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b class="small">${esc(a.title)}</b>
          <a class="lnk small" href="#/service/${s.id}/artifacts" onclick="if(event.button===0&&!event.metaKey&&!event.ctrlKey)ART_JUMP='${a.kind}'">редактировать →</a>
        </div>
        <div class="diag" id="dvg-${a.kind}"></div>
      </div>`).join('')
    : '<p class="mut small" style="margin:10px 0 0">Диаграмм пока нет: нарисуйте C4-модель выше — Mermaid-исходник уйдёт в артефакт Vision сам; ER-модель — в «Модель данных» при её сохранении; deployment — в «Артефактах».</p>'}
  </div>`;
  withDiag.forEach(a => renderDiag(document.getElementById('dvg-'+a.kind), byKind[a.kind].diagram_code));
}

/* пояснение «?» в тулбаре: показывается по клику/с клавиатуры, а не только в title */
function c4HelpToggle(btn){
  const el = document.getElementById('c4-help');
  if(!el) return;
  el.hidden = !el.hidden;
  btn.setAttribute('aria-expanded', String(!el.hidden));
}

function c4SetView(v){
  c4FlushSave();                      // правки текущего вида сохраняются до переключения
  DSGN.view = v; DSGN.sel = null; DSGN.selType = null; c4CancelLink();
  document.querySelectorAll('.c4-views button').forEach(b => b.classList.toggle('c4-vact', b.dataset.view === v));
  document.querySelectorAll('.c4-aibtn').forEach(b => b.setAttribute('onclick', `c4AI('${v}', this)`));
  const em = document.getElementById('c4-empty');
  if(em) em.querySelector('b').textContent = `Модель ${C4_VIEWS[v]} пуста`;
  c4Palette(); c4Draw(); c4Props(); c4Status();
}

function c4Box(n){
  /* габариты узла: ER-сущность растёт по числу атрибутов (шапка 24px + строка на атрибут) */
  if(DSGN.view === 'er')
    return {w: C4_W, h: 42 + Math.max(0, (n.attrs || []).length - 1) * 13};
  return {w: C4_W, h: C4_H};
}

function c4Draw(){
  const g = document.getElementById('c4-g'); if(!g) return;
  const m = c4M();
  const center = n => { const b = c4Box(n); return {x: n.x + b.w/2, y: n.y + b.h/2}; };
  const trim = (na, nb) => {   // обрезка линии по границам прямоугольников (габариты свои у каждого)
    const ba = c4Box(na), bb = c4Box(nb);
    const A = center(na), B = center(nb);
    const dx = B.x - A.x, dy = B.y - A.y;
    if(!dx && !dy) return {a: A, b: B};
    const ta = Math.min(dx ? (ba.w/2) / Math.abs(dx) : 1e9, dy ? (ba.h/2) / Math.abs(dy) : 1e9);
    const tb = Math.min(dx ? (bb.w/2) / Math.abs(dx) : 1e9, dy ? (bb.h/2) / Math.abs(dy) : 1e9);
    return {a: {x: A.x + dx * ta, y: A.y + dy * ta}, b: {x: B.x - dx * tb, y: B.y - dy * tb}};
  };
  let edges = '';
  for(const e of (m.edges || [])){
    const f = c4Node(e.from), t = c4Node(e.to);
    if(!f || !t) continue;
    const p = trim(f, t);
    const selE = DSGN.selType === 'edge' && DSGN.sel === e.id;
    const lbl = DSGN.view === 'er'
      ? esc(ER_CARD_RU[e.card] || '1 — N') + (e.label ? ' · ' + esc(e.label) : '')
      : esc(e.label || 'взаимодействует') + (e.tech ? ` · ${esc(e.tech)}` : '');
    edges += `<line data-eid="${esc(e.id)}" x1="${p.a.x}" y1="${p.a.y}" x2="${p.b.x}" y2="${p.b.y}"
      stroke="${selE ? '#e11d48' : '#64748b'}" stroke-width="${selE ? 3 : 1.6}" marker-end="url(#c4-arrow)"/>
      <line data-eid="${esc(e.id)}" x1="${p.a.x}" y1="${p.a.y}" x2="${p.b.x}" y2="${p.b.y}"
      stroke="transparent" stroke-width="12"/>
      <text x="${(p.a.x + p.b.x)/2}" y="${(p.a.y + p.b.y)/2 - 5}" text-anchor="middle"
      font-size="10.5" fill="#334155" style="paint-order:stroke" stroke="#f8fafc" stroke-width="4"
      font-weight="600">${lbl}</text>`;
  }
  let nodes = '';
  for(const n of (m.nodes || [])){
    const ty = DSGN.view === 'er' ? ER_TYPES[0] : (C4_TYPE[n.type] || C4_TYPE.container);
    const selN = DSGN.selType === 'node' && DSGN.sel === n.id;
    const isLinkFrom = DSGN.linkFrom === n.id;
    const nm = n.name.length > 24 ? n.name.slice(0, 23) + '…' : n.name;
    const b = c4Box(n);
    if(DSGN.view === 'er'){
      const rows = (n.attrs || []).map((a, i) =>
        `<text x="8" y="${36 + i * 13}" font-size="8.5" fill="#334155">${esc([a.type, a.name, a.key].filter(Boolean).join(' '))}</text>`).join('');
      nodes += `<g data-nid="${esc(n.id)}" transform="translate(${n.x},${n.y})"${isLinkFrom?' class="c4-src"':''}>
      <rect width="${b.w}" height="${b.h}" rx="8" fill="${ty.fill}"
        stroke="${selN || isLinkFrom ? '#e11d48' : ty.line}" stroke-width="${selN || isLinkFrom ? 3 : 1.6}"/>
      <text x="8" y="16" font-size="10.5" font-weight="700" fill="#0f172a">${esc(nm)}</text>
      <line x1="0" y1="24" x2="${b.w}" y2="24" stroke="${ty.line}" stroke-width="1"/>
      ${rows}</g>`;
    } else {
    nodes += `<g data-nid="${esc(n.id)}" transform="translate(${n.x},${n.y})"${isLinkFrom?' class="c4-src"':''}>
      <rect width="${C4_W}" height="${C4_H}" rx="10" fill="${ty.fill}"
        stroke="${selN || isLinkFrom ? '#e11d48' : ty.line}" stroke-width="${selN || isLinkFrom ? 3 : ty.t==='system'?2.4:1.6}"
        ${ty.dash ? `stroke-dasharray="${ty.dash}"` : ''}/>
      <text x="${C4_W/2}" y="22" text-anchor="middle" font-size="14">${ty.icon}</text>
      <text x="${C4_W/2}" y="39" text-anchor="middle" font-size="12" font-weight="700" fill="#0f172a">${esc(nm)}</text>
      <text x="${C4_W/2}" y="54" text-anchor="middle" font-size="9.5" fill="#475569">${esc((n.tech || ty.ru).slice(0, 26))}</text>
    </g>`;
    }
  }
  g.innerHTML = edges + nodes;
  const em = document.getElementById('c4-empty');
  if(em) em.classList.toggle('show', !(m.nodes || []).length);
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
    const b = c4Box(n);
    n.x = Math.max(0, Math.min(960 - b.w, c4Snap(C4DRAG.ox + dx)));
    n.y = Math.max(0, Math.min(560 - b.h, c4Snap(C4DRAG.oy + dy)));
    c4Draw();
  };
  svg.onmouseup = () => {
    if(C4DRAG && !C4DRAG.moved){
      const id = C4DRAG.id;
      if(c4LinkOn() && !DSGN.linkFrom){          // первый клик — источник связи
        DSGN.linkFrom = id; c4Draw(); c4Status();
      } else if(DSGN.linkFrom && DSGN.linkFrom !== id){   // второй клик — цель: создаём связь
        const m = c4M();
        const ne = {id: 'e' + Date.now(), from: DSGN.linkFrom, to: id, label: '', tech: ''};
        if(DSGN.view === 'er') ne.card = '||--o{';       // 1 — N: самый частый случай
        m.edges.push(ne);
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
  const pos = {x: c4Snap(40 + Math.random() * (960 - C4_W - 80)),
               y: c4Snap(40 + Math.random() * (560 - C4_H - 80))};
  const n = DSGN.view === 'er'
    ? {id: 'n' + Date.now(), type: 'entity', name: 'Сущность ' + (m.nodes.length + 1),
       attrs: [{name: 'id', type: 'uuid', key: 'PK'}], ...pos}
    : {id: 'n' + Date.now(), type, name: C4_TYPE[type].ru, desc: '', tech: '', ...pos};
  m.nodes.push(n);
  c4Sel(n.id, 'node'); c4Status(); c4SaveSoon();
}

const c4LinkOn = () => { const b = document.getElementById('c4-linkbtn'); return !!b && b.classList.contains('c4-vact'); };
const c4CancelLink = () => { DSGN.linkFrom = null; const b = document.getElementById('c4-linkbtn'); if(b) b.classList.remove('c4-vact');
  document.getElementById('c4-svg')?.classList.remove('c4-linking'); };

function c4LinkMode(){
  const btn = document.getElementById('c4-linkbtn');
  const on = !btn.classList.contains('c4-vact');
  btn.classList.toggle('c4-vact', on);
  document.getElementById('c4-svg')?.classList.toggle('c4-linking', on);
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
  if(DSGN.view === 'er'){
    if(DSGN.selType === 'node'){
      const n = c4Node(DSGN.sel); if(!n) return;
      el.innerHTML = `
      <label>Название сущности</label><input value="${esc(n.name)}" oninput="c4Set('name', this.value)">
      <label>Атрибуты — «тип имя [PK|FK]», по строке</label>
      <textarea rows="6" class="c4-attrs" oninput="c4SetAttrs(this.value)">${esc(c4AttrsText(n))}</textarea>
      <p class="small mut" style="margin:4px 0 0">Например: <code>uuid id PK</code>, <code>varchar email</code>. До 16 атрибутов.</p>`;
    } else {
      const e = c4Edge(DSGN.sel); if(!e) return;
      const f = c4Node(e.from), t = c4Node(e.to);
      el.innerHTML = `
      <p class="small mut" style="margin:0 0 6px">${esc(f?.name||'?')} → ${esc(t?.name||'?')}</p>
      <label>Кардинальность</label><select onchange="c4Set('card', this.value)">
        ${Object.entries(ER_CARD_RU).map(([k, v]) => `<option value="${k}" ${e.card===k?'selected':''}>${v}</option>`).join('')}</select>
      <label>Смысл связи</label><input value="${esc(e.label)}" oninput="c4Set('label', this.value)" placeholder="содержит, относится к…">`;
    }
    return;
  }
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

/* атрибуты ER-сущности: текст «тип имя [PK|FK]» ↔ массив {name, type, key};
   имя может содержать пробелы — после типа берём все токены до ключа */
const c4AttrsText = n => (n.attrs || []).map(a => [a.type, a.name, a.key].filter(Boolean).join(' ')).join('\n');
function c4SetAttrs(text){
  const n = c4Node(DSGN.sel); if(!n) return;
  n.attrs = text.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 16).map(l => {
    const p = l.split(/\s+/);
    let key = '';
    if(p.length >= 2 && (p[p.length-1] === 'PK' || p[p.length-1] === 'FK')) key = p.pop();
    const name = p.length >= 2 ? p.slice(1).join(' ') : p[0];
    const type = p.length >= 2 ? p[0] : 'varchar';
    return {name, type, key};
  });
  c4Draw(); c4Status(); c4SaveSoon();
}

function c4Status(note, warn){
  const el = document.getElementById('c4-chips'); if(!el) return;
  const m = c4M();
  const er = DSGN.view === 'er';
  el.innerHTML = `<span class="c4-chip c4-chipv">${esc(C4_VIEWS[DSGN.view])}</span>`
    + `<span class="c4-chip">${er ? 'сущностей' : 'узлов'} ${m.nodes.length}</span><span class="c4-chip">связей ${m.edges.length}</span>`
    + (note ? `<span class="c4-chip ${warn?'c4-chipwarn':'c4-chipok'}">${esc(note)}</span>` : '')
    + (DSGN.linkFrom ? '<span class="c4-chip c4-chipwarn">🔗 режим связи: выберите цель</span>'
       : (c4LinkOn() ? '<span class="c4-chip c4-chipwarn">🔗 режим связи: кликните источник</span>' : ''));
}

/* зум холста: viewBox сжимается/расширяется вокруг центра; 0 — сброс на 100% */
function c4Zoom(dir){
  DSGN.zoom = dir === 0 ? 1 : Math.min(2.5, Math.max(0.5, Math.round(((DSGN.zoom || 1) + dir * 0.25) * 100) / 100));
  c4ApplyZoom();
}
function c4ApplyZoom(){
  const svg = document.getElementById('c4-svg'); if(!svg) return;
  const z = DSGN.zoom || 1;
  svg.setAttribute('viewBox', `${(960 - 960 / z) / 2} ${(560 - 560 / z) / 2} ${960 / z} ${560 / z}`);
  const l = document.getElementById('c4-zlbl');
  if(l) l.textContent = Math.round(z * 100) + '%';
}

function c4SaveSoon(){
  if(DSGN.readonly) return;           // нет прав на сервис — не тягаем 403 при случайных правках
  clearTimeout(DSGN.saveT);
  // снимок фиксируется сейчас: таймер обязан сохранить тот {sid, view, данные}, при которых
  // была правка, а не те, что станут актуальными через 1.2 с (иначе правка молча теряется)
  DSGN.pending = {sid: DSGN.sid, view: DSGN.view,
                  model: JSON.parse(JSON.stringify({nodes: c4M().nodes, edges: c4M().edges}))};
  DSGN.saveT = setTimeout(() => { DSGN.saveT = null; c4Save(); }, 1200);
}

function c4FlushSave(){
  if(!DSGN.saveT) return Promise.resolve();
  clearTimeout(DSGN.saveT); DSGN.saveT = null;
  const job = DSGN.pending; DSGN.pending = null;
  return job ? c4Save(job) : Promise.resolve();   // немедленный досейв под старым видом (при смене вида/таба)
}

async function c4Save(job){
  const use = job || DSGN.pending;
  if(!job) DSGN.pending = null;
  if(!use) return;
  try{
    const r = await api(`/services/${use.sid}/c4/${use.view}`,
      {method:'PUT', body: JSON.stringify({model: use.model})});
    const er = use.view === 'er';                 // ER: производная — артефакт data_model
    const kind = er ? 'data_model' : 'vision_c4';
    const K = er ? 'dm' : 'vision';
    if(r[K + '_synced'] && SERVICE && SERVICE.id === use.sid){
      const a = (SERVICE.artifacts||[]).find(x=>x.kind===kind);
      if(a) a.diagram_code = r[K + '_code'];      // галерея и вкладка артефактов — без перезагрузки
      const svg = document.getElementById('dvg-' + kind);
      if(svg) renderDiag(svg, r[K + '_code']);
      c4Status('сохранено · ' + (er ? 'Модель данных обновлена' : 'Vision обновлён'));
    }else if((r[K + '_skipped']||[]).length){
      c4Status((er ? 'Модель данных не обновлена: ' : 'Vision не обновлён: ') + r[K + '_skipped'][0], true);
    }else c4Status('сохранено');
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
    c4SaveSoon();                       // AI-модель живёт только в редакторе — сразу в автосейв,
                                        // иначе экспорт/предпросмотр прочитают из БД пустоту
    toast(`${r.provider === 'ai-buddy' ? 'AI-структура (' + esc(r.model||'') + ')' : 'Стартовая структура'} для ${esc(C4_VIEWS[view])} загружена в редактор — <b>проверьте и поправьте</b>`);
  }catch(e){ toast(esc(e.message), true); }
  btn.disabled = false; btn.textContent = old;
}

async function c4Preview(btn){
  try{
    await c4FlushSave();                // недосейвенные правки уходят в БД до чтения
    const r = await api(`/services/${DSGN.sid}/c4/export`,
      {method:'POST', body: JSON.stringify({dry_run: true})});
    const pre = document.getElementById('c4-preview');
    if(!r.code){ pre.style.display = 'none'; return toast('Модели пусты — предпросмотра нет', true); }
    pre.style.display = 'block';
    pre.textContent = r.code;
    toast('Предпросмотр Mermaid-исходника ниже — при сохранении модели он синхронизируется в артефакт Vision автоматически');
  }catch(e){ toast(esc(e.message), true); }
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
    el.innerHTML = `<button class="chat-new-btn" onclick="chatNew()">＋ Новый чат</button>` +
      (r.chats || []).map(c => `
      <div class="chat-item${c.id === CHAT_ID ? ' active' : ''}" onclick="chatOpen(${c.id})" title="${esc(c.title||'')}">
        <span class="chat-item-title">${esc(c.title || 'Чат')}</span>
        <span class="chat-item-del" onclick="event.stopPropagation(); chatDelete(${c.id})" title="Удалить чат">✕</span>
      </div>`).join('');
  }catch{ /* нет доступа — панель пустая */ }
}

async function chatOpen(id){
  if(CHAT_BUSY) return;
  $('#chat-list')?.classList.remove('open');
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

/* плавающая иконка чат-бота у правого края (вне топбара и меню) */
function aiTriggerMount(){
  if(document.getElementById('ai-trigger')) return;
  const b = document.createElement('button');
  b.id = 'ai-trigger'; b.className = 'ai-trigger';
  b.title = 'AI-ассистент стандарта — чат поверх любого экрана';
  b.setAttribute('aria-label', 'AI-ассистент');
  b.onclick = toggleAiPanel;
  b.innerHTML = `<span class="robot" aria-hidden="true"><svg viewBox="0 0 24 24" width="26" height="26"
    fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
    <line class="antenna" x1="12" y1="7" x2="12" y2="3.6"/>
    <circle class="antenna-tip" cx="12" cy="2.9" r="1.1" fill="currentColor" stroke="none"/>
    <rect x="4.2" y="7" width="15.6" height="12.4" rx="3.4"/>
    <line x1="4.2" y1="12" x2="2.6" y2="12"/><line x1="19.8" y1="12" x2="21.4" y2="12"/>
    <circle class="eye" cx="9.2" cy="12.6" r="1.5" fill="currentColor" stroke="none"/>
    <circle class="eye" cx="14.8" cy="12.6" r="1.5" fill="currentColor" stroke="none"/>
    <path d="M9.6 16.4h4.8"/>
  </svg></span><i class="ai-dot"></i>`;
  document.body.append(b);
}
/* чип контекста сервиса в шапке панели (🧩 + имя, ✕ — убрать) */
async function aiCtxRender(){
  const box = document.getElementById('ai-ctx'); if(!box) return;
  if(!ASK_SERVICE){ box.innerHTML = ''; return; }
  if(!ASK_SVC_NAME){
    try{ const sv = await api('/services/' + ASK_SERVICE); ASK_SVC_NAME = sv.name; }
    catch{ ASK_SVC_NAME = ''; }
  }
  box.innerHTML =
    `<span class="chip" id="svc-ctx-chip">🧩 ${esc(ASK_SVC_NAME || ('service #' + ASK_SERVICE))}
     <span style="cursor:pointer" onclick="clearAskService()" title="Убрать контекст сервиса">✕</span></span>`;
}
async function aiPanelOpen(){
  let p = document.getElementById('aipanel');
  if(p){ p.classList.add('open'); document.body.classList.add('ai-open'); aiCtxRender(); $('#q')?.focus(); return; }
  p = document.createElement('div'); p.id = 'aipanel'; p.className = 'aipanel';
  p.innerHTML = `
  <div class="ai-head">
    <b style="font-size:14px">AI-ассистент</b><span id="ai-status"></span>
    <span class="grow"></span>
    <button class="sec" onclick="aiHistToggle()" title="История чатов">История ▾</button>
    <button class="sec" id="ai-full-btn" onclick="aiFullToggle(this)" title="На весь экран (меню остаётся видимым)">⛶</button>
    <button class="sec" onclick="aiPanelClose()" title="Закрыть (Esc)">✕</button>
    <div id="ai-ctx"></div>
    <div class="chat-list" id="chat-list"></div>
  </div>
  <div class="chat-wrap">
    <div class="chat-scroll" id="chat-scroll"><div class="chat-log" id="chat-log"></div></div>
    <div class="composer">
      <div class="composer-box">
        <textarea id="q" rows="1" placeholder="Спросите про стандарт — артефакты, ревью, техдолг, fitness…"
          onkeydown="chatKeydown(event)" oninput="chatAutogrow(this)"></textarea>
        <select id="chat-model" class="chat-model" style="display:none"
          onchange="chatModelPick()" title="Модель LLM"></select>
        <button class="send-btn" id="send-btn" onclick="askAssistant()" title="Отправить (Enter)">↑</button>
      </div>
      <p class="small mut" style="text-align:center">Advisory-режим (BR-33): ничего не меняет, решение за человеком.
      Могут быть неточности — проверяйте по первоисточнику.</p>
    </div>
  </div>`;
  document.body.append(p);
  document.body.classList.add('ai-open');
  requestAnimationFrame(() => p.classList.add('open'));
  aiCtxRender();
  let st = {provider:'local-rag', kb_pages:'…', kb_chunks:''};
  try{ st = await api('/assistant/status'); }catch{}
  document.getElementById('ai-status').innerHTML = st.provider === 'ai-buddy'
    ? `<span class="badge b-approved">● AI-Buddy</span>`
    : `<span class="badge b-in_review">● fallback</span>`;
  if(CHAT.length){ renderChat(); }                    // вернулись в открытый чат
  else{
    const chats = await api('/assistant/chats').catch(() => ({chats: []}));
    if((chats.chats || []).length) await chatOpen(chats.chats[0].id);
    else renderChat();
  }
  $('#q')?.focus();
  chatLoadModels();
  loadChats();
}
function aiPanelClose(){
  const p = document.getElementById('aipanel');
  if(!p) return;
  p.classList.remove('open');
  document.body.classList.remove('ai-open');
}
function toggleAiPanel(){
  const p = document.getElementById('aipanel');
  (p && p.classList.contains('open')) ? aiPanelClose() : aiPanelOpen();
}
function aiHistToggle(){ $('#chat-list')?.classList.toggle('open'); }
/* разворот панели на весь экран под топбаром (меню остаётся доступным) */
function aiFullToggle(btn){
  const p = document.getElementById('aipanel'); if(!p) return;
  const full = p.classList.toggle('full');
  document.body.classList.toggle('ai-full', full);
  btn.textContent = full ? '⇲' : '⛶';
  btn.title = full ? 'Свернуть в боковую панель' : 'На весь экран (меню остаётся видимым)';
}

async function askAssistantAbout(sid){
  ASK_SERVICE = sid;
  try{ const sv = await api('/services/' + sid); ASK_SVC_NAME = sv.name; }
  catch{ ASK_SVC_NAME = ''; }
  await aiPanelOpen();   // панель поверх текущего экрана — контекст не теряется
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
  $('#chat-list')?.classList.remove('open');
  CHAT_ID = null; CHAT = []; renderChat(); loadChats(); $('#q')?.focus();
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
  const can = ['domain_expert','admin'].includes(S.user.role);        // integration.import
  const canAudit = ['domain_expert','admin','infosec'].includes(S.user.role);  // audit.view
  const isAdmin = S.user.role === 'admin';
  $('#view').innerHTML = `<h1>Интеграции</h1>
  <div class="grid g2" style="margin-top:14px">
    <div class="card vio"><h2 style="margin-top:0">Backstage Catalog (BR-21)</h2>
      <p class="small mut">Импорт сервисов из catalog-info.yaml (GitLab autodiscovery). MVP — mock-коннектор с dry-run.</p>
      <div class="btnrow"><button class="cya" onclick="importBackstage(true)" ${can?'':'disabled title="Нужна роль domain_expert+"'}>Dry-run импорт</button>
      <button onclick="importBackstage(false)" ${can?'':'disabled title="Нужна роль domain_expert+"'}>Импортировать</button></div>
      <div id="imp-res"></div></div>
    <div class="card"><h2 style="margin-top:0">CMDB (BR-20/22)</h2>
      <p class="small mut">DataGerry — REST API + ObjectTypes (контур кибербезопасности). Матрица владения полями:
      ИС → архитектурные атрибуты, CMDB → операционные (CI, health, алерты). Подключение — после финализации выбора CMDB.</p>
      <span class="badge b-draft">запланировано</span></div>
    ${isAdmin?`<div class="card"><h2 style="margin-top:0">AI-Buddy: корпоративная LLM</h2>
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
    </div>`:''}
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
      <p class="small mut">Все действия фиксируются (BR-33). Просмотр: expert/admin/InfoSec.</p>
      <div class="btnrow">${canAudit?'<button class="sec" onclick="showAudit()">Открыть журнал</button>':`<span class="mut small">нужна роль domain_expert+ или InfoSec</span>`}</div>
      <div id="audit-res"></div></div>
  </div>`;
  if (isAdmin) renderLlm();
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
  const f = m.querySelector('input:not([disabled]),textarea,select');
  if(f) f.focus();
}
const closeModal = () => $('#modal')?.remove();
document.addEventListener('keydown', e => {
  if(e.key !== 'Escape') return;
  if($('#modal')) closeModal();
  else aiPanelClose();
});
/* клик вне открытой панели закрывает её (клик по самой панели, кнопке-роботу и тостам — нет) */
document.addEventListener('click', e => {
  const p = document.getElementById('aipanel');
  if(!p || !p.classList.contains('open')) return;
  const t = e.target;
  if(!t || typeof t.closest !== 'function') return;
  if(t.closest('#aipanel') || t.closest('#ai-trigger') || t.closest('#toast')) return;
  aiPanelClose();
});
window.addEventListener('hashchange', render);
// восстановление сессии по сохранённому токену
(async () => {
  if(localStorage.token){
    try{ S.user = await api('/me'); }catch{ delete localStorage.token; }
  }
  render();
})();
