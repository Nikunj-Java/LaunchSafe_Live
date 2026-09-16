'use strict';
/* All shared mutations go through the authenticated Python server.
   Team controls below only switch local tabs or open read-only views. */
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const e = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => '$' + Number(n || 0).toLocaleString('en-US');
const points = n => (n > 0 ? '+' : '') + n;
const color = n => n > 0 ? 'positive' : n < 0 ? 'negative' : 'muted';
const uid = () => { const a = new Uint8Array(18); crypto.getRandomValues(a); return [...a].map(x => x.toString(16).padStart(2,'0')).join(''); };
const mode = location.pathname === '/host' ? 'host' : location.pathname === '/screen' ? 'screen' : location.pathname.startsWith('/team/') ? 'team' : 'join';
let teamId = mode === 'team' ? location.pathname.split('/')[2] : null;
const readSession = key => { try { return sessionStorage.getItem(key); } catch { return null; } };
const writeSession = (key,val) => { try { sessionStorage.setItem(key,val); } catch {} };
let token = readSession('launchsafe-host') || '';
if (mode === 'host' && location.hash.length > 1) {
  token = location.hash.slice(1); writeSession('launchsafe-host',token);
  history.replaceState(null,'',location.pathname);
}
let viewer = readSession('launchsafe-viewer') || uid(); writeSession('launchsafe-viewer',viewer);
let S = null, busy = false, polling = false, clockOffset = 0, hostTab = 'stage', teamTab = 'live';
let bidDraft = {focus:null,team:'',price:''}, setupDraft = null, soundOn = false, audio = null;
let previousEvent = null, previousPhase = null, previousGame = null, toastTimer = null, lastClockSecond = null;
const phaseNames = {lobby:'Lobby',brief:'Risk briefing',auction:'Live auction',simulation:'Incident room',debrief:'Board pitches',round_end:'Round results',finished:'Final champions'};
const team = id => S.teams.find(t=>t.id===id) || {id,name:'Unknown team',members:''};
const idx = id => Math.max(0,S.teams.findIndex(t=>t.id===id));
const tone = id => 'team-tone-' + idx(id);
const dot = id => `<span class="team-dot ${tone(id)}">${String(idx(id)+1).padStart(2,'0')}</span>`;
const owned = id => S.round ? S.round.purchases.filter(p=>p.team_id===id) : [];
const cash = id => S.rules.budget - owned(id).reduce((n,p)=>n+p.price,0);
const score = id => S.round_scores.find(r=>r.team_id===id);
const overall = id => S.leaderboard.find(r=>r.team_id===id);
const lot = id => S.scenario.mits.find(m=>m.id===id);
const sold = id => S.round ? S.round.purchases.filter(p=>p.mid===id) : [];
const finishedRound = () => ['debrief','round_end','finished'].includes(S.phase);
const btn = (label,act,cls='',attrs='',disabled=false) => `<button type="button" class="btn ${cls}" data-act="${act}" ${attrs} ${disabled?'disabled':''}>${label}</button>`;
const mutateBtn = (label,act,cls='',attrs='',disabled=false) => btn(label,act,cls,'data-mutate '+attrs,disabled);
const pill = (label,cls='neutral') => `<span class="pill ${cls}">${label}</span>`;
function title(eyebrow,heading,sub=''){return `<div class="stage-top"><div><div class="eyebrow">${eyebrow}</div><h2>${heading}</h2>${sub?`<p>${sub}</p>`:''}</div></div>`;}
function toast(message,error=false){
  const el=$('#toast');el.textContent=message;el.className='toast show'+(error?' error':'');
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),error?7000:4000);
}
function connection(ok){
  const el=$('#connection');el.className=ok?'connection':'connection offline';
  el.textContent=ok?'Connected':S?'Connection lost - showing the last saved state. Reconnecting automatically...':'Cannot reach the control room. Check the server and Wi-Fi; retrying automatically...';
  document.body.dataset.online=ok?'yes':'no';
}
function requestHeaders(){return {'Content-Type':'application/json', ...(mode==='host' && token ? {'Authorization':'Bearer '+token}:{})};}
async function fetchTimed(url,options={}){
  const controller = new AbortController(); const t=setTimeout(()=>controller.abort(),8000);
  try{return await fetch(url,{cache:'no-store',...options,signal:controller.signal});}finally{clearTimeout(t);}
}
function receive(next){
  if(S && next.version < S.version)return;
  clockOffset=next.server_now*1000-Date.now();
  if(next.unchanged){ if(S) S.presence=next.presence; updatePresence(); tick(); return; }
  const first=!S;
  const newGame=S && S.game_id!==next.game_id;
  const event=next.audit.length?next.audit[next.audit.length-1]:null;
  if(!first && event && event.id!==previousEvent){
    if(event.kind==='sold') play('sold');
    if(event.kind==='incident') play('incident');
    if(event.kind==='finish' || (event.kind==='round' && next.phase==='round_end')) play('win');
  }
  previousEvent=event?.id;
  if(newGame){teamTab='live';hostTab='stage';setupDraft=null;}
  if(S && S.round?.id!==next.round?.id){teamTab='live';bidDraft={focus:null,team:'',price:''};}
  if(next.phase!=='lobby')setupDraft=null;
  previousPhase=S?.phase;
  S=next; render(); updatePresence(); tick();
  if(!first && previousPhase!==S.phase) window.scrollTo({top:0,behavior:'smooth'});
}
async function poll(force=false){
  if(polling || busy || (mode==='host'&&!token))return;
  polling=true;
  try{
    const endpoint=mode==='host'?'/api/host':'/api/state';
    const q=new URLSearchParams();
    if(S&&!force) q.set('since',S.version);
    if(mode==='team'||mode==='screen'){q.set('viewer',viewer);q.set('team',mode==='screen'?'screen':teamId);}
    const res=await fetchTimed(endpoint+'?'+q.toString(),{headers:mode==='host'?{'Authorization':'Bearer '+token}:{}});
    if(res.status===401 && mode==='host'){token='';writeSession('launchsafe-host','');S=null;renderLogin();return;}
    if(!res.ok)throw Error('Cannot read game');
    receive(await res.json()); connection(true);
  }catch(err){connection(false);}finally{polling=false;}
}
async function act(action,data={}){
  if(mode!=='host'||busy)return false;
  busy=true;document.body.classList.add('busy');
  try{
    const response=await fetchTimed('/api/action',{method:'POST',headers:requestHeaders(),body:JSON.stringify({action,data,version:S.version,request_id:uid()})});
    const result=await response.json();
    if(!response.ok){throw Object.assign(new Error(result.error||'Action was not accepted.'),{status:response.status});}
    receive(result);connection(true);return true;
  }catch(err){
    toast(err.name==='AbortError'?'No confirmation received. Check the refreshed dashboard before repeating the action.':err.message,true);
    if(err.status===401){token='';writeSession('launchsafe-host','');renderLogin();}
    return false;
  }finally{busy=false;document.body.classList.remove('busy');await poll(true);}
}
function brand(sub='The risk negotiation game'){
  return `<div class="brand"><div class="brandmark">L<span>\\</span>S</div><div><div class="brand-name">LaunchSafe <b>LIVE</b></div><div class="brand-sub">${e(sub)}</div></div></div>`;
}
function phaseTrack(){
  const order=['brief','auction','simulation','debrief','round_end'];const current=S.phase==='finished'?4:order.indexOf(S.phase);
  const labels=['Brief','Auction','Incidents','Pitch','Results'];
  return `<div class="phase-track">${order.map((p,i)=>`<span class="phase-step ${i===current?'active':i<current?'done':''}" data-num="${i+1}">${labels[i]}</span>`).join('')}</div>`;
}
function banner(){return S.announcement?`<div class="banner"><b>Control room</b><div>${e(S.announcement)}</div></div>`:'';}
function timerSmall(){return `<div class="header-timer"><div class="timer-title">Room timer</div><div class="timer small" data-clock>03:00</div></div>`;}
function publicHeader(){
  return `<header class="site-header screen-header">${brand(S.title)}<div class="public-tools">${S.phase!=='lobby'?pill(`Round ${S.round_index+1}/${S.scenario_order.length}`):''}${timerSmall()}${btn('QR code','qr','small')}${btn(soundOn?'Sound on':'Sound off','sound','small ghost')}${btn('Full screen','fullscreen','small ghost')}</div></header>`;
}
function renderLogin(){
  $('#app').innerHTML=`<header class="site-header">${brand('Instructor sign-in')}</header><main class="login card"><div class="eyebrow">Private control room</div><h2 class="mt-sm">Your classroom. Your controls.</h2><p class="subtitle">Open the PRIVATE HOST link printed in your Python terminal, or paste only its secret below.</p><form id="login-form" class="mt"><label class="form-label" for="host-secret">Instructor secret</label><input id="host-secret" class="field" type="password" autocomplete="off" required><button class="btn primary full mt" type="submit">Open control room</button></form><p class="tiny muted mt">This is not the team join code. Do not share your private host link with learners.</p></main>`;
  $('#connection').className='connection';
}
function render(){
  if(!S)return;
  const active=document.activeElement;
  const focus=active?.id&&['INPUT','TEXTAREA','SELECT'].includes(active.tagName)?{id:active.id,value:active.value,start:active.selectionStart,end:active.selectionEnd}:null;
  const details=$$('details[open]').map(d=>d.id).filter(Boolean);
  const html=mode==='host'?hostPage():mode==='screen'?screenPage():mode==='team'?teamPage():joinPage();
  $('#app').innerHTML=html;
  details.forEach(id=>{const d=document.getElementById(id);if(d)d.open=true;});
  if(focus){const el=document.getElementById(focus.id);if(el){el.value=focus.value;el.focus({preventScroll:true});try{el.setSelectionRange(focus.start,focus.end);}catch{}}}
  if(mode==='team')document.title=team(teamId).name+' - LaunchSafe';
  else document.title=(mode==='host'?'Control room':mode==='screen'?'Projector':'Join')+' - LaunchSafe';
}
function tick(){
  if(!S)return;
  const remaining=S.timer.running?Math.max(0,Math.ceil((S.timer.deadline*1000-Date.now()-clockOffset)/1000)):S.timer.seconds;
  const label=String(Math.floor(remaining/60)).padStart(2,'0')+':'+String(remaining%60).padStart(2,'0');
  $$('[data-clock]').forEach(el=>{el.textContent=label;el.classList.toggle('urgent',remaining<=10&&S.timer.running);});
  $$('[data-timer-state]').forEach(el=>el.textContent=S.timer.running?(remaining>0?'Running':'Time is up'):'Paused');
  if(remaining===0 && lastClockSecond!==0 && S.timer.running)play('time');
  lastClockSecond=remaining;
}
function updatePresence(){
  if(!S)return;
  $$('[data-presence]').forEach(el=>{const n=S.presence[el.dataset.presence]||0;el.textContent=n===0?'No active viewer':`${n} active viewer${n===1?'':'s'}`;});
  $$('[data-viewer-total]').forEach(el=>{el.textContent=Object.entries(S.presence).filter(([k])=>k!=='screen').reduce((sum,[,v])=>sum+v,0);});
}
function publicRules(){
  const p=S.rules;
  return `<div class="card"><div class="row between"><h3>The deal</h3>${pill(p.name+' scoring','warm')}</div><div class="subtitle">${money(p.budget)} fresh each round. Maximum ${p.max_buys} different mitigations. ${S.copies} ${S.copies===1?'copy':'copies'} of each lot. ${S.incident_count} sealed incidents.</div><div class="table-wrap mt"><table><tbody><tr><td>Highly correlated mitigation</td><td class="positive mono">+10</td></tr><tr><td>Partially correlated mitigation</td><td class="mono" style="color:var(--accent)">+5</td></tr><tr><td>Unmanaged incident</td><td class="negative mono">-10</td></tr><tr><td>Every incident highly covered</td><td class="positive mono">+5</td></tr><tr><td>Cash saved: each full $1,000</td><td class="mono">+5, cap +${p.budget_cap}</td></tr>${p.all_missed?`<tr><td>Every incident unmanaged</td><td class="negative mono">${p.all_missed}</td></tr>`:''}<tr><td>Instructor-approved strategy pitch</td><td class="positive mono">+5</td></tr></tbody></table></div><p class="tiny muted mt-sm">One result per risk; high and partial cover do not stack. A mitigation can cover several risks. No penalty for an unused purchase. Cash, sweep and all-missed adjustments apply only after every incident is revealed. Equal totals share a winning position.</p></div>`;
}
function roleCards(){
  const people=(mode==='team'?team(teamId).members:'').split(',').map(s=>s.trim()).filter(Boolean);
  return `<details id="roles-panel" class="card"><summary><strong>Make every voice count</strong><span class="muted tiny"> &middot; rotate roles each round</span></summary><p class="subtitle">For four players, combine auction voice and spokesperson. For five, give each player one role. Decisions are discussed aloud; the phone stays a viewer.</p><div class="role-grid mt">${S.roles.map((r,i)=>`<div class="role"><h4>${e(r.name)}</h4>${people.length?`<div class="tiny mb">${e(people[(i+S.round_index)%people.length])}</div>`:''}<p>${e(r.job)}</p></div>`).join('')}</div></details>`;
}
function joinHero(projector=false){
  return `<div class="join-hero"><div><div class="eyebrow">${e(S.title)} / ${S.scenario_order.length}-round risk tournament</div><h1>Spend smart.<br>Survive the launch.</h1><p>Limited protection. Loud auctions. Unexpected incidents. Your team has one job: make the trade-offs you can defend.</p><div class="join-stats"><div><strong>${money(S.rules.budget)}</strong><small>per team, per round</small></div><div><strong>${S.rules.max_buys}</strong><small>purchases maximum</small></div><div><strong>${S.incident_count}</strong><small>sealed incidents</small></div></div><div class="row mt">${pill('Teams watch. Instructor controls.','warm')}${pill(S.rules.name+' scoring')}</div></div><div class="join-qr center"><div class="qr-frame"><img src="/qr.svg" alt="Scan to open the team selection page"></div><h3 class="mt-sm">Scan. Pick your team.</h3><p class="qr-caption">${e(S.network.join)}</p><p class="tiny muted mt-sm">Use the same reachable classroom network.</p></div></div>`;
}
function joinPage(){
  return `<header class="site-header">${brand(S.title)}<div class="public-tools">${pill('Read-only team access','live')}${btn('Show join QR','qr','small ghost')}</div></header><main class="shell">${banner()}${joinHero()}<div class="section-title"><h3>Choose your team viewer</h3><small><span data-viewer-total>0</span> connected devices</small></div><div class="join-cards">${S.teams.map(t=>`<a href="/team/${t.id}" class="card team-join ${tone(t.id)}">${dot(t.id)}<div class="grow"><div class="team-name">${e(t.name)}</div><div class="tiny muted" data-presence="${t.id}"></div></div><span class="muted">&#8594;</span></a>`).join('')}</div><div class="notice mt">Bid by raising your hand and speaking to the instructor. Your phone shows live prices, your cash, purchases and scores. It cannot bid, buy, reveal risks or change the game.</div>${S.phase!=='lobby'?`<p class="subtitle">The room is in <strong>${phaseNames[S.phase]}</strong>. You can join at any time.</p>`:''}<details id="join-rules" class="mt"><summary class="muted">Read the scoring rules</summary><div class="mt">${publicRules()}</div></details><p class="local-note">Team views are public, not confidential accounts. More than one teammate can open the same viewer.</p></main>`;
}
function getSetupDraft(){
  if(!setupDraft)setupDraft={title:S.title,teams:S.teams.map(t=>({...t})),profile:S.profile,copies:S.copies,incident_count:S.incident_count,scenario_order:[...S.scenario_order]};
  return setupDraft;
}
function gatherSetup(){
  if(!$('#setup-form'))return getSetupDraft();
  const form=$('#setup-form');
  const d={title:$('#session-title').value,profile:$('#profile').value,copies:Number($('#copies').value),incident_count:Number($('#incident-count').value),teams:[],scenario_order:$$('input[name="scenario"]:checked',form).map(el=>Number(el.value))};
  $$('[data-team-name]',form).forEach((el,i)=>d.teams.push({name:el.value,members:$(`[data-team-members="${i}"]`,form).value}));
  setupDraft=d;return d;
}
function setupPage(){
  const d=getSetupDraft();
  return `${title('Instructor setup','Build your room.','Name the teams, publish one scoring profile, then let the room compete.')}<form id="setup-form" class="stack"><div class="card"><div class="form-grid"><div><label for="session-title" class="form-label">Session name</label><input class="field" id="session-title" maxlength="64" value="${e(d.title)}" required></div><div><label for="team-count" class="form-label">Number of teams</label><select class="field" id="team-count">${Array.from({length:11},(_,i)=>i+2).map(n=>`<option ${d.teams.length===n?'selected':''}>${n}</option>`).join('')}</select></div></div><div class="section-title"><h3>The teams</h3>${btn('Use fun team names','fun-names','small ghost')}</div><p class="tiny muted mb">Suggested split for 23 learners: three teams of 5 and two teams of 4. Member names are optional and visible to the room.</p>${d.teams.map((t,i)=>`<div class="team-edit"><span class="team-dot team-tone-${i}">${String(i+1).padStart(2,'0')}</span><input class="field" id="team-name-${i}" data-team-name="${i}" aria-label="Team ${i+1} name" maxlength="32" value="${e(t.name)}" required><input class="field member-field" id="team-members-${i}" data-team-members="${i}" aria-label="Team ${i+1} members" maxlength="180" value="${e(t.members)}" placeholder="Optional: names, separated by commas"></div>`).join('')}<div class="line"></div><div class="form-grid three"><div><label class="form-label" for="profile">Scoring profile</label><select id="profile" class="field"><option value="arena" ${d.profile==='arena'?'selected':''}>Arena - risk decisions matter more</option><option value="original" ${d.profile==='original'?'selected':''}>Original - uploaded game scoring</option></select></div><div><label class="form-label" for="copies">Copies of every mitigation</label><select id="copies" class="field"><option value="1" ${d.copies===1?'selected':''}>1 - fierce scarcity</option><option value="2" ${d.copies===2?'selected':''}>2 - recommended</option></select></div><div><label class="form-label" for="incident-count">Incidents per scenario</label><select id="incident-count" class="field"><option value="3" ${d.incident_count===3?'selected':''}>3 - recommended</option><option value="4" ${d.incident_count===4?'selected':''}>4 - tougher survival</option></select></div></div><div class="notice mt">Arena keeps +10 / +5 / -10 risk scoring, but lowers the cash-bonus cap from +30 to +15 and adds -5 when every incident is unmanaged. Original uses the uploaded game's scoring. This choice locks when play starts.</div>${d.teams.length>5?`<div class="notice alert mt-sm">More than five teams increases scarcity: a scenario has only 7 or 8 lots, with ${d.copies} copies each. Some teams may not buy three items.</div>`:''}</div><div class="card"><h3>Choose the rounds</h3><p class="subtitle">Selected scenarios run in the order shown. Each has its own original auction catalogue.</p>${S.scenarios.map(sc=>`<label class="checkrow"><input type="checkbox" name="scenario" value="${sc.id}" ${d.scenario_order.includes(sc.id)?'checked':''}><span><strong>0${sc.id} &middot; ${e(sc.name)}</strong><br><span class="tiny">${sc.risk_count} exposed risks &middot; ${sc.lot_count} mitigation lots</span></span></label>`).join('')}</div><div class="row"><button type="submit" class="btn" data-mutate>Save room settings</button>${mutateBtn('Save & start round 1 &#8594;','start','primary big')}</div></form>`;
}
function hostHeader(){
  const tabs=[['stage','Control room'],['links','Team QR codes'],['rules','Rules & answer key'],['backup','Save / restore']];
  return `<header class="site-header">${brand('Instructor control room')}<nav class="header-nav">${tabs.map(([id,label])=>`<button class="navbtn ${hostTab===id?'active':''}" data-act="host-tab" data-tab="${id}">${label}</button>`).join('')}<a class="btn small" href="/screen" target="_blank" rel="noopener">Open projector &#8599;</a></nav></header><div class="private-strip">INSTRUCTOR ONLY &nbsp; / &nbsp; Project the separate /screen window. Never project this dashboard or share your private host link.</div>`;
}
function timerPanel(){
  return `<div class="card"><div class="row between"><div class="timer-title">Room timer</div><span class="tiny muted" data-timer-state>Paused</span></div><div class="timer" data-clock>03:00</div><p class="tiny muted mt-sm">Time is a cue, not an automatic phase change.</p><div class="timer-controls">${mutateBtn(S.timer.running?'Pause':'Start','timer-toggle',S.timer.running?'':'primary','',S.phase==='lobby'||S.phase==='finished')}</div><div class="timer-set"><input class="field" id="timer-seconds" type="number" min="0" max="3600" value="${S.timer.seconds}" aria-label="Timer duration in seconds">${mutateBtn('Set seconds','timer-set','small','',S.phase==='lobby'||S.phase==='finished')}</div><div class="timer-presets">${[30,45,180,300].map(n=>mutateBtn(n>=60?n/60+' min':n+' sec','timer-preset','small ghost',`data-seconds="${n}"`,S.phase==='lobby'||S.phase==='finished')).join('')}</div></div>`;
}
function ledgerPanel(){
  return `<div class="card"><div class="row between"><h4>Team wallets</h4><span class="tiny muted">${S.rules.max_buys} max</span></div>${S.teams.map(t=>`<div class="ledger-mini">${dot(t.id)}<div class="grow"><div class="team-name truncate">${e(t.name)}</div><div class="slots">${owned(t.id).length}/${S.rules.max_buys} bought &middot; <span data-presence="${t.id}"></span></div></div><span class="cash ${cash(t.id)<2000?'negative':'positive'}">${money(cash(t.id))}</span></div>`).join('')}</div>`;
}
function feed(){return `<div class="card"><h4 class="mb">Room activity</h4><div class="activity">${S.audit.length?S.audit.slice().reverse().map(x=>`<div class="activity-item ${e(x.kind)}"><time>${new Date(x.time*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</time><p>${e(x.message)}</p></div>`).join(''):'<p class="muted">The auction story will appear here.</p>'}</div></div>`;}
function sidebar(){return `<aside class="sidebar stack">${timerPanel()}${ledgerPanel()}<div class="card"><label class="form-label" for="announcement">Send a room-wide message</label><textarea id="announcement" class="field" maxlength="220" placeholder="One minute left to agree your strategy...">${e(S.announcement)}</textarea><div class="row mt-sm">${mutateBtn('Publish','announce','small primary')}${mutateBtn('Clear','clear-announce','small ghost')}</div></div>${feed()}</aside>`;}
function hostPage(){
  let content;
  if(hostTab==='links')content=linksPage();
  else if(hostTab==='rules')content=hostRules();
  else if(hostTab==='backup')content=backupPage();
  else content=S.phase==='lobby'?setupPage():`${phaseTrack()}${banner()}${stage(true)}`;
  return `${hostHeader()}<main class="shell"><div class="host-grid"><section>${content}</section>${sidebar()}</div></main>`;
}
function linksPage(){
  return `${title('Read-only access','One QR for the room. One viewer per team.','All teammates can scan the main QR and choose a team. The links below skip team selection.')}<div class="card grid2"><div class="center"><div class="qr-frame"><img src="/qr.svg" alt="Main team-join QR"></div></div><div class="stack" style="justify-content:center"><h3>Project this, not your controls.</h3><p class="muted">Team pages contain no auction controls. Team viewers are public and do not need passwords.</p><div class="mono tiny wrap-anywhere">${e(S.network.join)}</div><div class="row">${btn('Copy join link','copy','primary',`data-text="${e(S.network.join)}"`)}${btn('Print QR sheet','print','ghost')}</div><p class="tiny muted">The QR address comes from the server. To use a different network adapter, restart with --public-url and your correct LAN address.</p></div></div><div class="links-grid mt">${S.teams.map(t=>`<div class="card center ${tone(t.id)}"><div class="row">${dot(t.id)}<div class="team-name">${e(t.name)}</div></div><div class="qr-frame"><img src="/qr.svg?team=${t.id}" alt="QR for ${e(t.name)}"></div><div class="tiny muted" data-presence="${t.id}"></div><div class="row mt-sm"><a href="/team/${t.id}" target="_blank" rel="noopener" class="btn small grow">Open viewer</a>${btn('Copy','copy','small ghost',`data-text="${e(S.network.base+'/team/'+t.id)}"`)}</div></div>`).join('')}</div>`;
}
function hostRules(){
  const map=S.answer_key;
  return `${title('Private reference','The rules, without the surprises.','Only this instructor endpoint receives the unrevealed answer key.')}<div class="notice alert mb">Do not project this tab. The sealed incident order is not shown here: it is committed before the auction and revealed one card at a time.</div>${publicRules()}<div class="section-title"><h3>Answer key &middot; ${e(S.scenario.name)}</h3></div><div class="table-wrap"><table class="key-table"><thead><tr><th>Risk</th><th>Highly correlated +10</th><th>Partially correlated +5</th></tr></thead><tbody>${S.scenario.risks.map(r=>`<tr><td><strong>${r.id}</strong><div class="tiny muted mt-sm">${e(r.d)}</div></td><td>${map[r.id].high}<div class="tiny muted mt-sm">${e(lot(map[r.id].high)?.d||'Catalogue appears after start')}</div></td><td>${map[r.id].partial}<div class="tiny muted mt-sm">${e(lot(map[r.id].partial)?.d||'Catalogue appears after start')}</div></td></tr>`).join('')}</tbody></table></div><div class="card mt"><h3>A better room rhythm</h3><p class="subtitle">Brief for 3 minutes. Ask each team to name one priority risk and one walk-away price. Auction one copy at a time. Call "going once" and "going twice", then record the sale. After the auction locks, reveal one incident and let teams react before revealing the next.</p><p class="subtitle">Give each team a 45-second board pitch. Award the +5 strategy bonus for a defensible trade-off with an explicit limitation or fallback, not for confidence or volume. Enter the reason so the room can see the standard.</p><p class="subtitle">Swap team roles each round. Ask a different person to explain the risk that was accepted. Share podium positions when points tie; no surprise tie-breaker.</p></div>${roleCards()}<div class="notice mt">The four scenario descriptions, mitigation catalogues and high/partial mappings come from the uploaded LaunchSafe HTML. Narrated headlines, mobile viewers, sealed draws and the optional Arena scoring adjustment are additions. These are classroom scoring conventions, not universal risk-management rules.</div>`;
}
function backupPage(){
  return `${title('Session safety','Saved after every accepted action.','Restart the same folder and the same game resumes automatically.')}<div class="stack"><div class="card"><h3>Take a portable checkpoint</h3><p class="subtitle">The native JSON backup contains the entire game, including the still-secret incident deck. Keep it with the instructor, not the learners. It does not contain the host authentication secret.</p><div class="row mt">${btn('Download game backup','export','primary')}${btn('Download scores CSV','csv')}</div></div><div class="card"><h3>Restore a LaunchSafe Live backup</h3><p class="subtitle">Restoring replaces the current game and pauses its timer. Export the current game first. This accepts this edition's native backups, not the old single-page game's JSON format.</p><input id="restore-file" type="file" accept=".json,application/json" class="field mt"><div class="mt">${mutateBtn('Choose backup & restore','restore','danger')}</div></div><div class="card danger"><h3>Start a different game</h3><p class="subtitle">This resets teams, purchases and points. Automatic saving is not a substitute for exporting a checkpoint you want to keep.</p><div class="mt">${mutateBtn('Reset to a new lobby','reset','danger')}</div></div><div class="notice info">The server exposes only the app's allowed pages and assets. The database, host key, source scenario file and secret incident deck are not downloadable from public routes. This is still a trusted-LAN HTTP classroom app, not a public hosting service.</div></div>`;
}
function briefing(admin=false){
  return `<div class="hero-brief"><div class="row between"><span class="eyebrow">Mission ${String(S.round_index+1).padStart(2,'0')} / ${S.scenario_order.length}</span>${pill(money(S.rules.budget)+' fresh budget','warm')}</div><h2>${e(S.scenario.name)}</h2><div class="context">${S.scenario.context.map(p=>`<p>${e(p)}</p>`).join('')}${S.scenario.list?`<ul>${S.scenario.list.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`:''}</div></div><div class="section-title"><h3>The exposed risks</h3><small>${S.incident_count} will occur</small></div>${riskCards()}<div class="notice mt">Your challenge: agree your priority risks and a maximum bid before the auction begins. You may buy only ${S.rules.max_buys} different mitigations; ${S.copies===1?'only one team':'only '+S.copies+' teams'} can own each one.</div>${admin?`<div class="row mt">${mutateBtn('Open the auction &#8594;','open_auction','primary big')}${mutateBtn('Start 3-minute discussion','discussion','big')}</div>`:''}<div class="seal">Incident commitment: ${e(S.round.commitment)}<br>The secret order was fixed before bidding. Proof appears after the last reveal.</div>${mode!=='screen'?`<details id="brief-catalogue" class="mt"><summary class="muted">Study the auction catalogue (${S.scenario.mits.length} lots)</summary><div class="mt">${catalogue(false)}</div></details>`:''}`;
}
function riskCards(){
  return `<div class="risk-grid">${S.scenario.risks.map(r=>`<div class="risk-card ${S.round?.revealed.includes(r.id)?'hit':''}"><span class="badge">${r.id}</span><p>${e(r.d)}${S.round?.revealed.includes(r.id)?'<br><span class="tiny negative">INCIDENT OCCURRED</span>':''}</p></div>`).join('')}</div>`;
}
function catalogue(admin=false){
  return `<div class="lot-grid">${S.scenario.mits.map(m=>{
    const purchases=sold(m.id),left=S.copies-purchases.length,selected=S.round?.focus===m.id;
    const classes=`lot-card ${selected?'active':''} ${left===0?'exhausted':''}`;
    const inner=`<div class="row between"><span class="badge">${m.id}</span>${pill(left?left+' '+(left===1?'copy':'copies')+' left':'Sold out',left?'neutral':'live')}</div><h4>${e(m.d)}</h4><div class="lot-meta"><span>Opening price</span><strong class="mono">${money(m.p)}</strong></div>${purchases.length?`<div class="owners">${purchases.map(p=>`${e(team(p.team_id).name)} ${money(p.price)}`).join(' &middot; ')}</div>`:''}${S.round?.passed.includes(m.id)&&left?'<div class="tiny muted mt-sm">Passed &middot; may reopen before auction closes</div>':''}`;
    return admin?`<button class="${classes}" data-act="focus" data-mid="${m.id}" data-mutate ${left?'':'disabled'}>${inner}</button>`:`<div class="${classes}">${inner}</div>`;
  }).join('')}</div>`;
}
function chooseBidDraft(m){
  if(bidDraft.focus!==m.id){bidDraft={focus:m.id,price:S.round.bid?.price||m.p,team:S.round.bid?.team_id||''};}
  const eligible=S.teams.filter(t=>owned(t.id).length<S.rules.max_buys&&!owned(t.id).some(p=>p.mid===m.id)&&cash(t.id)>=m.p);
  if(!eligible.some(t=>t.id===bidDraft.team))bidDraft.team=eligible[0]?.id||'';
  return eligible;
}
function auctionFocus(admin=false){
  const r=S.round,m=lot(r.focus);
  if(!m)return `<div class="empty-state"><div class="symbol">&#9671;</div><h3>The auction floor is yours.</h3><p>${admin?'Select a mitigation below to put it on every screen.':'The instructor is choosing the next mitigation. Agree your walk-away price with your team.'}</p></div>`;
  const bid=r.bid,done=r.call==='sold',left=S.copies-sold(m.id).length;
  const call={open:bid?'Bidding open':'Ready to open',once:'Going once...',twice:'Going twice...',sold:'SOLD',passed:'Passed for now'}[r.call];
  let controls='';
  if(admin){
    const eligible=chooseBidDraft(m);
    const soldOut=left===0;
    if(done){
      controls=`<div class="bid-box row">${left?mutateBtn('Open the next copy','focus','primary',`data-mid="${m.id}"`):pill('All copies sold','live')}${mutateBtn('Move to next available lot','next-lot','')}<span class="tiny muted">Each copy is auctioned separately.</span></div>`;
    }else{
      controls=`<div class="bid-box"><div class="bid-grid"><div><label for="bid-team" class="form-label">Leading / winning team</label><select id="bid-team" class="field">${eligible.length?'':'<option value="">No eligible team</option>'}${eligible.map(t=>`<option value="${t.id}" ${bidDraft.team===t.id?'selected':''}>${e(t.name)} &middot; ${money(cash(t.id))} left</option>`).join('')}</select></div><div><label class="form-label" for="bid-price">Price called in the room</label><input id="bid-price" class="field" type="number" min="${m.p}" max="10000" step="1" value="${e(bidDraft.price)}"></div></div><div class="row mt-sm">${[100,250,500].map(n=>btn('+'+money(n),'bump','small ghost',`data-increment="${n}"`,!eligible.length||soldOut)).join('')}<span class="tiny muted">Edits go live when you publish.</span></div><div class="bid-actions">${mutateBtn('Publish live bid','bid','primary','',!eligible.length||soldOut)}${mutateBtn('Going once','once','','',!bid||soldOut)}${mutateBtn('Going twice','twice','','',!bid||soldOut)}</div><div class="bid-actions">${mutateBtn('SOLD - record purchase','sell','mint','',!eligible.length||soldOut)}${mutateBtn('Pass this lot','pass','ghost')}</div><p class="tiny muted mt-sm">A published bid does not spend money. Only SOLD records a purchase. No team can submit a bid from its viewer.</p></div>`;
    }
  }
  return `<div class="auction-focus ${done?'sold celebrate':''}"><div class="row between"><span class="eyebrow">Live auction / ${m.id}</span>${pill(left+' of '+S.copies+' copies available',done?'live':'warm')}</div><h2>${e(m.d)}</h2><div class="auction-bottom"><div><div class="price-label">${done?'Winning price':bid?'Current bid':'Opening price'}</div><div class="price">${money(bid?.price||m.p)}</div><div class="row mt-sm">${bid?`${dot(bid.team_id)}<strong>${e(team(bid.team_id).name)}</strong>`:'<span class="muted">Who will open the bidding?</span>'}</div></div><div class="text-right"><span class="hammer">${call}</span><div class="tiny muted mt-sm">Opening price ${money(m.p)}</div></div></div>${controls}</div>`;
}
function receipts(){
  if(!S.round.purchases.length)return '';
  return `<details class="card mt" id="receipts"><summary><strong>Receipts &amp; corrections</strong> <span class="tiny muted">(${S.round.purchases.length} sales)</span></summary><p class="tiny muted mt-sm">Refunds are allowed only while this auction is still open. The instructor can then re-auction that copy.</p>${S.round.purchases.slice().reverse().map(p=>`<div class="receipt"><div><strong>${p.mid}</strong> &middot; ${e(team(p.team_id).name)}<div class="tiny muted">${money(p.price)}</div></div>${mutateBtn('Refund','refund','small danger',`data-purchase="${p.id}"`)}</div>`).join('')}</details>`;
}
function auction(admin=false){
  return `${title('The mitigation market','Call it. Win it. Own the trade-off.',admin?'Your inputs control the price shown on every viewer. Teams bid aloud, not on their phones.':'Bid aloud to the instructor. A live bid is not a purchase until the hammer falls.')}${auctionFocus(admin)}<div class="section-title"><h3>${admin?'Choose the next lot':'The auction catalogue'}</h3><small>${S.scenario.mits.length} strategies &middot; ${S.copies} copies each</small></div>${catalogue(admin)}${admin?`${receipts()}<div class="card warm mt"><h3>Ready for the unexpected?</h3><p class="subtitle">Closing the auction permanently locks this round's purchases and refunds. Unsold lots stay unsold. Incident reveals cannot be undone.</p><div class="mt">${mutateBtn('Lock auction & enter incident room','close_auction','primary big')}</div></div>`:''}`;
}
function incidentTrack(){
  return `<div class="incident-track ${S.incident_count===3?'three':''}">${Array.from({length:S.incident_count},(_,i)=>`<div class="incident-token ${S.round.revealed[i]?'revealed':''}">${S.round.revealed[i]?`0${i+1} &middot; ${S.round.revealed[i]} revealed`:`0${i+1} &middot; SEALED`}</div>`).join('')}</div>`;
}
function incidentStage(){
  const incidents=S.round.incidents,last=incidents[incidents.length-1];
  if(!last)return `<div class="empty-state"><div class="symbol">&#9889;</div><h3>The market is closed.<br>The launch is not safe yet.</h3><p class="mt-sm">${S.incident_count} incidents were sealed before the auction. No rerolls. No last-minute purchases.</p></div>`;
  const ids=mode==='team'?[teamId]:S.teams.map(t=>t.id);
  return `<div class="incident-stage pulse-in"><div class="row between"><span class="eyebrow" style="color:var(--red)">Breaking / incident ${incidents.length}</span>${pill(last.rid,'red')}</div><h2>${e(last.headline)}</h2><p>${e(last.description)}</p><div class="impact-grid">${ids.map(id=>{
    const l=score(id).lines.find(l=>l.rid===last.rid);return `<div class="impact ${l.kind}"><div class="team-name">${e(team(id).name)}</div><b>${points(l.points)}</b><small>${l.kind==='high'?'Highly correlated':l.kind==='partial'?'Partially correlated':'Unmanaged'}${l.mid?' &middot; '+l.mid:''}</small></div>`;
  }).join('')}</div><p class="tiny mt">This incident's mapping: ${last.answer.high} highly correlated &middot; ${last.answer.partial} partially correlated. Protection scores once per risk.</p></div>`;
}
function simulation(admin=false){
  const n=S.round.revealed.length;
  return `${title('The incident room','Now the decisions meet reality.',`${n} of ${S.incident_count} incidents revealed. Purchase records are locked.`)}${incidentTrack()}${incidentStage()}${admin?`<div class="row mt">${mutateBtn(`Reveal incident ${n+1} of ${S.incident_count} &#8594;`,'reveal','primary big')}</div><p class="tiny muted mt-sm">Pause after each reveal. Ask one team: "Was that a risk you consciously accepted?"</p>`:''}<div class="notice mt">Scores are provisional during the reveal. Cash savings, clean sweep and any all-missed adjustment are added only after the last incident.</div><div class="section-title"><h3>Live round points</h3></div>${roundScoreCards(false)}`;
}
function scoreParts(r){
  return `<div class="score-parts"><div><span>Incident points</span><strong class="${color(r.risk)}">${points(r.risk)}</strong></div><div><span>Cash bonus</span><strong>${points(r.budget)}</strong></div><div><span>Clean sweep</span><strong>${points(r.sweep)}</strong></div><div><span>All missed</span><strong class="${color(r.all_missed)}">${points(r.all_missed)}</strong></div><div><span>Strategy pitch</span><strong>${points(r.creative)}</strong></div><div><span>Cash left</span><strong>${money(r.remaining)}</strong></div></div>`;
}
function roundScoreCards(details=true,only=null){
  let rows=S.round_scores;if(only)rows=rows.filter(r=>r.team_id===only);
  return `<div class="score-list">${rows.map(r=>`<div class="score-card"><div class="score-head"><span class="board-rank">${r.rank}</span>${dot(r.team_id)}<div class="grow"><div class="team-name">${e(team(r.team_id).name)}</div><span class="tiny muted">${r.complete?'Round total':'Live incident points'}</span></div><div class="score-number ${color(r.total)}">${points(r.total)}</div></div>${scoreParts(r)}${details?`<details class="score-detail" id="score-${r.team_id}"><summary>Why this score?</summary>${r.lines.map(l=>`<div class="score-line"><span class="mono muted">${l.rid}</span><div>${e(l.description)}<div class="tiny muted mt-sm">${l.kind==='high'?'Highly correlated':l.kind==='partial'?'Partially correlated':'Unmanaged'}${l.mid?' &middot; '+l.mid:''}</div></div><strong class="${color(l.points)}">${points(l.points)}</strong></div>`).join('')}${r.reason?`<div class="notice mt-sm">Strategy bonus: ${e(r.reason)}</div>`:''}<p class="tiny muted mt-sm">Cash bonus uses complete $1,000 blocks, capped at +${S.rules.budget_cap}. High and partial protection do not stack.</p></details>`:''}</div>`).join('')}</div>`;
}
function pitchSpotlight(){
  return `<div class="pitch"><div class="row between"><div class="eyebrow" style="color:var(--blue)">The board wants an answer</div>${S.pitch_team?pill('On the floor','live'):pill('Prepare your pitch')}</div><h3>${S.pitch_team?e(team(S.pitch_team).name)+', defend your strategy.':'You bought protection. What did you leave exposed?'}</h3><p>${e(S.challenge)}</p>${S.pitch_team?'<div class="timer mt" data-clock>00:45</div>':''}<p class="tiny mt">A clear trade-off, an honest limitation, and a credible fallback can earn +5. The instructor decides and records the reason.</p></div>`;
}
function pitchControls(){
  return `<div class="section-title"><h3>Give every team the floor</h3><small>45 seconds each</small></div>${S.teams.map(t=>{
    const awarded=S.round.bonuses[t.id];return `<div class="pitch-controls"><div class="row between"><div class="row">${dot(t.id)}<strong>${e(t.name)}</strong>${awarded?pill('+5 awarded','live'):''}</div>${mutateBtn('Spotlight & start 45s','pitch','small',`data-team="${t.id}"`)}</div><div class="row mt-sm"><input class="field grow" id="reason-${t.id}" maxlength="240" placeholder="Reason for a defensible strategy (minimum 8 characters)" value="${e(awarded||'')}">${mutateBtn(awarded?'Update reason':'Award +5','bonus','small primary',`data-team="${t.id}"`)}${awarded?mutateBtn('Remove','remove-bonus','small ghost',`data-team="${t.id}"`):''}</div></div>`;
  }).join('')}`;
}
function sealedProof(){
  const p=S.round?.proof;
  if(!p)return '';
  return `<details class="card mt" id="proof"><summary><strong>The sealed draw is now open</strong> <span class="tiny positive">&middot; ${p.verified?'commitment matches':'check failed'}</span></summary><p class="subtitle">These incidents were chosen before bidding: <strong>${p.deck.join(' &#8594; ')}</strong>. The random salt prevented viewers from guessing a small risk deck from the public hash.</p><div class="seal">Round ID: ${e(p.round_id)}<br>Salt: ${e(p.salt)}<br>Commitment: ${e(S.round.commitment)}<br>${e(p.format)}</div><p class="tiny muted">This is an audit aid, not an external authority: the instructor still owns the computer and can restore a backup. Use the visible activity record to keep the room fair.</p></details>`;
}
function debrief(admin=false){
  return `${title('The boardroom','Explain the decision, not the luck.','The incidents are complete. Pitch bonuses can still change the round winner.')}${incidentTrack()}${pitchSpotlight()}${admin?pitchControls():''}<div class="section-title"><h3>Round scores &middot; provisional until banked</h3></div>${roundScoreCards()}${admin?`<div class="card warm mt"><h3>Every team had its say?</h3><p class="subtitle">Banking freezes the pitch bonuses and records this round exactly once.</p><div class="mt">${mutateBtn('Bank round & reveal the podium','bank','primary big')}</div></div>`:''}${sealedProof()}`;
}
function podium(final=false){
  const winners=final?S.overall_winners:S.round_winners;
  const names=winners.map(id=>team(id).name).join(' + ');
  const value=final?overall(winners[0])?.total:score(winners[0])?.total;
  return `<div class="podium celebrate"><div class="trophy">&#9733;</div><div class="eyebrow">${final?'Tournament complete':`Round ${S.round_index+1} banked`}</div><h2>${e(names)}</h2><p>${winners.length>1?(final?'Shared champions. Equal points, equal credit.':'Joint round winners. Equal points, equal credit.'):(final?'Your LaunchSafe champions.':'This round belongs to you.')}</p><div class="winner-score">${points(value||0)} points</div></div>`;
}
function leaderboard(){
  return `<div class="board-list">${S.leaderboard.map(row=>`<div class="board-row ${row.rank===1?'leader':''}"><span class="board-rank">${row.rank}</span>${dot(row.team_id)}<div><div class="team-name">${e(team(row.team_id).name)}</div><div class="tiny muted">${points(row.banked)} banked${row.live?' &middot; '+points(row.live)+' live':''}</div></div><div class="board-points ${color(row.total)}">${points(row.total)}</div></div>`).join('')}</div>`;
}
function archiveTable(){
  if(!S.archive.length)return '';
  return `<div class="table-wrap mt"><table><thead><tr><th>Team</th>${S.archive.map((a,i)=>`<th title="${e(a.name)}">Round ${i+1}</th>`).join('')}<th>Banked</th></tr></thead><tbody>${S.leaderboard.map(r=>`<tr><td>${e(team(r.team_id).name)}</td>${S.archive.map(a=>`<td class="mono">${points(a.rows.find(x=>x.team_id===r.team_id).total)}</td>`).join('')}<td class="mono"><strong>${points(r.banked)}</strong></td></tr>`).join('')}</tbody></table></div>`;
}
function results(admin=false,final=false){
  const last=S.round_index+1>=S.scenario_order.length;
  return `${podium(final)}<div class="section-title"><h3>${final?'Final standings':'Progressive tournament standings'}</h3><small>${S.archive.length} banked round${S.archive.length===1?'':'s'}</small></div>${leaderboard()}${archiveTable()}${!final?`<details class="mt" id="result-detail"><summary class="muted">View this round's full score breakdown</summary><div class="mt">${roundScoreCards()}</div></details>`:`<div class="notice mt">Before the room leaves: ask each team to share one risk they would manage differently in a real project. A high score is a prompt for discussion, not proof that a real launch is safe.</div>`}${admin?`<div class="row mt">${!final?mutateBtn(last?'Crown the final champions':'Next round - fresh $10,000 &#8594;','next','primary big'):btn('Export final scores','csv','primary big')}${btn('Save game backup','export','big')}</div>${!final&&!last?'<p class="tiny muted mt-sm">Purchases reset. Tournament points stay. Rotate the team roles before the next briefing.</p>':''}`:''}${sealedProof()}`;
}
function stage(admin=false){
  const functions={brief:briefing,auction,simulation,debrief,round_end:results,finished:(a)=>results(a,true)};
  return functions[S.phase]?functions[S.phase](admin):'';
}
function ribbon(){
  return `<div class="screen-ribbon">${S.teams.map(t=>{const r=overall(t.id);return `<div class="ribbon-team ${tone(t.id)}"><div class="row gap8">${dot(t.id)}<span class="team-name">${e(t.name)}</span></div><div class="points ${color(r.total)}">${points(r.total)} <span class="tiny muted">total pts</span></div><div class="cash">${money(cash(t.id))} &middot; ${owned(t.id).length}/${S.rules.max_buys} bought</div></div>`;}).join('')}</div>`;
}
function screenSidebar(){
  return `<aside class="stack"><div class="card"><div class="row between"><h4>Team wallets</h4><span class="tiny muted">${S.rules.max_buys} max</span></div>${S.teams.map(t=>`<div class="ledger-mini">${dot(t.id)}<div class="grow"><div class="team-name truncate">${e(t.name)}</div><div class="slots">${owned(t.id).length}/${S.rules.max_buys} bought</div></div><span class="cash positive">${money(cash(t.id))}</span></div>`).join('')}<div class="row mt-sm"><img class="mini-qr" src="/qr.svg" alt="Team join QR"><p class="tiny muted grow">Join any time.<br>Scan and pick a team.</p></div></div></aside>`;
}
function screenPage(){
  let main;
  if(S.phase==='lobby')main=`${joinHero(true)}<div class="join-cards">${S.teams.map(t=>`<div class="card team-join ${tone(t.id)}">${dot(t.id)}<div class="grow"><div class="team-name">${e(t.name)}</div><div class="tiny muted" data-presence="${t.id}"></div></div></div>`).join('')}</div><div class="notice mt">${S.rules.name} scoring &middot; ${S.copies} copies of each lot &middot; ${S.incident_count} sealed incidents. Bids are called aloud. No phone bidding.</div>`;
  else if(S.phase==='auction')main=`${phaseTrack()}<div class="screen-layout"><section>${title('The mitigation auction','What is protection worth?','Raise your hand. Call your bid. The instructor records the sale.')}${auctionFocus(false)}<div class="notice mt">Maximum ${S.rules.max_buys} different mitigations per team. ${S.copies} copies per lot. No shared purchases or post-incident corrections.</div></section>${screenSidebar()}</div>${ribbon()}`;
  else if(S.phase==='simulation')main=`${phaseTrack()}${incidentTrack()}${incidentStage()}${ribbon()}<p class="tiny muted mt-sm">Total = previously banked points + live incident points. End-of-round adjustments wait for the final reveal.</p>`;
  else if(S.phase==='debrief')main=`${phaseTrack()}${pitchSpotlight()}<div class="section-title"><h3>Live round scores</h3><small>Pitch bonuses still open</small></div>${roundScoreCards(false)}${ribbon()}`;
  else if(S.phase==='brief')main=`${phaseTrack()}${briefing(false)}${ribbon()}`;
  else main=results(false,S.phase==='finished');
  return `${publicHeader()}<main class="screen-shell">${banner()}${main}</main>`;
}
function wallet(){
  const total=overall(teamId)?.total||0;return `<div class="wallet"><div><div class="label">Your cash</div><div class="value cash">${money(cash(teamId))}</div></div><div><div class="label">Protection</div><div class="value">${owned(teamId).length}<span class="muted">/${S.rules.max_buys}</span></div></div><div><div class="label">Total points</div><div class="value ${color(total)}">${points(total)}</div></div></div>`;
}
function teamLive(){
  if(S.phase==='lobby')return `<div class="card warm"><div class="eyebrow">Connected to the room</div><h2 class="mt-sm">Your team is in.</h2><p class="subtitle">The instructor will start the game. Your viewer follows automatically. Agree who speaks at the auction and who watches the budget.</p><div class="notice mt">No buttons to bid. Raise your hand and call your offer to the instructor.</div></div><div class="mt">${publicRules()}</div><div class="mt">${roleCards()}</div>`;
  if(S.phase==='brief')return `${phaseTrack()}${briefing(false)}<div class="mt">${roleCards()}</div>`;
  if(S.phase==='auction')return `${phaseTrack()}<div class="row between mb">${pill('Auction is live','live')}<div class="timer small" data-clock>00:00</div></div>${auctionFocus(false)}<div class="notice mt">Your phone is a viewer. Agree a price with your team, then bid aloud. Cash changes only when the instructor records SOLD.</div><details class="mt" id="team-catalogue"><summary class="muted">Browse all ${S.scenario.mits.length} mitigation lots</summary><div class="mt">${catalogue(false)}</div></details>`;
  if(S.phase==='simulation')return `${phaseTrack()}${incidentTrack()}${incidentStage()}<div class="section-title"><h3>Your live round score</h3></div>${roundScoreCards(true,teamId)}<p class="tiny muted mt">Cash and round adjustments are still pending.</p>`;
  if(S.phase==='debrief')return `${phaseTrack()}${pitchSpotlight()}<div class="section-title"><h3>Your round outcome</h3></div>${roundScoreCards(true,teamId)}${sealedProof()}`;
  return `${podium(S.phase==='finished')}<div class="section-title"><h3>Your round breakdown</h3></div>${roundScoreCards(true,teamId)}<div class="section-title"><h3>Overall standings</h3></div>${leaderboard()}${S.phase==='round_end'?'<div class="notice mt">The round is banked. The next round starts when the instructor is ready; your viewer updates automatically.</div>':''}`;
}
function portfolio(){
  const items=owned(teamId);
  return `${title('Your protection portfolio','Know what you paid for.',`${items.length} of ${S.rules.max_buys} purchase slots used. ${money(cash(teamId))} available this round.`)}${items.length?`<div class="stack">${items.map(p=>{const m=lot(p.mid);return `<div class="portfolio-item"><div class="row between">${pill(p.mid,'live')}<strong class="mono">${money(p.price)}</strong></div><h4>${e(m?.d||p.mid)}</h4><p>Purchased by the instructor. Opening price ${money(m?.p||0)}. ${finishedRound()?'Review the score breakdown to see how it performed.':'The risk mapping stays hidden until incidents reveal it.'}</p></div>`;}).join('')}</div>`:'<div class="empty-state"><h3>No purchases yet.</h3><p>Discuss your strategy, then bid aloud during the auction.</p></div>'}<div class="notice mt">No duplicate mitigations. No spending beyond ${money(S.rules.budget)}. Purchased protection lasts for this scenario only.</div>${finishedRound()?`<div class="mt">${roundScoreCards(true,teamId)}</div>`:''}`;
}
function teamBrief(){
  if(S.phase==='lobby')return publicRules();
  return `${title('Keep the mission in sight',e(S.scenario.name))}<div class="card context">${S.scenario.context.map(p=>`<p>${e(p)}</p>`).join('')}${S.scenario.list?`<ul>${S.scenario.list.map(p=>`<li>${e(p)}</li>`).join('')}</ul>`:''}</div><div class="section-title"><h3>Exposed risks</h3></div>${riskCards()}<details class="mt" id="team-rules"><summary class="muted">Scoring rules</summary><div class="mt">${publicRules()}</div></details><div class="mt">${roleCards()}</div>`;
}
function teamPage(){
  if(!S.teams.some(t=>t.id===teamId))return `<header class="site-header">${brand()}</header><main class="phone-shell"><div class="card"><h2>This team is no longer in the room.</h2><p class="subtitle">The instructor may have changed the setup or started a new game.</p><a class="btn primary mt" href="/join">Choose a current team</a></div></main>`;
  const tabs=[['live','&#9673;','Live room'],['portfolio','&#9635;','My protection'],['brief','&#9671;','Risk brief'],['board','&#9733;','Standings']];
  const content=teamTab==='portfolio'?portfolio():teamTab==='brief'?teamBrief():teamTab==='board'?`${title('The race so far','Tournament standings.','Banked scores plus this round\'s live points. Unrevealed incidents are not scored.')}${leaderboard()}${archiveTable()}`:teamLive();
  return `<header class="site-header phone-header">${brand('Team viewer')}<div class="public-tools">${pill('View only','live')}<a href="/join" class="btn small ghost">Switch team</a></div></header><main class="phone-shell"><div class="team-identity">${dot(teamId)}<div class="grow"><div class="eyebrow">${S.phase==='lobby'?'Waiting for the instructor':`Round ${S.round_index+1} / ${S.scenario_order.length} &middot; ${phaseNames[S.phase]}`}</div><h1 class="mt-sm">${e(team(teamId).name)}</h1></div></div>${wallet()}${banner()}${content}<p class="local-note">Live, read-only viewer &middot; reconnects automatically &middot; ${e(S.rules.name)} scoring</p></main><nav class="mobile-tabs" aria-label="Team viewer navigation">${tabs.map(([id,icon,label])=>`<button class="${teamTab===id?'active':''}" data-act="team-tab" data-tab="${id}" aria-current="${teamTab===id?'page':'false'}"><span class="tab-icon">${icon}</span><span>${label}</span></button>`).join('')}</nav>`;
}
function qrModal(){
  $('#modal-root').innerHTML=`<div class="overlay" data-act="close-modal"><div class="modal center" role="dialog" aria-modal="true" aria-label="Team join QR"><div class="row between"><span class="eyebrow">Team access</span>${btn('Close','close-modal','small ghost')}</div><h2 class="mt">Scan. Pick your team.</h2><div class="qr-frame"><img src="/qr.svg" alt="Scan to join LaunchSafe"></div><div class="mono tiny wrap-anywhere">${e(S.network.join)}</div><p class="subtitle">Use the same reachable classroom network. No app installation. No bidding from phones.</p>${btn('Copy join link','copy','primary mt',`data-text="${e(S.network.join)}"`)}</div></div>`;
  $('#modal-root .btn')?.focus();
}
async function copyText(value){
  try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(value);}else{const input=document.createElement('textarea');input.value=value;input.style.position='fixed';input.style.opacity='0';document.body.append(input);input.select();if(!document.execCommand('copy'))throw Error('copy');input.remove();}toast('Link copied.');}
  catch{window.prompt('Copy this link:',value);}
}
async function downloadProtected(path,name){
  try{const res=await fetchTimed(path,{headers:{Authorization:'Bearer '+token}});if(!res.ok)throw Error('Could not export this game.');const blob=await res.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Export created.');}catch(err){toast(err.message,true);}
}
function play(kind){
  if(!soundOn||!audio)return;
  try{
    if(audio.state==='suspended')audio.resume();
    const sequence=kind==='win'?[[523,.12],[659,.12],[784,.12],[1046,.35]]:kind==='incident'?[[160,.2],[120,.25]]:kind==='time'?[[880,.15],[880,.15],[880,.25]]:[[190,.07],[95,.13]];
    let t=audio.currentTime;
    sequence.forEach(([freq,len])=>{const osc=audio.createOscillator(),gain=audio.createGain();osc.type=kind==='sold'?'triangle':'sine';osc.frequency.value=freq;gain.gain.setValueAtTime(.0001,t);gain.gain.exponentialRampToValueAtTime(.12,t+.01);gain.gain.exponentialRampToValueAtTime(.0001,t+len);osc.connect(gain);gain.connect(audio.destination);osc.start(t);osc.stop(t+len+.02);t+=len+.05;});
  }catch{}
}
function readBid(){return {mid:S.round.focus,team_id:$('#bid-team')?.value||bidDraft.team,price:Number($('#bid-price')?.value||bidDraft.price)};}
function readBidDraft(){if($('#bid-team'))bidDraft.team=$('#bid-team').value;if($('#bid-price'))bidDraft.price=$('#bid-price').value;}

document.addEventListener('input',event=>{
  if(event.target.closest('#setup-form'))gatherSetup();
  if(['bid-team','bid-price'].includes(event.target.id))readBidDraft();
});
document.addEventListener('change',event=>{
  if(event.target.id==='team-count'){
    const d=gatherSetup(),n=Number(event.target.value);
    while(d.teams.length<n)d.teams.push({name:'Team '+(d.teams.length+1),members:''});
    d.teams.length=n;render();
  }
  if(['profile','copies','incident-count'].includes(event.target.id)){gatherSetup();render();}
  if(event.target.id==='bid-team')readBidDraft();
});
document.addEventListener('submit',async event=>{
  if(event.target.id==='login-form'){
    event.preventDefault();token=$('#host-secret').value.trim();writeSession('launchsafe-host',token);await poll(true);
  }
  if(event.target.id==='setup-form'){
    event.preventDefault();const ok=await act('setup',gatherSetup());if(ok){setupDraft=null;render();toast('Room settings saved.');}
  }
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-act]');if(!button||button.disabled)return;
  const action=button.dataset.act;
  if(action==='close-modal'){
    if(button.classList.contains('overlay') && event.target!==button)return;
    $('#modal-root').innerHTML='';return;
  }
  if(action==='host-tab'){if($('#setup-form'))gatherSetup();hostTab=button.dataset.tab;render();window.scrollTo(0,0);return;}
  if(action==='team-tab'){teamTab=button.dataset.tab;render();window.scrollTo(0,0);return;}
  if(action==='qr'){qrModal();return;}
  if(action==='copy'){await copyText(button.dataset.text);return;}
  if(action==='print'){window.print();return;}
  if(action==='fullscreen'){
    try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{toast('Use your browser full-screen control.');}return;
  }
  if(action==='sound'){
    try{if(!audio)audio=new (window.AudioContext||window.webkitAudioContext)();soundOn=!soundOn;await audio.resume();render();tick();if(soundOn)play('sold');}catch{toast('Sound is not available in this browser.');}return;
  }
  if(mode!=='host')return;
  if(busy)return;
  if(action==='fun-names'){
    const d=gatherSetup(),names=['Circuit Breakers','Risk Rangers','Rollback Rebels','Code Commandos','Control Alt Elite','The Hotfix Crew','Release Rangers','Cache Me Outside','Deadline Dodgers','Bug Busters','Safe Deployers','The Test Pilots'];
    d.teams.forEach((t,i)=>t.name=names[i]);render();return;
  }
  if(action==='start'){
    if(!$('#setup-form').reportValidity())return;
    if(!getSetupDraft().scenario_order.length){toast('Choose at least one scenario.',true);return;}
    if(await act('setup',gatherSetup())){setupDraft=null;await act('start');}return;
  }
  if(action==='focus'){bidDraft={focus:null,team:'',price:''};if(await act('focus',{mid:button.dataset.mid}))window.scrollTo({top:90,behavior:'smooth'});return;}
  if(action==='next-lot'){
    const available=S.scenario.mits.filter(m=>sold(m.id).length<S.copies);
    const currentIndex=S.scenario.mits.findIndex(m=>m.id===S.round.focus);
    const next=available.find(m=>S.scenario.mits.indexOf(m)>currentIndex)||available[0];
    if(next){bidDraft={focus:null,team:'',price:''};await act('focus',{mid:next.id});window.scrollTo({top:90,behavior:'smooth'});}else toast('All copies sold. Close the auction when ready.');return;
  }
  if(action==='bump'){readBidDraft();bidDraft.price=Number(bidDraft.price)+Number(button.dataset.increment);$('#bid-price').value=bidDraft.price;return;}
  if(action==='bid'){await act('bid',readBid());return;}
  if(action==='sell'){
    const data=readBid();
    if(!data.team_id){toast('There is no eligible team for this lot.',true);return;}
    if(confirm(`Record SOLD: ${data.mid} to ${team(data.team_id).name} for ${money(data.price)}?`))await act('sell',data);return;
  }
  if(action==='once'||action==='twice'){await act('call',{value:action});return;}
  if(action==='refund'){
    const p=S.round.purchases.find(p=>p.id===button.dataset.purchase);
    if(p&&confirm(`Refund ${money(p.price)} to ${team(p.team_id).name} and return ${p.mid} to the auction?`))await act('refund',{purchase_id:p.id});return;
  }
  if(action==='close_auction'){
    if(confirm('Lock every purchase and refund for this round? You cannot reopen the auction after seeing incidents.'))await act(action);return;
  }
  if(action==='bank'){
    if(confirm('Have all teams had a chance to pitch? Bank the round and lock its bonuses?'))await act(action);return;
  }
  if(action==='timer-preset'){await act('timer',{operation:'set',seconds:Number(button.dataset.seconds)});return;}
  if(action==='timer-set'){await act('timer',{operation:'set',seconds:Number($('#timer-seconds').value)});return;}
  if(action==='timer-toggle'){await act('timer',{operation:S.timer.running?'pause':'start'});return;}
  if(action==='discussion'){if(await act('timer',{operation:'set',seconds:180}))await act('timer',{operation:'start'});return;}
  if(action==='announce'){await act('announce',{message:$('#announcement').value});return;}
  if(action==='clear-announce'){await act('announce',{message:''});return;}
  if(action==='pitch'){await act('pitch',{team_id:button.dataset.team,seconds:45});return;}
  if(action==='bonus'){await act('bonus',{team_id:button.dataset.team,enabled:true,reason:$('#reason-'+button.dataset.team).value});return;}
  if(action==='remove-bonus'){await act('bonus',{team_id:button.dataset.team,enabled:false});return;}
  if(action==='export'){await downloadProtected('/api/export','launchsafe-backup.json');return;}
  if(action==='csv'){await downloadProtected('/api/scores.csv','launchsafe-scores.csv');return;}
  if(action==='restore'){
    const file=$('#restore-file').files[0];if(!file){toast('Select a native LaunchSafe Live JSON backup first.',true);return;}
    if(file.size>950000){toast('Backup is too large.',true);return;}
    try{const backup=JSON.parse(await file.text());const confirmation=prompt('This replaces the current game. Export it first. Type RESTORE to continue:');if(confirmation==='RESTORE'){if(await act('restore',{backup,confirmation})){setupDraft=null;hostTab='stage';render();toast('Backup restored; timer paused.');}}}catch{toast('The selected file is not valid JSON.',true);}return;
  }
  if(action==='reset'){
    const confirmation=prompt('This resets the session. Export a backup first. Type NEW GAME to continue:');
    if(confirmation==='NEW GAME'){if(await act('reset',{confirmation})){setupDraft=null;hostTab='stage';render();}}return;
  }
  if(['open_auction','pass','reveal','next'].includes(action))await act(action);
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')$('#modal-root').innerHTML='';});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll(true);});
window.addEventListener('online',()=>poll(true));
if(mode==='host'&&!token)renderLogin();else poll(true);
setInterval(()=>poll(),1200);
setInterval(tick,200);
