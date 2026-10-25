'use strict';
/* lane-board. Three screens — home, work, memory — and one command bar above them.
   Navigation is the palette (Cmd-K); esc always steps back out to home. */

const T=window.__T;
const THEMES=['system','light','dark'];
/* data-theme is always set, to light or dark: board.css defines dark once, on :root[data-theme="dark"].
   On "system" it follows prefers-color-scheme, live. index.html sets it before first paint. */
const DARKQ=matchMedia('(prefers-color-scheme: dark)');let THEME='system';
function syncTheme(){document.documentElement.dataset.theme=THEME==='dark'||(THEME==='system'&&DARKQ.matches)?'dark':'light'}
DARKQ.addEventListener('change',syncTheme);
function applyTheme(v){THEME=THEMES.includes(v)?v:'system';syncTheme();
  try{localStorage.setItem('lane-theme',THEME)}catch{}
  const b=document.getElementById('theme');if(b){b.textContent=v==='light'?'☀':v==='dark'?'☾':'◐';b.title='Theme: '+v+'. Click to cycle system → light → dark'}}
{let th=new URLSearchParams(location.search).get('theme');if(!th){try{th=localStorage.getItem('lane-theme')}catch{}}applyTheme(THEMES.includes(th)?th:'system')}

const S={view:'home',board:null,lane:null,repo:null,sel:{},data:null,diff:null,diffKey:'',busy:null,dialog:false,
  filter:'',startedAt:null,fails:0,diffAll:false,mem:null,mscope:'cross',mfile:null,
  pal:{open:false,q:'',rows:[],i:0},
  // which registered control plane the board is scoped to right now. null (or 'home') means
  // whichever plane the server was started from/inside — the least-surprising default. Any
  // other value is a name from /api/planes: api() below prefixes every request with /api/w/<name>,
  // and the page's own URL carries the same /w/<name> prefix, so no call site has to know about it.
  plane:null,planes:null};
const $=s=>document.querySelector(s);
/* API resources: the path names the thing, the query only how to show it */
const E=encodeURIComponent;
const laneApi=(id=S.lane)=>`/api/lanes/${E(id)}`;
const repoApi=()=>`${laneApi()}/repos/${E(S.repo)}`;
const post=(p,obj={})=>api(p,{method:'POST',body:JSON.stringify(obj)});
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api=async(p,o={})=>{
  const body=o.body;
  if(S.plane&&S.plane!=='home'&&p!=='/api/planes')p='/api/w/'+encodeURIComponent(S.plane)+p.slice(4);
  const r=await fetch(p,{...o,body,headers:{'X-Token':T,'Content-Type':'application/json'}});let j={};try{j=await r.json()}catch{}
  if(r.status===403){toast('err','Server restarted — reload the page');throw new Error('restarted')}
  if(!r.ok)throw Object.assign(new Error(j.error||j.output||r.statusText),{output:j.output});return j};

/* ---------- plane switcher: read-only selection, never a second server/tab ---------- */
function planeDisplayName(name){
  if(!name||name==='home')return(S.planes?.planes||[]).find(p=>p.home)?.name||'home';
  return name;
}
function updateTitle(){document.title='lane-board — '+planeDisplayName(S.plane)}
async function loadPlanes(){
  try{S.planes=await api('/api/planes')}catch{S.planes=null;return}
  const sel=$('#planeSel');if(!sel)return;
  const list=S.planes.planes||[];
  if(list.length<2){sel.classList.add('hidden');updateTitle();return}
  sel.classList.remove('hidden');
  sel.innerHTML=list.map(p=>`<option value="${esc(p.name)}"${(S.plane?S.plane===p.name:p.home)?' selected':''}>${esc(p.name)}${p.home?' (this)':''}</option>`).join('');
  updateTitle();
}
async function switchPlane(name){
  // Not persisted across reloads on purpose: a fresh load always defaults back to the plane the
  // server was started from/inside, per docs/board.md — the least-surprising behavior.
  S.plane=(S.planes?.planes||[]).find(p=>p.name===name)?.home?null:name;updateTitle();
  S.board=null;S.boardSig=null;S.lane=null;S.repo=null;S.data=null;
  await loadBoard();renderHome();renderCrumb();goHome();
}
/* localStorage holds conveniences only (theme, collapsed sections, the last repo per lane).
   Where you are lives in the URL: see the router below. */
const LSg=(k,d)=>{try{return localStorage.getItem(k)??d}catch{return d}};
const LSs=(k,v)=>{try{v==null?localStorage.removeItem(k):localStorage.setItem(k,v)}catch{}};
function rememberPlace(){if(S.lane&&S.repo)LSs('lane-repo:'+S.lane,S.repo)}
const ico=(n,c='')=>`<svg class="ic${c?' '+c:''}" viewBox="0 0 16 16"><use href="#g-${n}"/></svg>`;
const plural=(n,w)=>`${n} ${w}${n===1?'':'s'}`;

function prettyName(id,ticket){
  // the ticket field holds a full Jira URL — a visitor wants the key, not the link
  let tk=(/([A-Z]+-\d+)/.exec(ticket||'')||[])[1]||'';
  const m=/^([A-Z]+-\d+)-(.+)$/.exec(id);
  let s=id;
  if(m){tk=tk||m[1];s=m[2]}
  // a tail like "6237" is a second ticket number, not a name — then the id itself is the name
  if(!s||/^[\d-]+$/.test(s))return[id,''];
  s=s.replace(/[-_]+/g,' ').trim();
  return[s.charAt(0).toUpperCase()+s.slice(1),tk];
}
// Goal and resume notes are written by and for developers, in markdown. Show one clean sentence,
// not a wall of prose with backticks and branch names in it.
function plain(s){
  return String(s||'')
    .replace(/`([^`]*)`/g,'$1').replace(/\*\*([^*]*)\*\*/g,'$1')
    .replace(/(^|\s)[_*]([^_*\n]+)[_*](?=\s|$)/g,'$1$2')
    .replace(/\[([^\]]+)\]\([^)]*\)/g,'$1')
    .replace(/https?:\/\/\S+/g,'').replace(/\s+/g,' ').trim();
}
/* the lane template ships "(written by lane-park: ...)"-style placeholders; they are not content */
const realText=s=>/^\s*\([^)]*\)\s*$/.test(String(s||''))?'':String(s||'');
function firstSentence(s,max){
  s=plain(realText(s));if(!s)return'';
  const m=/^(.{20,}?[.!?])(\s|$)/.exec(s);
  let out=m?m[1]:s;
  if(out.length>max)out=out.slice(0,max).replace(/\s+\S*$/,'')+'…';
  return out;
}
function daysAgo(d){
  if(!d)return'';
  const t=new Date(d+'T00:00:00'),n=new Date();n.setHours(0,0,0,0);
  const k=Math.round((n-t)/86400000);
  return k<=0?'today':k===1?'yesterday':k<7?k+' days ago':k<14?'last week':k<60?Math.round(k/7)+' weeks ago':'a while ago';
}
const mem=()=>{const w=S.lane&&(S.sel[S.lane]||(S.sel[S.lane]={repo:null,files:{}}));return w};
const rmem=()=>{const w=mem();if(!w||!S.repo)return null;return w.files[S.repo]||(w.files[S.repo]={file:null,staged:false,tab:'diff',scroll:0})};
const cur=()=>S.board?.lanes.find(w=>w.id===S.lane);
const curRepo=()=>cur()?.repos.find(r=>r.repo===S.repo);
const shortOf=r=>r.short||r.repo;
/* A stable colour per repo, so a repo is the same shade everywhere it appears. Assigned
   explicitly: with six repos a hash collides (three of them all landed on the same slot),
   and a colour that is not distinct is worse than no colour. Unknown repos fall back to a
   hash over the slots nobody has claimed. */
const REPO_COLOUR={
  'web':'rp6',        // mauve
  'api':'rp3',          // indigo
  'worker':'rp5',          // teal
  'agent':'rp4',      // umber
  'tools':'rp2',   // olive
  'lib':'rp0',               // steel
  'docs':'rp1',                    // plum
};
function repoClass(repo){
  const s=String(repo||'');
  if(REPO_COLOUR[s])return REPO_COLOUR[s];
  const taken=new Set(Object.values(REPO_COLOUR));
  const free=['rp0','rp1','rp2','rp3','rp4','rp5','rp6','rp7'].filter(c=>!taken.has(c));
  const pool=free.length?free:['rp0','rp1','rp2','rp3','rp4','rp5','rp6','rp7'];
  let h=0;for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;
  return pool[h%pool.length];
}

/* ---------- toasts ---------- */
function toast(kind,text,opts={}){const box=$('#toasts');if(opts.replace&&opts.replace.isConnected)opts.replace.remove();
  const t=document.createElement('div');t.className='toast '+(kind==='ok'?'ok':kind==='err'?'err':'prog');
  t.innerHTML=`<svg class="ic ti2" viewBox="0 0 16 16"><use href="#g-${kind==='ok'?'check':kind==='err'?'warn':'commit'}"/></svg>`;
  const tx=document.createElement('div');tx.className='tx';tx.textContent=text;t.appendChild(tx);
  if(kind==='err'){const r=document.createElement('div');r.className='tr';if(opts.fix){const b=document.createElement('button');b.className='sm';b.textContent=opts.fix.label;b.onclick=()=>{t.remove();opts.fix.run()};r.appendChild(b)}const sp=document.createElement('span');sp.className='sp';r.appendChild(sp);const c=document.createElement('button');c.className='txt';c.textContent='Copy';c.onclick=()=>navigator.clipboard?.writeText(text);r.appendChild(c);const x=document.createElement('button');x.className='txt';x.textContent='Dismiss';x.onclick=()=>t.remove();r.appendChild(x);t.appendChild(r)}
  box.appendChild(t);while(box.children.length>3)box.firstChild.remove();if(kind==='ok')setTimeout(()=>t.remove(),3000);return t}
/* ---------- board ---------- */
async function memAct(verb,scope,file,to,lane){try{const j=await post(`/api/memory/${E(scope)}/${E(file)}/${verb}`,{to,lane});toast('ok',j.output||'done');S.mfile=null;await loadMemory()}catch(e){toast('err',e.message)}}
function scopeOptions(){return (S.mem?.scopes||[]).filter(s=>!['drafts'].includes(s.id)).map(s=>`<option value="${esc(s.id)}">${esc(s.label)} — ${esc(s.hint)}</option>`).join('')}
const dlgHead=(title,sub,icon,tone='')=>`<h3><span class="hi ${tone}">${ico(icon)}</span><span>${title}${sub?`<small>${sub}</small>`:''}</span></h3>`;
function memMoveDlg(file){const d=openDlg(dlgHead(`Move ${esc(file)}`,'Pick the scope by how long it stays true.','move')
  +`<label>New scope</label><select id="sc">${scopeOptions()}</select>
  <div class="infobox">${ico('info')}<span>Cross-repo stays true everywhere; a repo scope stays true for that repo after a ticket ships. The index lines are rewritten for you.</span></div>`,
  async d=>memAct('move',S.mscope,file,d.querySelector('#sc').value));d.querySelector('#dok').textContent='Move'}
function memFileDlg(file){const d=openDlg(dlgHead(`File ${esc(file)}`,'Where does it belong? Ask yourself how long it stays true.','inbox')
  +`<label>Scope</label><select id="sc">${scopeOptions()}${(S.board?.lanes||[]).filter(w=>w.status==='active').map(w=>`<option value="lane:${esc(w.id)}">lane ${esc(w.id)} — only while this work is live</option>`).join('')}</select>
  <div class="infobox">${ico('info')}<span>A lane scope lands in that lane's Findings and is archived with it; everything else becomes standing memory.</span></div>`,
  async d=>{const v=d.querySelector('#sc').value;return v.startsWith('lane:')?memAct('file','drafts',file,'lane',v.slice(5)):memAct('file','drafts',file,v)});d.querySelector('#dok').textContent='File it'}
function memRmDlg(file){openDlg(dlgHead(`Delete ${esc(file)}?`,'','trash','bad')+`<div class="warnbox bad"><b>This cannot be undone from here.</b> The file and its index line are removed.</div>`,async()=>memAct('delete',S.mscope,file));$('#dok').textContent='Delete';$('#dok').className='danger'}
function memDropDlg(file){openDlg(dlgHead(`Discard draft ${esc(file)}?`,'','trash','bad')+`<div class="warnbox bad"><b>The draft is thrown away.</b> Nothing was filed from it yet, so nothing else changes.</div>`,async()=>memAct('discard','drafts',file));$('#dok').textContent='Discard';$('#dok').className='danger'}
/* ---------- selection memory ---------- */
async function loadRepo(silent){const r=curRepo();const w=cur();if(!w){goHome();return}
  if(!r||!r.exists){S.data=null;renderRepo();return}
  try{const d=await api(repoApi());const prev=S.data;
    const sig=dataSig(d);const same=silent&&sig===S.dataSig;S.dataSig=sig;S.data=d;
    if(!same)renderRepo();
    const rm=rmem();if(rm.file){const f=d.files.find(x=>x.file===rm.file&&(rm.staged?x.staged:x.unstaged));if(!f){rm.file=null;renderStage(true)}else{const key=JSON.stringify([S.lane,S.repo,rm.file,rm.staged,f.add,f.del,f.add_staged,f.del_staged,d.log[0]?.sha]);if(key!==S.diffKey||!prev)await loadDiff(key)}}
  }catch(e){$('#files').innerHTML=`<div class="empty">Could not read this worktree. <button class="txt" onclick="loadRepo(false)">Retry</button><br><span class="mono">${esc(e.message)}</span></div>`}}
function fname(f){const i=f.lastIndexOf('/');return i<0?esc(f):`<span class="dir">${esc(f.slice(0,i+1))}</span>${esc(f.slice(i+1))}`}
function frow(f,staged){const rm=rmem();const sel=rm.file===f.file&&rm.staged===staged;const letter=staged?(f.index||'M'):(f.untracked?'?':(f.work||'M'));const cls=letter==='A'?'ok':letter==='D'?'bad':letter==='R'?'acc':letter==='?'?'muted':'warn';const a=staged?f.add_staged:f.add,dl=staged?f.del_staged:f.del;
  return`<div class="frow ${sel?'sel':''}" data-file="${esc(f.file)}" data-staged="${staged?1:0}" tabindex="0" title="${esc(f.file)}"><input type="checkbox" ${staged?'checked':''} ${f.partial&&!staged?'data-ind=1':''} tabindex="-1"><span class="st ${cls}" title="${({M:'modified',A:'added',D:'deleted',R:'renamed','?':'untracked (new, not in git yet)',C:'copied',U:'conflict'})[letter]||letter}">${esc(letter)}</span><span class="nm">${f.old?`<span class="dir">${esc(f.old)} → </span>`:''}${fname(f.file)}</span>${f.secret?'<span class="secret">secret</span>':''}${a!=null?`<span class="cnt" title="${a} line(s) added, ${dl} removed"><b class="ok">+${a}</b> <b class="bad">−${dl}</b></span>`:''}</div>`}
function inline(s){return esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g,'$1<i>$2</i>').replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g,'$1<i>$2</i>').replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank">$1</a>').replace(/(^|\s)(https?:\/\/[^\s<]+)/g,'$1<a href="$2" target="_blank">$2</a>')}
function md(src){const out=[];const lines=src.replace(/\r/g,'').split('\n');let i=0;
  if(lines[0]==='---'){const j=lines.indexOf('---',1);if(j>0){const rows=[];for(const l of lines.slice(1,j)){const m=/^(\s*)(?:- )?([\w.-]+):\s*(.*)$/.exec(l);if(m)rows.push(`<tr><td>${'&nbsp;'.repeat(m[1].length)}${esc(m[2])}</td><td>${inline(m[3])}</td></tr>`)}out.push(`<table class="fm">${rows.join('')}</table>`);i=j+1}}
  let list=null,para=[],code=null;
  const flushP=()=>{if(para.length){out.push(`<p>${inline(para.join(' '))}</p>`);para=[]}};const flushL=()=>{if(list){out.push(`<${list.t}>${list.items.map(x=>`<li>${inline(x)}</li>`).join('')}</${list.t}>`);list=null}};
  for(;i<lines.length;i++){const l=lines[i];
    if(code!==null){if(/^```/.test(l)){out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);code=null}else code.push(l);continue}
    if(/^```/.test(l)){flushP();flushL();code=[];continue}
    const h=/^(#{1,6})\s+(.*)$/.exec(l);if(h){flushP();flushL();out.push(`<h${h[1].length+1}>${inline(h[2])}</h${h[1].length+1}>`);continue}
    if(/^\s*[-*+]\s+/.test(l)){flushP();if(!list||list.t!=='ul'){flushL();list={t:'ul',items:[]}}list.items.push(l.replace(/^\s*[-*+]\s+/,''));continue}
    if(/^\s*\d+[.)]\s+/.test(l)){flushP();if(!list||list.t!=='ol'){flushL();list={t:'ol',items:[]}}list.items.push(l.replace(/^\s*\d+[.)]\s+/,''));continue}
    if(/^\s*(---|\*\*\*)\s*$/.test(l)){flushP();flushL();out.push('<hr>');continue}
    if(/^>\s?/.test(l)){flushP();flushL();out.push(`<blockquote>${inline(l.replace(/^>\s?/,''))}</blockquote>`);continue}
    if(!l.trim()){flushP();flushL();continue}
    if(list&&/^\s{2,}/.test(l)){list.items[list.items.length-1]+=' '+l.trim();continue}
    para.push(l.trim())}
  flushP();flushL();if(code)out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);return `<div class="md">${out.join('')}</div>`}
/* ---------- pane ---------- */
const PT={diff:'Diff',history:'History',notes:'Notes',refs:'Refs',spec:'Spec',sessions:'Sessions'};
const PT_TIP={refs:'Outside folders or files attached to this lane for reference (per lane)',diff:'Changes in the selected file (per file)',history:'Recent commits on this branch (per repo)',notes:'Goal and resume note from the lane file (per lane)',spec:'The whole lane file: frontmatter, goal, note, log (per lane)',sessions:'Old Claude conversations for this repo (per repo)'};
const srcLine=(what,scope)=>`<div class="src">${what}<span class="scope">${scope}</span></div>`;
async function loadDiff(key){const rm=rmem();S.diffKey=key||S.diffKey;S.diffAll=false;try{S.diff=await api(`${repoApi()}/diff?file=${E(rm.file)}&staged=${rm.staged?1:0}`)}catch(e){S.diff={error:e.message}}if(feedOf()!=='history'&&rm.file){S.stageSig=null;renderStage(true)}}
function renderDiff(){const rm=rmem(),d=S.data,body=$('#pbody');const f=d.files.find(x=>x.file===rm.file&&(rm.staged?x.staged:x.unstaged));
  if(!f){body.innerHTML=`<div class="center">${ico('check','big')}No changes in this file.</div>`;return}
  const D=S.diff;if(!D){body.innerHTML='<div class="center">Loading diff…</div>';return}
  if(D.error){body.innerHTML=`<div class="center">${ico('warn','big')}Could not read the diff.<br><span class="mono sm">${esc(D.error)}</span><br><br><button onclick="loadDiff()">Retry</button></div>`;return}
  if(D.secret){body.innerHTML=`<div class="center">${ico('warn','big')}<b>Secret file. The contents are never shown here.</b><br><span class="mono sm">Edit it in ${esc(D.mirror)}</span><br>It cannot be staged or committed from the board.</div>`;return}
  if(D.binary){body.innerHTML=`<div class="center">${ico('file','big')}Binary or very large file — ${(D.size/1048576).toFixed(1)} MB. Not shown.</div>`;return}
  if(!D.diff.trim()){body.innerHTML=`<div class="center">${ico('check','big')}No changes in this file.</div>`;return}
  const R=diffBody(D.diff,false,rm.file);
  body.innerHTML=R.meta+`<div class="diff">${R.rows}</div>`+moreLine(D,'showAll()')}

/* ---------- syntax highlighting ----------
   Small on purpose: no library, works offline, and it hands back token ranges rather than
   HTML so the word-level <mark> from the diff can be sliced into the same output.
   One line at a time — a diff has no state across lines — so an unterminated block comment
   or template literal only colours its own line. */
const SYN_EXT={ts:'js',tsx:'js',mts:'js',cts:'js',js:'js',jsx:'js',mjs:'js',cjs:'js',
  java:'java',kt:'java',py:'py',rb:'py',go:'go',rs:'go',c:'java',h:'java',cpp:'java',cs:'java',
  css:'css',scss:'css',less:'css',json:'json',jsonc:'json',yml:'yaml',yaml:'yaml',toml:'yaml',
  sh:'sh',bash:'sh',zsh:'sh',sql:'sql',md:'md',markdown:'md',html:'xml',xml:'xml',svg:'xml',vue:'xml'};
const SYN_KW={
  js:'as async await break case catch class const continue debugger default delete do else enum export extends false finally for from function get if implements import in instanceof interface let new null of private protected public readonly return satisfies set static super switch this throw true try type typeof undefined var void while yield keyof infer declare namespace abstract',
  java:'abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null var record sealed yield',
  py:'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case self',
  go:'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false let mut fn pub use impl struct enum match where async await move ref Self',
  css:'important from to and not or only media supports keyframes import charset font-face',
  sql:'select from where group by order having join left right inner outer on as insert into values update set delete create table alter drop index view union all distinct limit offset and or not null is in between like case when then else end',
  sh:'if then else elif fi for while do done case esac function return local export source alias unset in select time until',
  json:'true false null',yaml:'true false null yes no on off',md:'',xml:''};
const SYN_CACHE={};
function synRules(lang){
  if(SYN_CACHE[lang])return SYN_CACHE[lang];
  const kw=(SYN_KW[lang]||'').trim().split(/\s+/).filter(Boolean);
  const kwRe=kw.length?new RegExp('^(?:'+kw.join('|')+')$'):null;
  const parts=[];
  if(lang==='md'){
    parts.push(['com',/^(?:#{1,6}\s.*|\s*>.*)/],['str',/^`[^`]*`/],['kw',/^(?:\*\*[^*]+\*\*|_[^_]+_|\*[^*]+\*)/],
      ['fn',/^\[[^\]]*\]\([^)]*\)/],['pun',/^[-*+]\s/]);
  }else if(lang==='xml'){
    parts.push(['com',/^<!--[\s\S]*?(?:-->|$)/],['str',/^"(?:\\.|[^"\\])*"?|^'(?:\\.|[^'\\])*'?/],
      ['typ',/^<\/?[A-Za-z][\w:.-]*/],['att',/^[A-Za-z_:][\w:.-]*(?==)/],['pun',/^[<>/=]/]);
  }else{
    if(lang==='py'||lang==='yaml'||lang==='sh')parts.push(['com',/^#.*/]);
    if(lang==='sql')parts.push(['com',/^--.*/]);
    if(lang!=='py'&&lang!=='yaml'&&lang!=='sh'&&lang!=='sql')parts.push(['com',/^\/\/.*/],['com',/^\/\*[\s\S]*?(?:\*\/|$)/]);
    if(lang==='py')parts.push(['str',/^(?:[rbfu]{0,2})(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$))/]);
    parts.push(['str',/^`(?:\\.|[^`\\])*`?/],['str',/^"(?:\\.|[^"\\])*"?/],['str',/^'(?:\\.|[^'\\])*'?/]);
    if(lang==='sh')parts.push(['typ',/^\$\{?[A-Za-z_][\w]*\}?/]);
    if(lang==='css')parts.push(['typ',/^[.#][A-Za-z_-][\w-]*/],['att',/^--[\w-]+/],['num',/^-?\d*\.?\d+(?:px|rem|em|%|vh|vw|s|ms|fr|deg)?/]);
    if(lang==='yaml')parts.push(['att',/^[A-Za-z_][\w.-]*(?=\s*:)/]);
    if(lang==='json')parts.push(['att',/^"(?:\\.|[^"\\])*"(?=\s*:)/]);
    parts.push(['num',/^-?(?:0[xX][\da-fA-F]+|\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?)\b/]);
    parts.push(['word',/^[A-Za-z_$@][\w$]*/]);
    parts.push(['pun',/^[{}()[\];,.:?!<>=+\-*/%&|^~]+/]);
  }
  const r={parts,kwRe};SYN_CACHE[lang]=r;return r;
}
/* -> [[start, end, class], ...] covering the whole line, plain runs included */
function synTokens(text,lang){
  const out=[];if(!lang||!SYN_KW.hasOwnProperty(lang)){out.push([0,text.length,'']);return out}
  const{parts,kwRe}=synRules(lang);
  let i=0,plain=0;
  const flush=(to)=>{if(to>plain)out.push([plain,to,''])};
  while(i<text.length){
    const rest=text.slice(i);
    let hit=null;
    for(const[cls,re]of parts){const m=re.exec(rest);if(m&&m[0].length){hit=[cls,m[0].length];break}}
    if(!hit){i++;continue}
    let[cls,len]=hit;
    if(cls==='word'){
      const w=text.slice(i,i+len);
      const next=text.slice(i+len).match(/^\s*\(/);
      cls=kwRe&&kwRe.test(w)?'kw':/^[A-Z]/.test(w)?'typ':next?'fn':/^[@$]/.test(w)?'att':'';
    }
    if(cls===''){i+=len;continue}
    flush(i);out.push([i,i+len,cls]);i+=len;plain=i;
  }
  flush(text.length);
  return out.sort((a,b)=>a[0]-b[0]);
}
/* escape + colour + slice in the word-level diff mark, all in one pass */
function code(text,lang,mark){
  text=String(text??'');
  const toks=synTokens(text,lang);
  const[ms,me]=mark&&mark[1]>mark[0]?mark:[-1,-1];
  let html='',open=false;
  for(const[a,b,cls]of toks){
    let p=a;
    while(p<b){
      const inMark=ms>=0&&p>=ms&&p<me;
      const stop=Math.min(b,inMark?me:(ms>p?ms:b));
      const piece=esc(text.slice(p,stop));
      if(inMark&&!open){html+='<mark>';open=true}
      if(!inMark&&open){html+='</mark>';open=false}
      html+=cls?`<span class="k-${cls}">${piece}</span>`:piece;
      p=stop;
    }
  }
  if(open)html+='</mark>';
  return html;
}
const langOf=f=>SYN_EXT[String(f||'').split('.').pop().toLowerCase()]||'';

function diffBody(text,fileHeaders,file){
  let o=0,n=0;let lang=langOf(file);const rows=[];const meta=[];const lines=String(text||'').split('\n');
  const pair=(a,b)=>{let i=0;while(i<a.length&&i<b.length&&a[i]===b[i])i++;let j=0;while(j<a.length-i&&j<b.length-i&&a[a.length-1-j]===b[b.length-1-j])j++;
    if(i+j===0||(a.length-i-j)>a.length*.8&&(b.length-i-j)>b.length*.8)return[[a,null],[b,null]];
    return[[a,[i,a.length-j]],[b,[i,b.length-j]]]};
  const g=(a,b,s,cls,txt)=>`<div class="dl ${cls}"><span class="g">${a}</span><span class="g">${b}</span><span class="s">${s}</span><span class="t">${txt}</span></div>`;
  for(let k=0;k<lines.length;k++){const l=lines[k];
    if(l.startsWith('@@')){const m=/@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(l);o=m?+m[1]:0;n=m?+m[2]:0;rows.push(g('','','','h',esc(l.replace(/^(@@[^@]*@@)\s?/,'$1  '))));continue}
    if(l.startsWith('diff ')){const m=/ b\/(.+)$/.exec(l);if(m)lang=langOf(m[1]);if(fileHeaders){rows.push(`<div class="dfile">${ico('file','sm')}${esc(m?m[1]:l)}</div>`)}continue}
    if(l.startsWith('index ')||l.startsWith('+++')||l.startsWith('---')){continue}
    if(l.startsWith('new file')||l.startsWith('deleted file')||l.startsWith('similarity')||l.startsWith('rename')||l.startsWith('old mode')||l.startsWith('new mode')){meta.push(l);continue}
    if(l.startsWith('-')){let dels=[];while(k<lines.length&&lines[k].startsWith('-')&&!lines[k].startsWith('---'))dels.push(lines[k++].slice(1));let adds=[];while(k<lines.length&&lines[k].startsWith('+')&&!lines[k].startsWith('+++'))adds.push(lines[k++].slice(1));k--;
      const paired=dels.length===adds.length;const marked=[];
      for(let x=0;x<dels.length;x++){const[[da,dm],[aa,am]]=paired?pair(dels[x],adds[x]):[[dels[x],null],[adds[x]??'',null]];
        rows.push(g(o++,'','-','d',code(da,lang,dm)));if(paired)marked[x]=code(aa,lang,am)}
      for(let x=0;x<adds.length;x++)rows.push(g('',n++,'+','a',paired?marked[x]:code(adds[x],lang,null)));continue}
    if(l.startsWith('+')){rows.push(g('',n++,'+','a',code(l.slice(1),lang,null)));continue}
    if(l.startsWith('\\')){rows.push(g('','','','m',esc(l)));continue}
    if(l==='')continue;
    rows.push(g(o++,n++,'','',code(l.slice(1),lang,null)))}
  return{rows:rows.join(''),meta:meta.length?`<div class="dfile meta">${esc(meta.join(' · '))}</div>`:''}}

function moreLine(D,fn){return D.truncated?`<div class="center sm">Showing ${D.total_lines>2000?2000:D.total_lines} of ${D.total_lines} lines. <button class="txt" onclick="${fn}">Show all</button></div>`:''}

// One commit, rendered with the same diff engine. Secret files are stripped server-side.
async function showCommit(sha,all){
  const body=$('#pbody'),head=$('#stagehead');
  if(!all&&S.commitSha===sha&&body.dataset.sha===sha&&body.childElementCount)return;  // already showing it
  S.commitSha=sha;
  body.innerHTML='<div class="center">Loading commit…</div>';
  let C;try{C=await api(`${repoApi()}/commits/${E(sha)}${all?'?all=1':''}`)}
  catch(e){body.innerHTML=`<div class="center">${ico('warn','big')}Could not read that commit.<br><span class="mono sm">${esc(e.message)}</span></div>`;return}
  if(C.error){body.innerHTML=`<div class="center">${esc(C.error)}</div>`;return}
  const R=diffBody(C.diff,true);
  head.innerHTML=`<button class="ghost sm" onclick="backToChanges()">${ico('back','sm')}Back to changes</button>
    <span class="tagq">${esc(C.short)}</span><span class="faint">${C.files} file${C.files===1?'':'s'} changed</span><span class="sp"></span>
    <button class="sm" onclick="navigator.clipboard?.writeText('${esc(C.sha)}');toast('ok','Copied ${esc(C.short)}')">${ico('copy','sm')}Copy hash</button>`;
  const hidden=C.hidden?`<div class="hid">${ico('warn','sm')} ${C.hidden} secret file${C.hidden===1?'':'s'} in this commit — contents never shown.</div>`:'';
  body.innerHTML=`<div class="chero"><h2>${esc(C.subject)}</h2>
      ${C.body?`<pre class="body">${esc(C.body)}</pre>`:''}
      <div class="meta"><b>${esc(C.author)}</b><span class="sep">·</span><span>${esc(C.date)}</span><span class="sep">·</span>
        <span class="mono">${esc(C.sha.slice(0,12))}</span><span class="sep">·</span><span class="repotag ${repoClass(S.repo)}">${esc(shortOf(curRepo()||{repo:S.repo}))}</span></div>
      ${hidden}</div>
    ${R.meta}<div class="diff">${R.rows}</div>`+moreLine(C,`showCommit('${esc(sha)}',1)`);
  body.dataset.sha=sha;body.scrollTop=0;
}
async function showAll(){const rm=rmem();S.stageSig=null;S.diff=await api(`${repoApi()}/diff?file=${E(rm.file)}&staged=${rm.staged?1:0}&all=1`);renderDiff()}
async function pickFile(file,staged){const rm=rmem();rm.file=file;rm.staged=staged;rm.sha=null;nav(false);
  const f=S.data.files.find(x=>x.file===file);S.diff=null;renderFiles();renderStage(true);
  await loadDiff(JSON.stringify([S.lane,S.repo,file,staged,f?.add,f?.del,f?.add_staged,f?.del_staged,S.data.log[0]?.sha]))}
/* ---------- actions ---------- */
function setBusy(b){S.busy=b;$('#prog').classList.toggle('on',!!b);if(S.data)renderActbar();updateCommitBtn()}
async function stage(files,on){try{await post(`${repoApi()}/${on?'stage':'unstage'}`,{files});await refreshRepo()}catch(e){toast('err',e.message)}}
async function commit(){const msg=$('#msg').value;if(!msg.trim()||!S.data?.files.some(f=>f.staged))return;setBusy({id:'commit',label:'Committing…'});try{const j=await post(`${repoApi()}/commit`,{message:msg});$('#msg').value='';toast('ok','Committed '+j.output);}catch(e){toast('err','Commit failed\n'+(e.output||e.message))}setBusy(null);await refreshRepo()}
async function act(a){const st=S.data?.state||{};const label=a==='push'?'Pushing…':'Pulling…';setBusy({id:a==='push'&&!st.upstream?'publish':a,label});const t=toast('prog',a==='push'?`Pushing to origin/${st.branch}…`:'Pulling…');
  try{const j=await post(`${repoApi()}/${a}`);toast('ok',(j.output||'').split('\n').slice(-2).join('\n')||a+' done',{replace:t})}
  catch(e){const out=e.output||e.message;t.remove();if(a==='push'&&/rejected|fetch first|non-fast-forward/i.test(out))toast('err','Push rejected — the remote has work you do not have.\n\n'+out,{fix:{label:`Pull ${st.behind||''}`.trim(),run:()=>act('pull')}});else if(a==='pull')toast('err','Pull needs a merge — fast-forward only. Sort it out in the terminal.\n\n'+out);else toast('err',out)}
  setBusy(null);await refreshRepo()}
async function primary(){const na=S.data?.nextAction;if(!na)return;switch(na.id){case'pull':return act('pull');case'push':case'publish':return act('push');case'commit':$('#msg').focus();return;case'stage_all':return stage(S.data.files.filter(f=>f.unstaged).map(f=>f.file),true);case'create_pr':{try{const j=await post(`${repoApi()}/pr`);window.open(j.url,'_blank')}catch(e){toast('err',e.message)}return}case'open_pr':if(na.url)window.open(na.url,'_blank');return;case'finish':return finishDlg();case'resume':return laneRun({action:'resume',id:S.lane})}}
async function laneRun(b){const labels={start:'Starting…',resume:'Resuming…',park:'Parking…',done:'Finishing…'};setBusy({id:b.action,label:labels[b.action]});const t=toast('prog',labels[b.action]);
  try{const j=await post(`${laneApi(b.id)}/${b.action}`,{repos:b.repos,note:b.note});toast('ok',(j.output||'ok').split('\n').slice(-3).join('\n'),{replace:t});setBusy(null);S.board=await api('/api/board');if(b.action==='start'){S.boardSig=null;await openWs(b.id)}else if(b.action==='done'){S.lane=null;S.repo=null;renderHome();renderCrumb();goHome()}else{renderHome();renderCrumb();renderRepos();await loadRepo(false)}}
  catch(e){t.remove();toast('err',(b.action+' failed\n\n'+(e.output||e.message)));setBusy(null)}}
async function refReveal(name){try{const j=await post(`${laneApi()}/refs/${E(name)}/reveal`);toast('ok',j.output||'revealed')}catch(e){toast('err',e.message)}}
async function refRm(name){openDlg(dlgHead(`Detach reference ${esc(name)}?`,'','unlink','warn')+`<div class="infobox">${ico('info')}<span>Only the link under <span class="mono">lanes/${esc(S.lane)}/refs/</span> and the registry line are removed. The folder or file itself is not touched.</span></div>`,async()=>{const j=await post(`${laneApi()}/refs/${E(name)}/detach`);toast('ok',j.output);await refreshWs();if(!$('#sheetwrap').classList.contains('hidden'))renderSheet()});$('#dok').textContent='Detach'}
function refAddDlg(){const d=openDlg(dlgHead('Attach a reference',`To ${esc(S.lane)} — outside code or docs Claude may read`,'folder')
    +`<label>Path <span class="req">*</span></label><input id="rp" placeholder="~/Desktop/some-folder  or  ~/Downloads/spec.pdf" autocomplete="off">
    <div class="hint">${ico('info','sm')}<span>A folder or file outside the repos. It will appear as <span class="mono">lanes/${esc(S.lane)}/refs/&lt;name&gt;</span>.</span></div>
    <label>Note <span class="opt">(optional)</span></label><input id="rn" placeholder="why it matters for this work" autocomplete="off">
    <label class="chk"><input type="checkbox" id="rw"> Allow Claude to edit it (default is read-only)</label>`,
    async d=>{const j=await post(`${laneApi()}/refs/attach`,{path:d.querySelector('#rp').value.trim(),note:d.querySelector('#rn').value.trim(),rw:d.querySelector('#rw').checked});toast('ok',j.output.split('\n').filter(l=>l.startsWith('ref')).join('\n')||'attached');await refreshWs();if(!$('#sheetwrap').classList.contains('hidden'))renderSheet()},d=>d.querySelector('#rp').value.trim().length>0);d.querySelector('#dok').textContent='Attach';d.querySelector('#rp').focus()}
function discardDlg(list){
  if(!list.length)return;
  const d=S.data;const info=list.map(f=>d.files.find(x=>x.file===f)).filter(Boolean);
  const gone=info.filter(f=>f.untracked),edited=info.filter(f=>!f.untracked);
  openDlg(dlgHead(`Discard changes to ${list.length} file${list.length===1?'':'s'}?`,`In ${esc(S.repo)}`,'trash','bad')+`
    <div class="warnbox bad"><b>This cannot be undone.</b> Git keeps no copy of uncommitted work.
      <ul>${edited.length?`<li>${edited.length} file${edited.length===1?'':'s'} go back to the last commit</li>`:''}
         ${gone.length?`<li>${gone.length} new file${gone.length===1?'':'s'} are deleted from disk</li>`:''}</ul>
      <div class="mono sm">${info.slice(0,12).map(f=>esc(f.file)+(f.untracked?' (new)':'')).join('<br>')}
        ${info.length>12?`<br>…and ${info.length-12} more`:''}</div></div>`,
    async()=>{try{const j=await post(`${repoApi()}/discard`,{files:list});
      toast('ok',j.output||'discarded');const rm=rmem();if(rm&&list.includes(rm.file))rm.file=null;await refreshRepo()}
      catch(e){toast('err',e.output||e.message)}});
  const ok=$('#dlg').querySelector('#dok');ok.textContent='Discard';ok.className='danger';
}
// Amending is fine until the commit is shared; the server refuses it after that and says why.
function amendDlg(){
  const d=S.data;if(!d)return;const last=d.log&&d.log[0];if(!last){toast('err','Nothing to amend yet.');return}
  const staged=d.files.filter(f=>f.staged).length;
  const typed=$('#msg').value.trim();
  openDlg(dlgHead('Amend the last commit?',`<span class="mono">${esc(last.sha)}</span> on ${esc(d.state?.branch||S.repo)}`,'commit','warn')+`
    <div class="warnbox"><b>Rewrites</b> “${esc(last.subject)}”.
      <ul><li>${staged?`${staged} staged file${staged===1?'':'s'} join that commit`:'No staged files — only the message changes'}</li>
          <li>Refused if it is already pushed</li></ul></div>
    <label>Message</label><textarea id="am" rows="3">${esc(typed||last.subject)}</textarea>
    <div class="hint">Leave as is to keep the message.</div>`,
    async dd=>{try{const j=await post(`${repoApi()}/amend`,{message:dd.querySelector('#am').value});
      toast('ok',j.output||'amended');$('#msg').value='';await refreshRepo()}
      catch(e){toast('err',e.output||e.message)}});
  $('#dlg').querySelector('#dok').textContent='Amend';
}
/* ---------- dialogs ---------- */
function openDlg(html,onOk,validate){const d=$('#dlg');S.dialog=true;
  d.innerHTML=`<div class="dbody">${html}</div><div class="row"><span class="keys"><kbd>&crarr;</kbd> to confirm <kbd>esc</kbd> to cancel</span><button type="button" id="dcancel">Cancel</button><button type="button" class="pri" id="dok">OK</button></div>`;d.showModal();const ok=d.querySelector('#dok');d.querySelector('#dcancel').onclick=()=>d.close();
  const check=()=>{ok.disabled=validate?!validate(d):false};d.oninput=check;check();ok.onclick=async()=>{if(ok.disabled)return;d.close();try{await onOk(d)}catch(e){toast('err',e.message)}};d.onclose=()=>{S.dialog=false};d.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&e.target.tagName!=='TEXTAREA'){e.preventDefault();ok.click()}};return d}
function startDlg(){const repos=S.board?.repos||[];
  const d=openDlg(dlgHead('Start a lane','One piece of work across the repos it needs','branch')
    +`<label>Lane id <span class="req">*</span><span class="opt">slug</span></label><div class="field"><span class="pre">#</span><input id="i" placeholder="ABC-123-short-name" autocomplete="off" spellcheck="false"></div>
    <div class="hint" id="ih">${ico('info','sm')}<span>A ticket key or short slug, e.g. <span class="mono acc">ABC-123</span></span></div>
    <label>Repos <span class="req">*</span><span class="opt" id="rsel"></span></label>
    <div class="chips">${repos.map(r=>`<span class="chip" data-r="${esc(r)}">${ico('check','sm')}${esc(r)}</span>`).join('')||'<span class="faint">No repos registered yet — lane add one first.</span>'}</div>
    <input id="r" class="specin" placeholder="api@develop web:my-branch" autocomplete="off" spellcheck="false">
    <div class="hint">${ico('info','sm')}<span><span class="mono">name[:branch][@base]</span>, space separated. Click a repo to add or remove it.</span></div>
    <div class="infobox">${ico('term')}<span>Creates a worktree per repo under <span class="mono">lanes/&lt;id&gt;/</span>, on a new branch from its default branch unless you name a base.</span></div>`,
    d=>laneRun({action:'start',id:d.querySelector('#i').value.trim(),repos:d.querySelector('#r').value.trim()}),
    d=>{const id=d.querySelector('#i').value.trim();const okId=/^[A-Za-z0-9._-]+$/.test(id);
      d.querySelector('#ih span').innerHTML=id&&!okId?'<span class="bad">Letters, numbers, dot, dash, underscore.</span>':'A ticket key or short slug, e.g. <span class="mono acc">ABC-123</span>';
      const names=d.querySelector('#r').value.trim().split(/\s+/).filter(Boolean).map(s=>s.split(/[:@]/)[0]);
      d.querySelectorAll('.chip[data-r]').forEach(c=>c.classList.toggle('on',names.includes(c.dataset.r)));
      d.querySelector('#rsel').textContent=names.length?`${names.length} selected`:'';
      return okId&&names.length>0});
  d.querySelector('#dok').innerHTML=`Start lane ${ico('arrow','sm')}`;
  d.querySelectorAll('.chip[data-r]').forEach(c=>c.onclick=()=>{const r=d.querySelector('#r');
    const parts=r.value.trim().split(/\s+/).filter(Boolean);const has=parts.findIndex(s=>s.split(/[:@]/)[0]===c.dataset.r);
    if(has>=0)parts.splice(has,1);else parts.push(c.dataset.r);r.value=parts.join(' ');d.oninput()});
  d.querySelector('#i').focus()}
function parkDlg(){const w=cur();if(!w)return;const dirty=w.repos.filter(r=>r.exists&&(r.unstaged||r.staged));const unp=w.repos.filter(r=>r.exists&&r.ahead);
  const warn=`<div class="warnbox"><b>What parking does</b><ul>${dirty.length?dirty.map(r=>`<li>${esc(shortOf(r))}: ${(r.unstaged||0)+(r.staged||0)} uncommitted file(s) will be committed as <span class="mono">wip: park ${esc(w.id)}</span> on <span class="mono">${esc(r.branch)}</span></li>`).join(''):'<li>No uncommitted work — nothing will be committed.</li>'}${unp.length?`<li>${esc(unp.map(shortOf).join(', '))}: unpushed commits stay local until you push.</li>`:''}<li>Worktrees stay on disk. The lane leaves the active list; Resume brings it back.</li></ul></div>`;
  const d=openDlg(dlgHead(`Park ${esc(w.id)}`,'Put this lane down with a note for the next time you pick it up','park')+`${warn}<label>Resume note <span class="req">*</span></label><textarea id="n" rows="4" placeholder="where things stand, next step, blockers"></textarea><div class="hint">${ico('info','sm')}<span>Required, at least 10 characters — you will read it in a week.</span></div>`,
    d=>laneRun({action:'park',id:w.id,note:d.querySelector('#n').value.trim()}),d=>d.querySelector('#n').value.trim().length>=10);d.querySelector('#dok').textContent='Park lane';d.querySelector('#n').focus()}
function finishDlg(){const w=cur();if(!w)return;const bad=w.repos.filter(r=>r.exists&&(r.unstaged||r.staged||r.ahead));
  const rows=w.repos.map(r=>{const ok=!r.exists||!(r.unstaged||r.staged||r.ahead);
    return`<div class="ck ${ok?'ok':'bad'}">${ico(ok?'check':'warn','sm')}<span class="repotag ${repoClass(r.repo)}">${esc(shortOf(r))}</span><span class="mono faint">${esc(r.branch||'')}</span>
      <span class="why">${!r.exists?'no worktree':ok?'clean, pushed':`${(r.unstaged||0)+(r.staged||0)} uncommitted, ${r.ahead||0} unpushed`}</span></div>`}).join('');
  const d=openDlg(dlgHead(`Finish ${esc(w.id)}?`,bad.length?'Not yet — something would be lost':'Everything is committed and pushed',bad.length?'warn':'flag',bad.length?'bad':'')
    +`<div class="warnbox ${bad.length?'bad':''}"><b>This removes the worktrees</b> under <span class="mono">lanes/${esc(w.id)}/</span> and archives the lane file. Branches and commits stay in git. ${bad.length?'Refused right now:':'Nothing uncommitted or unpushed was found.'}</div>
    <div class="checks">${rows}</div>${bad.length?`<div class="hint bad">${ico('warn','sm')}<span>Commit and push ${esc(bad.map(shortOf).join(', '))} first.</span></div>`:''}`,
    ()=>laneRun({action:'done',id:w.id}),()=>bad.length===0);const ok=d.querySelector('#dok');ok.textContent='Finish lane';ok.className='danger'}
/* ---------- events ---------- */
/* ---------- screens ---------- */
function setView(v){S.view=v;rememberPlace();nav(true);
  $('#home').classList.toggle('hidden',v!=='home');
  $('#work').classList.toggle('hidden',v!=='work');
  $('#memory').classList.toggle('hidden',v!=='memory');
  if(v!=='work')closeSheet();
  renderCrumb();
  if(v==='home'){renderHome();loadHomeExtras()}else if(v==='memory')loadMemory();}
function goHome(){S.view='home';setView('home');$('#home').focus()}

/* how long since this worktree last moved */
/* Relative time, one unit, largest that still reads true: 5 min, 3 hours, 2 days, 3 weeks.
   A lane touched an hour ago and one touched this morning are different situations;
   "touched today" flattened both. Takes epoch seconds; returns '' for nothing. */
function ago(ts){
  if(!ts)return'';
  const s=Math.max(0,Math.floor(Date.now()/1000-ts));
  if(s<45)return'just now';
  if(s<3600)return `${Math.floor(s/60)} min ago`;
  if(s<86400){const n=Math.floor(s/3600);return `${n} hour${n===1?'':'s'} ago`}
  if(s<604800){const n=Math.floor(s/86400);return `${n} day${n===1?'':'s'} ago`}
  if(s<2629800){const n=Math.round(s/604800);return `${n} week${n===1?'':'s'} ago`}
  if(s<31557600){const n=Math.round(s/2629800);return `${n} month${n===1?'':'s'} ago`}
  const n=Math.round(s/31557600);return `${n} year${n===1?'':'s'} ago`;
}
/* the lane file records a date, not a timestamp: read it as local midnight */
function agoDate(d){
  if(!d)return'';
  const t=Date.parse(d+'T00:00:00');
  return isNaN(t)?'':ago(t/1000);
}
const exact=ts=>ts?new Date(ts*1000).toLocaleString(undefined,
  {weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
const sinceCommit=ago;
const laneTouched=w=>Math.max(0,...w.repos.map(r=>r.last||0));
const changed=r=>(r.unstaged||0)+(r.staged||0);
const laneChanged=w=>w.repos.reduce((n,r)=>n+changed(r),0);
const laneAhead=w=>w.repos.reduce((n,r)=>n+(r.ahead||0),0);
const laneDrift=w=>Math.max(0,...w.repos.map(r=>r.base_behind||0));

/* a repo's state as chips: every true thing about it, loudest first */
function repoChips(r){
  if(!r.exists)return[`<span class="chip" title="no worktree on disk">no worktree</span>`];
  const out=[],ch=changed(r);
  if(r.pr_failing)out.push(`<span class="chip bad" title="the open PR has failing checks">${ico('warn','sm')}PR checks failing</span>`);
  if(ch)out.push(`<span class="chip att" title="${ch} uncommitted file(s)"><span class="dotc"></span>${ch} uncommitted</span>`);
  if(r.behind)out.push(`<span class="chip att" title="origin has ${r.behind} commit(s) this branch does not">${ico('pull','sm')}${r.behind} to pull</span>`);
  if(r.ahead)out.push(`<span class="chip acc" title="${r.ahead} commit(s) no origin branch has">${ico('push','sm')}${r.ahead} to push</span>`);
  if(r.base_behind>2)out.push(`<span class="chip drift" title="${r.base_behind} commit(s) behind ${esc(r.base_branch||'its base')}${r.base_from_pr?' — the branch its PR merges into':''}. Not a failure; it just gets harder to merge the longer it sits.">${ico('pull','sm')}${r.base_behind} behind ${esc(r.base_branch||'base')}</span>`);
  if(!out.length)out.push(`<span class="chip ok" title="clean and in sync">${ico('check','sm')}clean and in sync</span>`);
  return out;
}
const laneTone=w=>w.repos.some(r=>r.pr_failing)?'bad':laneChanged(w)?'att':laneAhead(w)?'acc':'';
/* One next action per lane card: the first repo that needs something, and what. It opens the
   lane on that repo, where the real button is — the card never commits or pushes by itself. */
function laneNext(w){
  if(w.status!=='active')return{label:'Resume lane',icon:'play',run:{action:'resume'}};
  const ex=w.repos.filter(r=>r.exists);
  const pick=(f)=>ex.find(f);
  let r;
  if((r=pick(x=>x.pr_failing)))return{label:`Fix checks in ${shortOf(r)}`,icon:'warn',tone:'bad',repo:r.repo};
  if((r=[...ex].filter(x=>changed(x)).sort((a,b)=>changed(b)-changed(a))[0]))return{label:`Review ${plural(changed(r),'change')} in ${shortOf(r)}`,icon:'diff',repo:r.repo};
  if((r=pick(x=>x.behind)))return{label:`Pull ${r.behind} in ${shortOf(r)}`,icon:'pull',repo:r.repo};
  if((r=pick(x=>x.ahead)))return{label:`Push ${r.ahead} in ${shortOf(r)}`,icon:'push',repo:r.repo};
  if(ex.length&&ex.every(x=>x.pr_state==='MERGED'))return{label:'Finish lane',icon:'flag',finish:true};
  if((r=pick(x=>x.base_behind>2)))return{label:`Catch ${shortOf(r)} up with ${r.base_branch||'its base'}`,icon:'pull',repo:r.repo};
  return{label:'Open lane',icon:'arrow',repo:null};
}
function runNext(id){const w=S.board?.lanes.find(x=>x.id===id);if(!w)return;const n=laneNext(w);
  if(n.run)return laneRun({...n.run,id});
  if(n.finish){S.lane=id;return finishDlg()}
  return openWs(id,n.repo||undefined)}

/* ---------- home: a reading of the situation, not a list ---------- */
function todoList(b){
  const out=[],act=b.lanes.filter(w=>w.status==='active');
  const drift=act.map(w=>{const r=w.repos.filter(x=>x.exists).sort((a,c)=>(c.base_behind||0)-(a.base_behind||0))[0];return[w,r]})
                 .filter(([,r])=>r&&r.base_behind>2).sort((a,c)=>(c[1].base_behind)-(a[1].base_behind))[0];
  if(drift){const[w,r]=drift;const ch=changed(r);
    out.push({tone:'drift',ic:'pull',html:`<b>${esc(shortOf(r))}</b> in <b>${esc(w.id)}</b> is ${r.base_behind} behind <b>${esc(r.base_branch||'its base')}</b>${r.base_from_pr?', the branch its PR merges into':''}${ch?`, while ${plural(ch,'file')} sit open on it`:''}. The longer that sits, the worse the merge.`,
      act:'Open it',go:[w.id,r.repo]});}
  const dirty=act.filter(w=>laneChanged(w));
  if(dirty.length){const total=dirty.reduce((n,w)=>n+laneChanged(w),0);const w=dirty.sort((a,c)=>laneChanged(c)-laneChanged(a))[0];
    const r=w.repos.filter(x=>changed(x)).sort((a,c)=>changed(c)-changed(a))[0];
    out.push({tone:'',ic:'diff',html:`${plural(total,'file')} changed across ${plural(dirty.length,'lane')}, none committed yet.`,
      act:`Review ${esc(shortOf(r))} in ${esc(w.id)}`,go:[w.id,r.repo]});}
  const push=act.filter(w=>laneAhead(w)&&!laneChanged(w));
  if(push.length){const n=push.reduce((x,w)=>x+laneAhead(w),0);
    out.push({tone:'calm',ic:'push',html:`${push.length===1?'One lane is':plural(push.length,'lane')+' are'} ahead of origin with nothing uncommitted — safe to push.`,
      act:`Open ${esc(push[0].id)}`,go:[push[0].id,push[0].repos.find(r=>r.ahead)?.repo]});}
  if(!out.length)out.push({tone:'calm',ic:'check',html:'Everything is committed, pushed and passing. Nothing wants a decision.',act:'',go:null});
  return out;
}
/* The ticket field is hand-written and comes in three shapes: a bare Jira URL,
   "ABC-123  https://...", or empty. Pull out whichever of key and url are there;
   build the url from the key when only the key was written. */
// Where ticket keys link to comes from registry/config.yml, not from this file.
const trackerTemplate=()=>String(S.board?.tracker||'');
function ticketOf(w){
  const raw=String(w?.ticket||'').trim();
  const url=(raw.match(/https?:\/\/\S+/)||[])[0]||'';
  const key=(raw.match(/\b([A-Z][A-Z0-9]+-\d+)\b/)||[])[1]
        ||(url.match(/\/browse\/([A-Z][A-Z0-9]+-\d+)/)||[])[1]
        ||(/^([A-Z][A-Z0-9]+-\d+)-/.exec(w?.id||'')||[])[1]||'';
  if(!key&&!url)return null;
  const tpl=trackerTemplate();
  const built=key&&tpl?(tpl.includes('{key}')?tpl.replace(/\{key\}/g,key):tpl.replace(/\/?$/,'/')+key):'';
  return {key:key||'ticket', url:url||built};
}
function ticketChip(w,cls='tk'){
  const t=ticketOf(w);if(!t)return'';
  if(!t.url)return `<span class="${cls} ticket">${esc(t.key)}</span>`;
  return `<a class="${cls} ticket link" href="${esc(t.url)}" target="_blank" rel="noopener"
    title="Open ${esc(t.key)} in Jira" onclick="event.stopPropagation()">${esc(t.key)}${ico('ext','sm')}</a>`;
}
function laneTitle(w){const[n]=prettyName(w.id,w.ticket);return n||w.id}
/* Home, after the Stitch "Dense list rows" screen: every active lane is one block in a single list.
   Header (ticket, title, status, age; the next action and About on the right), one Goal / Resume line,
   then one aligned row per repo with its full-word chips and when it last moved. */
const aboutBtn=w=>`<button class="sm ghost-b" data-about="${esc(w.id)}" title="About this lane — lanes/${esc(w.id)} (i)">${ico('info','sm')}About this lane</button>`;
function repoLine(w,r){
  const when=r.exists&&r.last?ago(r.last):'';
  return`<a class="rl2" href="${esc(href(`/lanes/${E(w.id)}/${E(r.repo)}`))}" title="Open ${esc(r.repo)} in this lane">
    ${ico('folder','sm')}<span class="rnm">${esc(r.repo)}</span><span class="branch">${esc(r.branch||'')}</span>
    <span class="sp"></span>${repoChips(r).join('')}${when?`<span class="age" title="${esc(exact(r.last))}">${esc(when)}</span>`:''}</a>`;
}
function homeCard(w){
  const ch=laneChanged(w),drift=laneDrift(w),fail=w.repos.some(r=>r.pr_failing);
  const tone=fail?'fail':(ch||drift>2)?'now':laneAhead(w)?'calm':'';
  const goal=plain(realText(w.goal)),note=plain(realText(w.note)),n=laneNext(w);
  const full=`Goal: ${goal||'none written yet'}${note?` — Resume: ${note}`:''}`;
  return`<div class="lblock ${tone}" data-open="${esc(w.id)}" tabindex="0">
    <div class="lh">${ticketChip(w)}<a class="ttl" href="${esc(href('/lanes/'+E(w.id)))}" title="${esc(w.id)}">${esc(laneTitle(w))}</a><span class="tk state active">active</span>
      <span class="dot">·</span><span class="when" title="${esc(exact(laneTouched(w))||w.updated)}">${esc(ago(laneTouched(w))||agoDate(w.updated))}</span>
      <span class="sp"></span><button class="pri sm ${n.tone||''}" data-next="${esc(w.id)}">${ico(n.icon,'sm')}${esc(n.label)}</button>${aboutBtn(w)}</div>
    <div class="lg" title="${esc(full)}"><b>Goal:</b><span class="g">${goal?esc(goal):'none written yet'}</span>${note?`<span class="dash">—</span><i>Resume: ${esc(note)}</i>`:''}</div>
    <div class="rlist">${w.repos.map(r=>repoLine(w,r)).join('')}</div></div>`;
}
function parkedCard(w){
  const m=/^(\d{4}-\d{2}-\d{2})\s+—\s+([\s\S]*)$/.exec(plain(w.note||'').trim()||'');
  const nd=m?m[1]:w.updated,nt=m?m[2]:plain(realText(w.note));
  const when=nd?new Date(nd+'T00:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric'}):'';
  return`<div class="prow2" data-open="${esc(w.id)}" tabindex="0" title="${esc(w.id)}${nt?' — Resume on: '+esc(nt):''}">
    ${ico('park','sm')}${ticketChip(w)}<a class="ttl" href="${esc(href('/lanes/'+E(w.id)))}">${esc(laneTitle(w))}</a>
    <span class="rs"><b>Resume on:</b> ${nt?esc(nt):'no note'}</span>
    <span class="when" title="parked; lane file updated ${esc(w.updated||'')}">${esc(when)}</span>
    <button class="sm" data-next="${esc(w.id)}">${ico('play','sm')}Resume</button></div>`;
}
const parkedOpen=()=>LSg('lane-parked-collapsed','0')!=='1';
function toggleParked(){LSs('lane-parked-collapsed',parkedOpen()?'1':'0');renderHome()}
/* Home's right column reads two things the board did not show before: drafts waiting for a
   scope (/api/memory) and recent conversations (/api/sessions). Both are fetched lazily. */
async function loadHomeExtras(force){
  const now=Date.now();if(!force&&S.extrasAt&&now-S.extrasAt<20000)return;S.extrasAt=now;
  try{S.mem=await api('/api/memory')}catch{}
  try{S.sessAll=(await api('/api/sessions')).sessions||{}}catch{S.sessAll=S.sessAll||{}}
  renderRail();if(S.view==='home')renderHome();
}
const draftsOf=()=>(S.mem?.scopes||[]).find(s=>s.id==='drafts')?.files||[];
function recentSessions(n){
  const rows=[];for(const[repo,txt]of Object.entries(S.sessAll||{}))for(const s of parseSessions(txt))rows.push({...s,repo});
  const seen=new Set();return rows.sort((a,b)=>b.when.localeCompare(a.when)).filter(s=>!seen.has(s.id)&&seen.add(s.id)).slice(0,n);
}
function renderHome(){
  const b=S.board,el=$('#home');
  if(!b||!b.lanes){el.innerHTML='<div class="hmain"><div class="center">Loading…</div></div>';return}
  const act=b.lanes.filter(w=>w.status==='active'),park=b.lanes.filter(w=>w.status!=='active');
  const wants=act.filter(w=>laneChanged(w)||laneDrift(w)>2||w.repos.some(r=>r.pr_failing));
  const ordered=[...wants,...act.filter(w=>!wants.includes(w))];
  const todos=todoList(b);
  const tally=[['active',act.length],['parked',park.length],
    ['files changed',act.reduce((n,w)=>n+laneChanged(w),0)],['commits to push',act.reduce((n,w)=>n+laneAhead(w),0)],
    ['behind base',Math.max(0,...act.map(laneDrift))],['checks failing',act.reduce((n,w)=>n+w.repos.filter(r=>r.pr_failing).length,0)]];
  const drafts=draftsOf(),sessAll=recentSessions(50),sess=sessAll.slice(0,6),open=parkedOpen();
  el.innerHTML=`<div class="hmain">
    <div class="hhead"><h1>Active Lanes</h1><span class="count">${act.length} active</span><span class="sub">needing a decision first, then by name</span></div>
    ${ordered.length?`<div class="llist">${ordered.map(homeCard).join('')}</div>`:''}
    ${!act.length&&b.lanes.length?'<div class="nolanes"><h3>Nothing in flight</h3><p>Every lane is parked. Resume one below, or start something new.</p><button class="pri" onclick="startDlg()">'+ico('plus','sm')+'Start a lane</button></div>':''}
    ${!b.lanes.length?`<div class="nolanes"><h3>No lanes yet</h3><p>A lane is one piece of work across the repos it needs: a branch and a worktree in each.</p><button class="pri" onclick="startDlg()">${ico('plus','sm')}Start a lane</button></div>`:''}
    ${park.length?`<div class="pbox" id="parkedHead">
      <button class="phead" onclick="toggleParked()" aria-expanded="${open}"><span class="chev ${open?'open':''}">${ico('arrow','sm')}</span>Parked Lanes<span class="count">${park.length} parked</span>
        <span class="sp"></span><span class="sub">worktrees kept on disk; Resume brings a lane back</span></button>
      ${open?park.map(parkedCard).join(''):''}</div>`:''}
  </div>
  <aside class="hside">
    <section class="rsec"><h4>${ico('flag','sm')}What to do about it</h4>
      <div class="todo">${todos.map((t,i)=>`<div class="ti ${t.tone}">${ico(t.ic,'sm')}<span class="tx">${t.html}
        ${t.act?` <button class="link do" data-todo="${i}">${t.act} →</button>`:''}</span></div>`).join('')}</div></section>
    <section class="rsec"><h4>${ico('book','sm')}Context memory</h4>
      <div class="mbox ${drafts.length?'hot':''}"><div class="mt">${drafts.length?`<span class="dotc"></span>${plural(drafts.length,'draft')} waiting`:'No drafts waiting'}</div>
        <div class="msub">${drafts.length?'Things Claude learned, waiting for you to pick how long they stay true.':'Claude drafts a memory when it learns something; you pick where it goes.'}</div>
        ${drafts.slice(0,4).map(f=>`<div class="d1"><div class="dn" title="${esc(f.description||f.name||f.file)}"><button class="link" data-mopen="${esc(f.file)}">${esc(f.name||f.file)}</button><span>${esc(daysAgo(f.modified))}</span></div>
          <div class="da"><button class="pri sm" data-mfileit="${esc(f.file)}">${ico('inbox','sm')}File it</button><button class="sm" data-mdrop="${esc(f.file)}">Discard</button></div></div>`).join('')}
        ${drafts.length>4?`<button class="link" data-rail="memory">${drafts.length-4} more in Memory →</button>`:''}</div></section>
    <section class="rsec"><h4>${ico('term','sm')}Recent sessions${sessAll.length?`<span class="hx">history (${sessAll.length})</span>`:''}</h4>
      ${sess.map(s=>`<button class="s1" data-resume="${esc(s.id)}" title="Click to copy: claude --resume ${esc(s.id)}">
        <span class="st">${esc(s.first)}</span><span class="sw">${esc(s.when.slice(5))}</span>
        <span class="sr"><span class="repotag ${repoClass(s.repo)}">${esc(s.repo)}</span> ${s.turns} turns · ${esc(s.id.slice(0,8))}</span></button>`).join('')
        ||'<div class="pempty">None recorded yet.</div>'}</section>
    <section class="rsec"><h4>${ico('lanes','sm')}At a glance</h4>
      <div class="tally">${tally.map(([l,n])=>`<div class="tl">${l}<span class="n">${n}</span></div>`).join('')}</div></section>
  </aside>`;
  el.querySelectorAll('[data-todo]').forEach(btn=>{const t=todos[+btn.dataset.todo];
    btn.onclick=e=>{e.stopPropagation();if(t.go)openWs(t.go[0],t.go[1])}});
  renderRail();
}

/* ---------- the rail: the board's places, then the lanes in flight ---------- */
function renderRail(){
  $('#railActive').setAttribute('href',href('/'));$('#memBtn').setAttribute('href',href('/memory'));$('#homeBtn').setAttribute('href',href('/'));
  const b=S.board;if(!b)return;
  const act=b.lanes.filter(w=>w.status==='active'),park=b.lanes.filter(w=>w.status!=='active');
  $('#nActive').textContent=act.length||'';$('#nParked').textContent=park.length||'';
  const nd=draftsOf().length,dn=$('#nDrafts');dn.textContent=nd?`${nd} draft${nd===1?'':'s'}`:'';dn.classList.toggle('hot',nd>0);
  $('#railActive').classList.toggle('on',S.view==='home');
  $('#memBtn').classList.toggle('on',S.view==='memory');
  $('#raillanes').innerHTML=act.map(w=>{const tone=laneTone(w),ch=laneChanged(w);
    return`<a class="rl ${S.view==='work'&&S.lane===w.id?'on':''}" href="${esc(href('/lanes/'+E(w.id)))}" title="${esc(w.id)}">
      <span class="dot ${tone}"></span><span class="nm">${esc(laneTitle(w))}</span>${ch?`<span class="c">${ch}</span>`:''}</a>`}).join('')
    ||'<div class="none">No active lanes.</div>';
}

/* ---------- command bar ---------- */
function renderCrumb(){
  const w=cur();
  const c=$('#crumb');
  if(S.view==='home'){c.innerHTML=S.board?`<b>Home</b><span class="sep">·</span><span>${S.board.lanes.filter(x=>x.status==='active').length} active, ${S.board.lanes.filter(x=>x.status!=='active').length} parked</span>`:'<b>Home</b>';}
  else if(S.view==='memory'){const sc=mscope();c.innerHTML='<b>Memory</b><span class="sep">/</span><span>'+esc((sc?.label||S.mscope).replace(/^repo:/,''))+'</span>';}
  else if(w){const r=curRepo();c.innerHTML=`<span>Lanes</span><span class="sep">/</span><b class="link" title="About this lane (i)">${esc(w.id)}</b>${r?`<span class="sep">/</span><b>${esc(shortOf(r))}</b>`:''}`;}
  else c.innerHTML='';
  let chips='';
  if(S.view==='work'&&w){
    const ch=laneChanged(w),ah=laneAhead(w),fail=w.repos.filter(r=>r.pr_failing).length;
    if(ch)chips+=`<span class="chip att"><span class="dotc"></span>${ch} uncommitted</span>`;
    if(ah)chips+=`<span class="chip acc">${ico('push','sm')}${ah} to push</span>`;
    if(fail)chips+=`<span class="chip bad">${ico('warn','sm')}${fail} failing</span>`;
    const dr=w.repos.filter(r=>r.base_behind>2).sort((a,b)=>b.base_behind-a.base_behind)[0];
    if(dr)chips+=`<span class="chip drift" title="behind ${esc(dr.base_branch||'base')} — drift, not a failure">${ico('pull','sm')}${dr.base_behind} behind ${esc(dr.base_branch||'')}</span>`;
    if(!ch&&!ah&&!fail)chips+=`<span class="chip ok">${ico('check','sm')}clean</span>`;
  }else if(S.board){
    const a=S.board.lanes.filter(x=>x.status==='active');
    const ch=a.reduce((n,x)=>n+laneChanged(x),0),ah=a.reduce((n,x)=>n+laneAhead(x),0);
    if(ch)chips+=`<span class="chip att"><span class="dotc"></span>${ch} uncommitted</span>`;
    if(ah)chips+=`<span class="chip acc">${ico('push','sm')}${ah} to push</span>`;
  }
  $('#chips').innerHTML=chips;
  let act='';
  if(S.view==='work'&&w){
    if(w.status!=='active')act=`<button class="pri" onclick="laneRun({action:'resume',id:'${esc(w.id)}'})">${ico('play','sm')}Resume</button>`;
    else{const allDone=w.repos.every(r=>r.exists&&!r.unstaged&&!r.staged&&!r.ahead&&(r.pr_state==='MERGED'||r.pr_state==null));
      act=`<button onclick="parkDlg()" title="Write a resume note and put this lane down">${ico('park','sm')}Park</button>`
        +(allDone?`<button class="pri" onclick="finishDlg()">${ico('flag','sm')}Finish</button>`:'');}
    const fnd=((w.findings||'').match(/^- /gm)||[]).length;
    $('#lanetitle').innerHTML=`<a class="up" href="${esc(href('/'))}" title="Home">Lanes</a><span class="sep">/</span>
      <h1 title="${esc(w.id)}">${esc(laneTitle(w))}</h1><span class="lid">${esc(w.id)}</span>${ticketChip(w)}<span class="tk state ${esc(w.status)}">${esc(w.status)}</span>`;
    $('#goalstrip').innerHTML=`<div class="gi g">${ico('target','sm')}<b>Goal</b><span>${esc(firstSentence(w.goal,180)||'none written yet')}</span></div>
      <div class="gi r">${ico('note','sm')}<b>Resume</b><span>${esc(firstSentence(w.note,160)||'no note')}</span></div>
      <div class="gi f">${ico('bulb','sm')}<b>Findings</b><span>${fnd?plural(fnd,'finding'):'none yet'}</span></div>`;
  }
  $('#cmdact').innerHTML=act;
  $('#aboutBtn').classList.toggle('hidden',!(S.view==='work'&&w));
  $('#memBtn').title=S.view==='memory'?'Back to your work (m)':'Memory: preferences, facts, per-repo notes (m)';
  renderRail();
}

/* ---------- work: repos, files, diff, one action bar ---------- */
function repoTab(r,i){
  const s=esc(shortOf(r));
  const dot=!r.exists?'none':r.pr_failing?'bad':changed(r)?'att':r.ahead?'acc':'';
  const chips=repoChips(r);
  return`<button class="r ${r.repo===S.repo?'sel':''} ${r.exists?'':'nowt'} ${repoClass(r.repo)}" data-repo="${esc(r.repo)}"
    title="${esc(r.repo)} · branch ${esc(r.branch)}${r.base?' from '+esc(r.base):''} · press ${i+1}">
    <span class="rname">${ico('repo','sm')}<span class="repotag ${repoClass(r.repo)}">${s}</span>${s!==esc(r.repo)?`<span class="full faint">${esc(r.repo)}</span>`:''}</span>
    <span class="rdot ${dot}"></span>
    <span class="rbr"><span class="branch">${ico('branch','sm')}${esc(r.branch||'')}</span></span>
    <span class="rst">${chips.slice(0,2).join('')}</span></button>`;
}
function renderRepos(){
  const w=cur();if(!w){$('#repos').innerHTML='';$('#repometa').innerHTML='';return}
  const d=S.data,st=d?.state,pr=d?.pr;
  $('#nrepos').textContent=`(${w.repos.length})`;
  $('#repos').innerHTML=w.repos.map(repoTab).join('');
  let meta='';
  if(st)meta=`<span class="branch" title="${esc(st.branch)}">${ico('branch','sm')}${esc(st.branch)}</span>${st.upstream?`<span class="up2" title="tracks ${esc(st.upstream)}">→ ${esc(st.upstream)}</span>`:'<span class="chip att">not published</span>'}
    ${pr&&!pr.error?`<a class="chip ${pr.state==='MERGED'?'ok':pr.checks?.failing?'bad':pr.isDraft?'':'ok'}" href="${esc(pr.url)}" target="_blank" rel="noopener">${ico('pr','sm')} #${pr.number} ${pr.state==='MERGED'?'merged':pr.checks?.failing?pr.checks.failing+' failing':pr.checks?.pending?'running':pr.isDraft?'draft':'passing'}</a>`:''}`;
  $('#repometa').innerHTML=meta;
}
function renderRepo(){
  const w=cur(),r=curRepo();if(!w){goHome();return}
  renderRepos();renderCrumb();
  if(!r||!r.exists){
    $('#files').innerHTML=`<div class="empty big">${w.status!=='active'?'Worktrees are removed while parked.':'No worktree for this repo yet.'}</div>`;
    $('#commit').classList.add('hidden');$('#stagehead').innerHTML='';
    $('#pbody').innerHTML=`<div class="center">${ico('repo','big')}No worktree here.<br><br><button class="pri" onclick="openSheet()">About this lane</button></div>`;
    renderActbar();return}
  $('#commit').classList.remove('hidden');
  $('#commitTo').textContent=S.data?.state?.branch||r.branch||'';
  renderFiles();renderStage();renderActbar();updateCommitBtn();
}
/* the action bar says what happens next in words, then offers it */
function renderActbar(){
  const d=S.data,w=cur();
  if(!d){$('#actwhy').innerHTML='';$('#actbtns').innerHTML=w&&w.status!=='active'?`<button class="pri" onclick="laneRun({action:'resume',id:'${esc(w.id)}'})">${ico('play','sm')}Resume this lane</button>`:'';return}
  const st=d.state,na=d.nextAction||{id:'none',label:'Nothing to do'};
  const staged=d.files.filter(f=>f.staged).length,unst=d.files.filter(f=>f.unstaged).length;
  const r=curRepo();
  let why='';
  if(staged&&unst)why=`<b>${plural(staged,'file')}</b> staged, ${unst} still open — commit what is ready, or press <b>a</b> to stage the rest.`;
  else if(staged)why=`<b>${plural(staged,'file')}</b> staged and nothing left open. Write a message and commit.`;
  else if(unst)why=`<b>${plural(unst,'file')}</b> changed, none staged yet — tick the ones that belong together, or press <b>a</b> for all.`;
  else if(st.ahead)why=`Working tree clean. <b>${plural(st.ahead,'commit')}</b> waiting to go to ${esc(st.upstream||'origin')}.`;
  else if(st.behind)why=`Working tree clean. <b>${plural(st.behind,'commit')}</b> to pull.`;
  else if(r&&r.base_behind>2)why=`Clean and in sync, but <b>${r.base_behind} behind ${esc(r.base_branch||'master')}</b> — worth pulling that in before you carry on.`;
  else why='Clean, in sync, nothing to do here.';
  $('#actwhy').innerHTML=why;
  const busy=S.busy;const primLabel=busy&&busy.id===na.id?busy.label:na.label;
  const btns=[];
  if(st.upstream&&st.behind&&na.id!=='pull')btns.push(`<button onclick="act('pull')" ${busy?'disabled':''}>${ico('pull','sm')}Pull ${st.behind}</button>`);
  // with files staged the commit box below the list is the primary action; everything else lands here
  if(!staged){const pi={pull:'pull',push:'push',publish:'push',commit:'commit',stage_all:'diff',create_pr:'pr',open_pr:'pr',finish:'flag',resume:'play'}[na.id];
    btns.push(`<button class="pri ${na.tone||''}" id="primary" onclick="primary()" title="⌘P" ${na.id==='none'||busy?'disabled':''}>${pi?ico(pi,'sm'):''}${esc(primLabel)}</button>`);}
  $('#actbtns').innerHTML=btns.join('');
  updateCommitBtn();
}

function backToChanges(){const rm=rmem();if(rm){rm.sha=null}setFeed('changes')}
/* ---------- the lane sheet ----------
   Goal, resume note, findings, references and past conversations: everything that is about
   the work rather than the code. Reachable any time with i, from the lane name in the
   bar, and from a Home card - visible on demand, never in the way of a diff. */
function openSheet(id){if(id&&id!==S.lane){S.lane=id;S.sheetRaw=null}
  if(!cur())return;$('#sheetwrap').classList.remove('hidden');renderSheet();$('#sheetClose').focus()}
function closeSheet(){$('#sheetwrap').classList.add('hidden')}
function toggleSheet(){$('#sheetwrap').classList.contains('hidden')?openSheet():closeSheet()}
function parseSessions(txt){
  return (txt||'').trim().split('\n').slice(1).map(l=>{
    const m=/^\s*(\S+ \S+)\s+(\S{8,})\s+(\d+) turns\s+(.*)$/.exec(l);
    return m?{when:m[1],id:m[2],turns:+m[3],first:m[4]}:null}).filter(Boolean);
}
async function loadSheetRaw(){const w=cur();if(!w)return;S.sheetRaw={id:w.id,html:'<pre class="raw muted">Reading the lane file…</pre>'};renderSheet();
  try{const j=await api(`${laneApi(w.id)}/spec`);S.sheetRaw={id:w.id,html:j.spec?md(j.spec):'<p>No file.</p>'}}
  catch(e){S.sheetRaw={id:w.id,html:`<pre class="raw bad">${esc(e.message)}</pre>`}}
  renderSheet()}
/* Goal, resume note, findings, references, conversations and the lane file, top to bottom:
   everything that is about the work rather than the code. Reachable any time with i, from the
   lane name in the bar, from the goal strip and from a Home card. */
function renderSheet(){
  const w=cur();if(!w)return;
  $('#sheetname').innerHTML=`<span class="tk state ${esc(w.status)}">${esc(w.status)}</span>${ticketChip(w)}`;
  $('#sheetsub').innerHTML=`${ico('branch','sm')}<span>${esc(w.id)}</span><span class="faint">· ${esc(laneTitle(w))}</span>`;
  const refs=w.refs||[];
  // on the lane's own screen, the repo in front of you; from Home, every repo of the lane
  const inWork=S.view==='work'&&S.data;
  const sessions=inWork?parseSessions(S.data.sessions):w.repos.flatMap(r=>parseSessions(S.sessAll?.[r.repo]));
  const fnd=(w.findings||'').replace(/^\(things learned[\s\S]*?\)$/m,'').trim();
  const items=fnd.split('\n').filter(l=>/^\s*[-*]\s+/.test(l)).map(l=>l.replace(/^\s*[-*]\s+/,''));
  const sess=[...sessions].sort((a,b)=>b.when.localeCompare(a.when));
  const raw=S.sheetRaw&&S.sheetRaw.id===w.id?S.sheetRaw.html:null;
  $('#sheetbody').innerHTML=`
    <div class="ssec"><h5>${ico('target','sm')}Goal</h5>${realText(w.goal)?`<div class="sbox">${md(w.goal)}</div>`:'<div class="sbox dim">No goal written yet. It lives in the lane file’s ## Goal section.</div>'}</div>
    <div class="ssec"><h5>${ico('note','sm')}Resume note</h5>${realText(w.note)?`<div class="sbox note">${md(w.note)}</div>`:'<div class="sbox dim">No resume note. Parking asks for one.</div>'}</div>
    <div class="ssec"><h5>${ico('bulb','sm')}Findings <span class="q">· kept only while this work is live</span>${items.length?`<span class="pill">${items.length}</span>`:''}</h5>
      ${items.length?items.map(x=>`<div class="fitem">${inline(x)}</div>`).join(''):fnd?`<div class="sbox">${md(fnd)}</div>`:'<div class="sbox dim">Nothing learned yet. Drafts filed to this lane land here.</div>'}</div>
    ${(w.links||[]).length?`<div class="ssec"><h5>${ico('ext','sm')}Links <span class="q">· hand-written in the lane file</span></h5>
      ${w.links.map(l=>`<div class="srow">${ico('ext','sm')}<span>${esc(l.label)}</span><a href="${esc(l.url)}" target="_blank" rel="noreferrer" class="sx">${esc(l.url)}</a></div>`).join('')}</div>`:''}
    <div class="ssec"><h5>${ico('repo','sm')}Repos</h5>
      ${w.repos.map(r=>`<div class="srow"><span class="repotag ${repoClass(r.repo)}">${esc(shortOf(r))}</span><span>${esc(r.repo)}</span>
        <span class="branch">${ico('branch','sm')}${esc(r.branch||'')}</span><span class="sx">${r.base?'from '+esc(r.base)+' · ':''}${r.exists?(changed(r)?plural(changed(r),'file')+' open':'clean'):'no worktree'}</span></div>`).join('')}</div>
    <div class="ssec"><h5>${ico('folder','sm')}References <button class="link" onclick="refAddDlg()">${ico('plus','sm')}Attach a reference</button></h5>
      ${refs.length?refs.map(r=>{const nm=r.name||r.path.split('/').pop();return`<div class="refc"><div class="rh">${ico('folder','sm')}<span>${esc(nm)}</span><span class="mode">${esc(r.mode||'read-only')}</span></div>
          <div class="rpath" title="${esc(r.path)}">${esc(r.path)}</div>${r.note?`<div class="rnote">${esc(r.note)}</div>`:''}
          <div class="ra"><button class="txt" data-reveal="${esc(nm)}">${ico('eye','sm')} Reveal</button><button class="txt" data-detach="${esc(nm)}">${ico('unlink','sm')} Detach</button></div></div>`}).join('')
        :`<div class="sbox dim">Nothing attached. A reference shows up as <span class="mono">lanes/${esc(w.id)}/refs/&lt;name&gt;</span>, read-only unless attached with --rw.</div>`}</div>
    <div class="ssec"><h5>${ico('term','sm')}Sessions <span class="q">· past Claude conversations in ${esc(inWork?S.repo:w.repos.map(r=>r.repo).join(', '))}</span></h5>
      ${sess.length?sess.map(s=>`<div class="sessc"><div class="top"><span>${esc(s.when)}</span><span class="tn">${s.turns} turns</span></div>
          <div class="tx">${esc(s.first)}</div>
          <button class="cmdline" data-resume="${esc(s.id)}" title="Copy: claude --resume ${esc(s.id)}"><span>claude --resume ${esc(s.id)}</span>${ico('copy','sm')}</button></div>`).join('')
        :'<div class="sbox dim">None recorded for this repo.</div>'}</div>
    <div class="ssec"><h5>${ico('file','sm')}The lane file <span class="q">· registry/lanes/${esc(w.id)}.md</span>
      ${raw?'':`<button class="link" onclick="loadSheetRaw()">Show it</button>`}</h5>${raw?`<div class="sbox">${raw}</div>`:''}</div>`;
  let foot='';
  if(w.status!=='active')foot=`<span class="sp"></span><button class="pri" onclick="closeSheet();laneRun({action:'resume',id:'${esc(w.id)}'})">${ico('play','sm')}Resume lane</button>`;
  else foot=`<button onclick="closeSheet();parkDlg()">${ico('park','sm')}Park lane</button><span class="sp"></span><button class="pri" onclick="closeSheet();finishDlg()">${ico('flag','sm')}Finish lane</button>`;
  $('#sheetfoot').innerHTML=foot;
}
/* ---------- the left column is a source picker; the pane is one stage ----------
   Changes feeds it file diffs, History feeds it commit diffs. History answers the
   question at two widths: this repo's branch, or every repo of the lane
   interleaved — a lane spans four repos, so "what happened on this work"
   is four logs, not one. */
const feedOf=()=>{const m=mem();return m?(m.feed||'changes'):'changes'};
const hscopeOf=()=>{const m=mem();return m?(m.hscope||'repo'):'repo'};
/* 'work' = origin/<base>..HEAD, the commits this lane added. 'all' = the branch tail,
   which on a branch behind its base is mostly commits that arrived with the base. */
const hrangeOf=()=>{const m=mem();if(!m)return'work';
  if(hscopeOf()==='lane')return'work';          // the lane view is this work, by definition
  return m.hrange||'work'};
function setHRange(r){const m=mem();if(!m)return;m.hrange=r;nav(false);
  if(hscopeOf()==='lane')loadWsLog();renderFeedBar();renderFiles();renderStage(true)}
function setFeed(f){const m=mem();if(!m)return;m.feed=f;nav(true);
  if(f==='history'&&hscopeOf()==='lane')loadWsLog();
  renderFeedBar();renderFiles();renderStage(true)}
function setHScope(sc){const m=mem();if(!m)return;m.hscope=sc;nav(false);
  if(sc==='lane')loadWsLog();renderFeedBar();renderFiles();renderStage(true)}
function renderFeedBar(){
  const feed=feedOf(),hs=hscopeOf(),d=S.data;
  document.querySelectorAll('#feeds .feed').forEach(b=>b.classList.toggle('sel',b.dataset.feed===feed));
  $('#feedcount').textContent=d?(d.files.length||''):'';
  $('#scopebar').classList.toggle('hidden',feed!=='history');
  document.querySelectorAll('#scopebar .sc').forEach(b=>b.classList.toggle('sel',b.dataset.scope===hs));
  $('#ffilter').placeholder=feed==='history'
    ? (hs==='lane'?'Filter commits across all repos':'Filter commits on this branch')
    : (d&&d.files.length?`Filter ${d.files.length} files`:'Filter files');
}
async function loadWsLog(){
  const whole=hrangeOf()==='all';const key=`${S.lane}|${whole?'all':'work'}`;
  if(S.wslogKey===key&&S.wslog)return;
  try{const j=await api(`${laneApi()}/log${whole?'?all=1':''}`);
    S.wslog=j.log;S.wslogKey=key;
    if(feedOf()==='history')renderFiles()}catch(e){toast('err',e.message)}}
function crow(c,withRepo){
  const rm=rmem();const sel=rm&&rm.sha===c.sha;
  const refs=(c.refs||'').split(',').map(x=>x.trim().replace(/^HEAD -> /,'')).filter(x=>x&&x!=='HEAD').slice(0,1);
  return`<div class="crow ${sel?'sel':''}" data-sha="${esc(c.sha)}" data-repo="${esc(c.repo||'')}" tabindex="0" title="${esc(c.date||'')}">
    <span class="sha">${esc(c.sha)}</span>${withRepo&&c.short?`<span class="rp ${repoClass(c.repo)}">${esc(c.short)}</span>`:'<span></span>'}
    ${refs.length?`<span class="ref">${esc(refs[0])}</span>`:'<span></span>'}<span class="when">${esc(c.when)}</span>
    <span class="sub">${esc(c.subject)}</span><span class="who">${esc(c.author)}</span></div>`;
}
function folderOf(f){const i=f.lastIndexOf('/');return i<0?'(root)':f.slice(0,i)}
function renderFiles(){
  const d=S.data;if(!d)return;
  renderFeedBar();
  const flt=S.filter.toLowerCase();const el=$('#files');const scroll=el.scrollTop;
  if(feedOf()==='history'){
    const lane=hscopeOf()==='lane',work=hrangeOf()==='work';
    const src=lane?(S.wslog||null):(work?d.worklog:d.log);
    if(!src){el.innerHTML='<div class="empty">Reading every repo\u2026</div>';return}
    const rows=src.filter(c=>`${c.subject} ${c.sha} ${c.author} ${c.short||''}`.toLowerCase().includes(flt));
    const base=esc(curRepo()?.base_branch||'the base branch');
    const foot=lane?'' :work
      ?`<button class="histmore txt" onclick="setHRange('all')">Show earlier commits that came from ${base} \u2193</button>`
      :`<button class="histmore txt" onclick="setHRange('work')">\u2191 Hide ${base}'s commits \u2014 show only this work</button>`;
    el.innerHTML=(rows.map(c=>crow(c,lane)).join('')
      ||`<div class="empty">${S.filter?'No commits match that filter.'
        :work?`Nothing committed yet beyond <b>${base}</b>.`
             :'No commits on this branch.'}</div>`)+foot;
    $('#fcount').textContent=S.filter?`${rows.length} of ${src.length}`
      :`${plural(src.length,'commit')}${work?'':' (all)'}`;
    el.scrollTop=scroll;return;
  }
  const list=d.files.filter(f=>f.file.toLowerCase().includes(flt));
  const focus=document.activeElement?.closest?.('.frow')?.dataset;
  // a partly staged file shows in both sections: its staged half and its open half
  const st=list.filter(f=>f.staged),un=list.filter(f=>f.unstaged);
  const section=(title,fs,staged)=>{
    if(!fs.length)return'';
    const all=JSON.stringify(fs.map(f=>f.file));
    let h=`<div class="fsec">${title}<span class="n">(${fs.length})</span><button class="txt" onclick="event.stopPropagation();stage(${esc(all)},${!staged})">${staged?'Unstage all':'Stage all'}</button></div>`;
    const groups=new Map();
    for(const f of fs){const k=folderOf(f.file);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(f)}
    const many=groups.size>1||!groups.has('(root)');
    for(const[dir,g]of groups){
      if(many)h+=`<div class="fold">${ico('folder','sm')}<span>${esc(dir)}</span><span class="c">${g.length}</span>
        ${!staged&&g.length>1?`<button class="txt" onclick="event.stopPropagation();stage(${esc(JSON.stringify(g.map(f=>f.file)))},true)">stage folder</button>`:''}</div>`;
      h+=g.map(f=>frow(f,staged)).join('');
    }
    return h;
  };
  const html=section('Staged changes',st,true)+section('Unstaged changes',un,false);
  el.innerHTML=html?html+`<div class="legend"><span><b class="warn">M</b> modified</span><span><b class="ok">A</b> added</span><span><b class="bad">D</b> deleted</span><span><b class="faint">?</b> untracked</span></div>`
    :(S.filter?'<div class="empty">No files match that filter.</div>':`<div class="empty big">${ico('check')}Working tree clean.</div>`);
  const tot=d.files.length;
  $('#fcount').textContent=S.filter?`${list.length} of ${tot}`:(tot?plural(tot,'file'):'');
  document.querySelectorAll('.frow input[data-ind]').forEach(i=>i.indeterminate=true);
  el.scrollTop=scroll;
  if(focus)$(`.frow[data-file="${CSS.escape(focus.file)}"]`)?.focus();
}
/* the stage: one reading surface, whatever the picker points at */
function stageSig(){
  const d=S.data,rm=rmem();if(!d||!rm)return 'none';
  return feedOf()==='history'
    ? ['c',rm.sha||'',S.diffAll?1:0].join('|')
    : ['f',rm.file||'',rm.staged?1:0,S.diffKey,S.diff?(S.diff.diff||'').length:-1].join('|');
}
function renderStage(force){
  const d=S.data,rm=rmem();const head=$('#stagehead');
  const sig=stageSig();
  if(!force&&sig===S.stageSig&&$('#pbody').childElementCount)return;   // nothing changed: keep the scroll
  S.stageSig=sig;
  if(!d){head.innerHTML='';$('#pbody').innerHTML='<div class="center">No worktree for this repo.</div>';return}
  if(feedOf()==='history'){
    if(rm&&rm.sha){showCommit(rm.sha);return}
    head.innerHTML=`${ico('commit','sm')}<span class="dim">Pick a commit to read it</span>`;
    $('#pbody').innerHTML=`<div class="center">${ico('commit','big')}Commits on <b>${esc(hscopeOf()==='lane'?'every repo of this lane':d.state.branch)}</b>.<br>Click one to see exactly what it changed.</div>`;
    return;
  }
  if(!rm||!rm.file){
    head.innerHTML=`${ico('diff','sm')}<span class="dim">${d.files.length?'Pick a file to read its diff':'Working tree clean'}</span>`;
    $('#pbody').innerHTML=`<div class="center">${d.files.length?`${ico('diff','big')}Select a file on the left to read its diff.`:`${ico('check','big')}<b>Working tree clean.</b><br>Last commit ${esc(d.log[0]?.when||'')}: “${esc(d.log[0]?.subject||'')}”`}</div>`;
    return;
  }
  const f=d.files.find(x=>x.file===rm.file&&(rm.staged?x.staged:x.unstaged))||d.files.find(x=>x.file===rm.file);
  const a=f?(rm.staged?f.add_staged:f.add):null,dl=f?(rm.staged?f.del_staged:f.del):null;
  const fl=JSON.stringify([rm.file]);
  head.innerHTML=`${ico('file','sm')}<b title="${esc(rm.file)}">${esc(rm.file)}</b>
    <span class="tagq">${rm.staged?'staged':f&&f.untracked?'untracked':'unstaged'}</span>
    ${a!=null?`<span class="counts"><span class="ok">+${a}</span> <span class="bad">−${dl}</span></span>`:''}<span class="sp"></span>
    ${f?`<button class="sm" onclick="stage(${esc(fl)},${!rm.staged})">${rm.staged?'Unstage':'Stage'}</button>
    ${rm.staged?'':`<button class="sm ghost" onclick="discardDlg(${esc(fl)})" title="Throw away these changes">${ico('trash','sm')}Discard</button>`}`:''}`;
  renderDiff();
}
function updateCommitBtn(){
  const d=S.data;const n=d?d.files.filter(f=>f.staged).length:0;const msg=$('#msg').value;
  const first=msg.split('\n')[0];const mc=$('#mcount');mc.textContent=first.length;mc.className=first.length>72?'warn':'';
  const b=$('#commitBtn');if(!b)return;
  const busy=S.busy?.id==='commit';
  b.innerHTML=busy?'Committing…':`${ico('check','sm')}Commit ${n?plural(n,'file'):''}`.trim();
  b.disabled=busy||!n||!msg.trim();
  b.title=!n?'Tick a file first':!msg.trim()?'Write a message first':'⌘⏎';
}

/* ---------- selection ---------- */
async function openWs(id,repo){
  S.lane=id;const w=cur();if(!w)return goHome();
  const m=mem();
  S.repo=repo&&w.repos.find(r=>r.repo===repo)?repo:
    ((m.repo||LSg('lane-repo:'+id,''))&&w.repos.find(r=>r.repo===(m.repo||LSg('lane-repo:'+id,'')))?(m.repo||LSg('lane-repo:'+id,'')):
     (w.repos.filter(r=>r.exists).sort((a,b)=>(changed(b)?1:0)-(changed(a)?1:0)||(b.ahead||0)-(a.ahead||0))[0]||w.repos[0])?.repo||null);
  m.repo=S.repo;rememberPlace();
  setView('work');await loadRepo(false);
}
async function pickRepo(repo){S.repo=repo;mem().repo=repo;rememberPlace();nav(true);renderRepos();await loadRepo(false)}

/* ---------- URLs: the path names the place, the query only how it is shown ----------
   /  /memory[/<scope>][?file=]  /lanes/<lane>[/<repo>][?file=&staged=1]
   /lanes/<lane>/<repo>/history[?repos=all&range=all]  /lanes/<lane>/<repo>/commits/<sha>
   Another workspace: the same under /w/<name>. ?theme= rides along on any page.
   Moving somewhere pushes a history entry; changing how it is shown (file, staged, history
   scope) replaces it, so Back does not step through every click. */
const planePrefix=()=>S.plane&&S.plane!=='home'?`/w/${E(S.plane)}`:'';
const href=p=>(planePrefix()+(p==='/'&&planePrefix()?'':p))||'/';
function currentUrl(){
  let p='/';const q=new URLSearchParams();
  if(S.view==='memory'){p='/memory'+(S.mscope?`/${E(S.mscope)}`:'');if(S.mfile)q.set('file',S.mfile)}
  else if(S.view==='work'&&S.lane){
    p=`/lanes/${E(S.lane)}`;
    if(S.repo){p+=`/${E(S.repo)}`;const m=mem(),rm=rmem();
      if(feedOf()==='history'){p+=rm?.sha?`/commits/${E(rm.sha)}`:'/history';
        if(hscopeOf()==='lane')q.set('repos','all');if(m?.hrange==='all')q.set('range','all')}
      else if(rm?.file){q.set('file',rm.file);if(rm.staged)q.set('staged','1')}}}
  const th=new URLSearchParams(location.search).get('theme');if(th)q.set('theme',th);
  const qs=q.toString();return href(p)+(qs?'?'+qs:'');
}
function nav(push){
  if(S.routing)return;
  const u=currentUrl();if(u===location.pathname+location.search)return;
  try{history[push?'pushState':'replaceState'](null,'',u)}catch{}
}
/* read the URL and put the board there: first load, Back/Forward, and internal links */
async function applyRoute(){
  S.routing=true;
  try{
    let segs=location.pathname.split('/').filter(Boolean).map(s=>{try{return decodeURIComponent(s)}catch{return''}});
    const q=new URLSearchParams(location.search);
    let plane=null;if(segs[0]==='w'&&segs[1]){plane=segs[1];segs=segs.slice(2)}
    const curPlane=S.plane&&S.plane!=='home'?S.plane:null;
    if(plane!==curPlane||!S.board){S.plane=plane;S.board=null;S.boardSig=null;S.lane=null;S.repo=null;S.data=null;
      updateTitle();const sel=$('#planeSel');if(sel&&S.planes)sel.value=plane||(S.planes.planes||[]).find(p=>p.home)?.name||'';
      await loadBoard()}
    if(segs[0]==='memory'){S.mscope=segs[1]||null;S.mfile=q.get('file')||null;setView('memory');return}
    if(segs[0]==='lanes'&&segs[1]){
      const w=S.board?.lanes.find(x=>x.id===segs[1]);
      if(!w){setView('home');toast('err',`No lane ${segs[1]} in this workspace.`);return}
      await openWs(w.id,segs[2]||null);
      const m=mem(),rm=rmem();if(!m||!rm)return;
      if(segs[3]==='history'||segs[3]==='commits'){
        m.feed='history';m.hscope=q.get('repos')==='all'?'lane':'repo';m.hrange=q.get('range')==='all'?'all':'work';
        rm.sha=segs[3]==='commits'?(segs[4]||null):null;rm.file=null;
        if(m.hscope==='lane')loadWsLog();renderFeedBar();renderFiles();renderStage(true)}
      else{m.feed='changes';rm.sha=null;const f=q.get('file');
        if(f&&S.data){await pickFile(f,q.get('staged')==='1')}else{rm.file=null;renderFeedBar();renderFiles();renderStage(true)}}
      return}
    setView('home');
  }finally{S.routing=false;nav(false)}
}
async function go(url){try{history.pushState(null,'',url)}catch{}closePal();await applyRoute()}
window.addEventListener('popstate',()=>applyRoute());

/* ---------- board polling ---------- */
/* Signatures: what the screen draws, with the per-poll timestamps left out. */
function boardSig(b){
  return JSON.stringify((b?.lanes||[]).map(w=>[w.id,w.status,w.updated,w.goal,w.note,(w.refs||[]).length,
    w.repos.map(r=>[r.repo,r.branch,r.exists,r.dirty,r.staged,r.unstaged,r.ahead,r.behind,
      r.pr_state,r.pr_failing,r.base_behind,r.last])]));
}
function dataSig(d){
  if(!d)return 'none';
  return JSON.stringify([d.state,d.files,(d.log||[]).map(c=>c.sha),d.pr?[d.pr.number,d.pr.state,d.pr.checks]:null,
    d.nextAction,(d.sessions||'').length]);
}
async function loadBoard(){
  if(S.busy||S.dialog)return;
  try{const b=await api('/api/board');
    if(S.startedAt&&b.serverStartedAt!==S.startedAt){toast('err','Server restarted — reload the page');return}
    S.startedAt=b.serverStartedAt;S.fails=0;
    const sig=boardSig(b);const changedNow=sig!==S.boardSig;S.boardSig=sig;S.board=b;
    $('#clock').textContent='Updated '+b.generated;$('#clock').parentElement.classList.remove('warn');
    if(S.view==='home')loadHomeExtras();
    if(changedNow){renderCrumb();if(!$('#sheetwrap').classList.contains('hidden'))renderSheet();
      if(S.view==='home')renderHome();
      else if(S.view==='work'){if(S.lane&&S.repo&&cur()?.repos.find(r=>r.repo===S.repo)?.exists)await loadRepo(true);else renderRepo()}}
  }catch(e){if(e.message==='restarted')return;S.fails++;const c=$('#clock');c.parentElement.classList.add('warn');
    c.textContent=S.fails>=3?'offline — server stopped?':'stale · retrying'}}
async function refreshRepo(){S.board=await api('/api/board');renderCrumb();await loadRepo(true)}
async function refreshWs(){S.board=await api('/api/board');renderCrumb();renderRepos();await loadRepo(true)}

/* ---------- memory screen ---------- */
async function loadMemory(){try{S.mem=await api('/api/memory');renderMemory();renderRail();if(S.view==='home')renderHome()}catch(e){$('#mbody').innerHTML=`<div class="center">${esc(e.message)}</div>`}}
function mscope(){return S.mem?.scopes.find(s=>s.id===S.mscope)||S.mem?.scopes[0]}
const scopeLabel=sc=>(sc.label||sc.id).replace(/^repo:/,'');
function renderMemory(){
  const m=S.mem;if(!m)return;
  const s=mscope();if(s)S.mscope=s.id;
  const row=sc=>{const repoish=!['cross','pref','drafts'].includes(sc.id);const n=sc.files.length;
    const icon=sc.id==='drafts'?'inbox':sc.id==='pref'?'key':sc.id==='cross'?'book':'repo';
    return`<div class="scope ${sc.id===S.mscope?'sel':''}" data-scope="${esc(sc.id)}" tabindex="0">${ico(icon)}<span>${esc(scopeLabel(sc))}</span>
      <span class="c ${sc.id==='drafts'&&n?'hot':''}">${sc.id==='drafts'&&n?n+' waiting':n}</span>${!repoish&&sc.hint?`<span class="h">${esc(sc.hint)}</span>`:''}</div>`};
  const by=id=>m.scopes.filter(sc=>sc.id===id);
  const repos=m.scopes.filter(sc=>!['cross','pref','drafts'].includes(sc.id));
  $('#mscopes').innerHTML=`<div class="grp">Inbox</div>${by('drafts').map(row).join('')}
    <div class="grp">Everywhere</div>${[...by('pref'),...by('cross')].map(row).join('')}
    <div class="grp">Repository scopes</div><div class="gsub">True for that repo after tickets ship</div>
    ${repos.map(row).join('')||'<div class="empty">No repo memory yet.</div>'}`;
  const files=s?.files||[];
  if(!files.find(f=>f.file===S.mfile))S.mfile=files[0]?.file||null;
  const drafts=s?.id==='drafts';
  $('#mfiles').innerHTML=`<div class="mhead"><b>${esc(s?scopeLabel(s):'')}<span class="n">${files.length}</span></b><span>${esc(drafts?'Waiting for you to pick a scope':s?.hint||'')}</span></div>
    <div class="mlist">${files.map(f=>`<div class="mrow ${f.file===S.mfile?'sel':''}" data-mfile="${esc(f.file)}" tabindex="0">
      <div class="t">${drafts?'<span class="dotc"></span>':''}${esc(f.name||f.file.replace(/\.md$/,''))}</div>
      ${f.description?`<div class="d">${esc(f.description)}</div>`:''}
      <div class="m">${f.type?`<span class="ty">${esc(f.type)}</span>`:''}<span>${esc(daysAgo(f.modified)||f.modified||'')}</span><span class="sp"></span><span>${esc(f.file)}</span></div></div>`).join('')
    ||`<div class="empty big">${drafts?`${ico('check')}No drafts waiting. Claude drafts a memory when it learns something; you pick where it goes.`:'Nothing in this scope yet.'}</div>`}</div>`;
  renderMemBody();
  renderCrumb();
  if(S.view==='memory')nav(false);
}
async function renderMemBody(){
  const s=mscope();const f=s?.files.find(x=>x.file===S.mfile);const b=$('#mbody');
  if(!f){b.innerHTML=`<div class="center">${ico('book','big')}Pick a memory on the left.</div>`;return}
  const key=S.mscope+'/'+S.mfile;b.dataset.key=key;
  b.innerHTML='<div class="center">Reading…</div>';
  try{const j=await api(`/api/memory/${E(S.mscope)}/${E(S.mfile)}`);
    if(b.dataset.key!==key)return;   // a newer pick won
    const drafts=S.mscope==='drafts',pref=S.mscope==='pref';
    const fq=esc(JSON.stringify(S.mfile));
    const acts=drafts?`<button class="pri" onclick='memFileDlg(${fq})'>${ico('inbox','sm')}File it</button><button onclick='memDropDlg(${fq})'>${ico('trash','sm')}Discard</button>`
      :pref?'':`<button onclick='memMoveDlg(${fq})'>${ico('move','sm')}Move scope</button><button class="ghost" onclick='memRmDlg(${fq})'>${ico('trash','sm')}Delete</button>`;
    const body=String(j.content||'').replace(/^---\n[\s\S]*?\n---\n?/,'');
    b.innerHTML=`<div class="mview"><div class="mvh"><span class="eyebrow">Memory / ${esc(scopeLabel(s))}</span><h2>${esc(f.name||f.file)}</h2>
      <div class="meta">${f.type?`<span class="tk">type: ${esc(f.type)}</span>`:''}<span>modified ${esc(f.modified||'')}</span><span>·</span><span>${esc(j.path)}</span></div>
      ${f.description?`<div class="muted">${esc(f.description)}</div>`:''}
      ${acts?`<div class="acts">${acts}</div>`:''}</div>
      ${md(body||'_Empty._')}
      ${drafts?`<div class="mcta">${ico('info')}<span><b>Where does it belong?</b> Filing it to a repo or cross-repo scope makes it standing memory for every future session there.</span><button class="pri sm" onclick='memFileDlg(${fq})'>File it ${ico('arrow','sm')}</button></div>`:''}</div>`;
  }catch(e){b.innerHTML=`<div class="center">${esc(e.message)}</div>`}
}

/* ---------- palette ---------- */
function palRows(q){
  const b=S.board;if(!b)return[];
  const norm=s=>String(s||'').toLowerCase();
  const terms=norm(q).split(/\s+/).filter(Boolean);
  const hit=(hay)=>terms.every(t=>norm(hay).includes(t));
  const rows=[];
  const w=cur();
  if(w)for(const r of w.repos){
    const hay=`${r.repo} ${shortOf(r)} ${w.id}`;
    if(hit(hay))rows.push({kind:'repo',group:'In this lane',lane:w.id,repo:r.repo,
      name:r.repo,sub:r.exists?(changed(r)?plural(changed(r),'file')+' changed':r.ahead?plural(r.ahead,'commit')+' to push':'in sync'):'no worktree',r});
  }
  for(const x of b.lanes){
    if(x.id===S.lane)continue;
    if(hit(`${x.id} ${x.ticket||''} ${x.repos.map(r=>r.repo+' '+shortOf(r)).join(' ')}`))
      rows.push({kind:'lane',group:x.status==='active'?'Lanes':'Parked',lane:x.id,repo:null,
        name:x.id,sub:`${plural(x.repos.length,'repo')}${x.status==='active'?'':' · parked'}`,w:x});
  }
  if(hit('memory'))rows.push({kind:'mem',group:'Elsewhere',name:'Memory',sub:'preferences, facts, per-repo notes'});
  if(hit('home board overview'))rows.push({kind:'home',group:'Elsewhere',name:'Home',sub:'every lane, and what wants a decision'});
  return rows;
}
function markMatch(name,q){
  const terms=q.toLowerCase().split(/\s+/).filter(Boolean);let out=esc(name);
  for(const t of terms){const i=out.toLowerCase().indexOf(t);if(i<0)continue;
    out=out.slice(0,i)+'<em>'+out.slice(i,i+t.length)+'</em>'+out.slice(i+t.length)}
  return out;
}
function renderPal(){
  const rows=S.pal.rows,q=S.pal.q;
  if(S.pal.i>=rows.length)S.pal.i=Math.max(0,rows.length-1);
  let html='',group=null;
  rows.forEach((r,i)=>{
    if(r.group!==group){group=r.group;html+=`<div class="pgrp">${esc(group)}</div>`}
    const icon=r.kind==='repo'?'repo':r.kind==='lane'?'branch':r.kind==='mem'?'book':'home';
    let state='';
    if(r.kind==='repo'&&r.r){const ch=changed(r.r);
      if(ch)state=`<span class="warn stat">${ico('diff','sm')}${ch}</span>`;
      else if(r.r.ahead)state=`<span class="topush stat">${ico('push','sm')}${r.r.ahead}</span>`;}
    if(r.kind==='lane'&&r.w){const ch=laneChanged(r.w);if(ch)state=`<span class="warn stat">${ico('diff','sm')}${ch}</span>`}
    const pill=r.kind==='lane'&&r.w?`<span class="tk state ${esc(r.w.status)}">${esc(r.w.status)}</span>`:'';
    const to=r.kind==='home'?'/':r.kind==='mem'?'/memory':r.kind==='repo'?`/lanes/${E(r.lane)}/${E(r.repo)}`:`/lanes/${E(r.lane)}`;
    html+=`<a class="prow ${i===S.pal.i?'on':''}" data-i="${i}" href="${esc(href(to))}">${ico(icon)}
      <span class="nm">${markMatch(r.name,q)}</span>${pill}<span class="sub">${esc(r.sub||'')}</span>
      <span class="c">${state}${i===S.pal.i?'<kbd>&crarr;</kbd>':''}</span></a>`;
  });
  $('#pallist').innerHTML=html||`<div class="empty big">Nothing matches “${esc(q)}”.</div>`;
  $('#palcount').textContent=rows.length?`${rows.length} found`:'';
  $('#pallist').querySelector('.prow.on')?.scrollIntoView({block:'nearest'});
}
function openPal(){S.pal={open:true,q:'',rows:palRows(''),i:0};$('#palwrap').classList.remove('hidden');
  $('#palq').value='';renderPal();$('#palq').focus()}
function closePal(){S.pal.open=false;$('#palwrap').classList.add('hidden')}
function palGo(){
  const r=S.pal.rows[S.pal.i];if(!r)return;closePal();
  if(r.kind==='home')return goHome();
  if(r.kind==='mem'){setView('memory');return}
  if(r.kind==='repo')return pickRepo(r.repo);
  return openWs(r.lane);
}

/* ---------- wiring ---------- */
document.addEventListener('click',e=>{
  const a=e.target.closest('a[href^="/"]');
  if(a&&!a.target&&e.button===0&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey&&!e.target.closest('button')){
    e.preventDefault();go(a.getAttribute('href'));return}
  const nx=e.target.closest('[data-next]');if(nx){e.stopPropagation();runNext(nx.dataset.next);return}
  const orp=e.target.closest('[data-open-repo]');if(orp){openWs(orp.dataset.openRepo,orp.dataset.repo);return}
  const rl=e.target.closest('[data-rail]');if(rl){const k=rl.dataset.rail;
    if(k==='memory'){setView(S.view==='memory'&&S.lane?'work':'memory');return}
    if(S.view!=='home')goHome();
    if(k==='parked'){if(!parkedOpen()){LSs('lane-parked-collapsed','0');renderHome()}const h=$('#parkedHead');if(h)h.scrollIntoView({behavior:'smooth',block:'start'});else toast('ok','No parked lanes.')}
    else $('#home .hmain')?.scrollTo({top:0,behavior:'smooth'});return}
  const mfi=e.target.closest('[data-mfileit]');if(mfi){e.stopPropagation();memFileDlg(mfi.dataset.mfileit);return}
  const mdr=e.target.closest('[data-mdrop]');if(mdr){e.stopPropagation();memDropDlg(mdr.dataset.mdrop);return}
  const mop=e.target.closest('[data-mopen]');if(mop){S.mscope='drafts';S.mfile=mop.dataset.mopen;setView('memory');return}
  const rv=e.target.closest('[data-reveal]');if(rv){refReveal(rv.dataset.reveal);return}
  const dt=e.target.closest('[data-detach]');if(dt){refRm(dt.dataset.detach);return}
  if(e.target.closest('[data-home]')){goHome();return}
  if(e.target.closest('#goalstrip')){openSheet();return}
  const ab=e.target.closest('[data-about]');if(ab){e.stopPropagation();S.lane=ab.dataset.about;openSheet(ab.dataset.about);return}
  const open=e.target.closest('[data-open]');if(open){openWs(open.dataset.open);return}
  const r=e.target.closest('#repos .r');if(r){pickRepo(r.dataset.repo);return}
  const fd=e.target.closest('#feeds .feed');if(fd){setFeed(fd.dataset.feed);return}
  const sc2=e.target.closest('#scopebar .sc');if(sc2){setHScope(sc2.dataset.scope);return}
  const cr=e.target.closest('.crow');if(cr){const rm=rmem();if(rm){rm.sha=cr.dataset.sha;rm.file=null}
    if(cr.dataset.repo&&cr.dataset.repo!==S.repo){pickRepo(cr.dataset.repo).then(()=>{const r2=rmem();if(r2)r2.sha=cr.dataset.sha;nav(true);renderFiles();renderStage(true)})}
    else{nav(true);renderFiles();renderStage(true)}return}
  const sn=e.target.closest('#crumb b.link');if(sn){openSheet();return}
  const rs=e.target.closest('[data-resume]');if(rs){const cmd='claude --resume '+rs.dataset.resume;
    navigator.clipboard?.writeText(cmd);toast('ok','Copied: '+cmd);return}
  if(e.target.id==='sheetwrap'){closeSheet();return}
  const f=e.target.closest('.frow');if(f){
    if(e.target.type==='checkbox'){stage([f.dataset.file],e.target.checked);return}
    pickFile(f.dataset.file,f.dataset.staged==='1');return}
  const sc=e.target.closest('#mscopes .scope');if(sc){S.mscope=sc.dataset.scope;S.mfile=null;nav(true);renderMemory();return}
  const mf=e.target.closest('[data-mfile]');if(mf){S.mfile=mf.dataset.mfile;nav(false);renderMemory();return}
  if(e.target.id==='palwrap'){closePal();return}
  const h=e.target.closest('.hrow');if(h){showCommit(h.dataset.sha);return}
});
$('#planeSel').onchange=e=>switchPlane(e.target.value);
$('#sheetClose').onclick=closeSheet;
$('#aboutBtn').onclick=()=>{if(cur())openSheet()};
$('#newBtn').onclick=()=>startDlg();
$('#helpBtn').onclick=()=>helpDlg();
$('#switchBtn').onclick=openPal;
$('#theme').onclick=()=>{const cur=(()=>{try{return localStorage.getItem('lane-theme')||'system'}catch{return'system'}})();
  applyTheme(THEMES[(THEMES.indexOf(cur)+1)%3])};
$('#ffilter').addEventListener('input',e=>{S.filter=e.target.value;renderFiles()});
$('#ffilter').addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();
  if(e.target.value){e.target.value='';S.filter='';renderFiles()}else e.target.blur()}});
$('#msg').addEventListener('input',updateCommitBtn);
$('#palq').addEventListener('input',e=>{S.pal.q=e.target.value;S.pal.rows=palRows(e.target.value);S.pal.i=0;renderPal()});
$('#palq').addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'||(e.key==='n'&&e.ctrlKey)){e.preventDefault();S.pal.i=Math.min(S.pal.rows.length-1,S.pal.i+1);renderPal()}
  else if(e.key==='ArrowUp'||(e.key==='p'&&e.ctrlKey)){e.preventDefault();S.pal.i=Math.max(0,S.pal.i-1);renderPal()}
  else if(e.key==='Enter'){e.preventDefault();palGo()}
  else if(e.key==='Escape'){e.preventDefault();closePal()}});

document.addEventListener('keydown',e=>{
  const inField=/INPUT|TEXTAREA/.test(e.target.tagName);const meta=e.metaKey||e.ctrlKey;
  if(meta&&(e.key==='k'||e.key==='K')){e.preventDefault();return S.pal.open?closePal():openPal()}
  if(S.pal.open)return;
  if(meta&&e.key==='Enter'){e.preventDefault();return commit()}
  if(meta&&(e.key==='p'||e.key==='P')){e.preventDefault();return primary()}
  if(e.key==='Escape'){if(S.dialog)return;
    if(!$('#sheetwrap').classList.contains('hidden')){closeSheet();return}
    if(S.filter){S.filter='';$('#ffilter').value='';renderFiles();return}
    const t=$('#toasts').lastChild;if(t){t.remove();return}
    if(S.view!=='home')goHome();return}
  if(inField||S.dialog)return;
  if(e.key==='Enter'&&e.target.matches?.('[data-open]')){e.preventDefault();openWs(e.target.dataset.open);return}
  if(e.key==='i'){if(cur())toggleSheet();return}
  if(e.key==='?')return helpDlg();
  if(e.key==='r')return S.view==='memory'?loadMemory():loadBoard();
  if(e.key==='m')return setView(S.view==='memory'?'home':'memory');
  if(e.key==='g')return goHome();
  if(e.key==='c'){$('#msg')?.focus();return}
  if(e.key==='/'){e.preventDefault();$('#ffilter')?.focus();return}
  if(S.view!=='work')return;
  const w=cur();
  if(/^[1-9]$/.test(e.key)){const r=w?.repos[+e.key-1];if(r)pickRepo(r.repo);return}
  if(e.key==='['||e.key===']'){const i=w.repos.findIndex(r=>r.repo===S.repo);
    const n=(i+(e.key===']'?1:w.repos.length-1))%w.repos.length;pickRepo(w.repos[n].repo);return}
  if(e.key==='a'&&S.data){e.preventDefault();stage(S.data.files.filter(f=>f.unstaged).map(f=>f.file),true);return}
  if(e.key==='h')return setFeed(feedOf()==='history'?'changes':'history');
  if(e.key==='d')return setFeed('changes');
  if(e.key===' '){const f=document.activeElement?.closest?.('.frow');
    if(f){e.preventDefault();stage([f.dataset.file],f.dataset.staged!=='1')}return}
  if(e.key==='j'||e.key==='k'||e.key==='ArrowDown'||e.key==='ArrowUp'){
    const down=e.key==='j'||e.key==='ArrowDown';const list=[...document.querySelectorAll('.frow')];
    if(!list.length)return;e.preventDefault();
    const i=list.indexOf(document.activeElement);
    const nx=list[Math.min(list.length-1,Math.max(0,(i<0?(down?0:list.length-1):i+(down?1:-1))))];
    nx.focus();nx.scrollIntoView({block:'nearest'})}
});

function helpDlg(){const k=(...a)=>`<span class="k">${a.map(x=>`<kbd>${x}</kbd>`).join('')}</span>`;
  openDlg(dlgHead('Keyboard shortcuts','Navigation is the palette; everything else is one letter.','key')+`<div class="keys2">
${k('⌘','K')}<span>jump to a lane or repo</span>${k('esc')}<span>back out to Home</span>
${k('g')}<span>Home</span>${k('m')}<span>Memory</span>
${k('i')}<span>about this lane</span>${k('r')}<span>refresh</span>
${k('1','–','9')}<span>pick a repo</span>${k('[',']')}<span>previous / next repo</span>
${k('j','k')}<span>move in the file list</span>${k('space')}<span>stage / unstage the file</span>
${k('a')}<span>stage everything</span>${k('/')}<span>filter files</span>
${k('d')}<span>Changes</span>${k('h')}<span>History</span>
${k('c')}<span>commit message</span>${k('⌘','⏎')}<span>commit</span>
${k('⌘','P')}<span>the primary action</span>${k('?')}<span>this list</span></div>`,()=>{});
  $('#dok').textContent='Close';$('#dcancel').classList.add('hidden')}

/* ---------- boot: the URL says where; a bare / is Home ---------- */
(async function boot(){
  applyTheme((()=>{try{return localStorage.getItem('lane-theme')||'system'}catch{return'system'}})());
  $('#home').classList.remove('hidden');
  updateTitle();
  // links from before the board had real URLs: /#lane=X&repo=Y
  const h=new URLSearchParams(location.hash.replace(/^#/,''));
  if(h.get('lane')){try{history.replaceState(null,'',`/lanes/${E(h.get('lane'))}${h.get('repo')?'/'+E(h.get('repo')):''}${location.search}`)}catch{}}
  await loadPlanes();
  await applyRoute();
  loadHomeExtras(true);
  setInterval(loadBoard,4000);
})();
