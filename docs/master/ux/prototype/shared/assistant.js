/* Parthenon UX prototype — Control Center Assistant (relocated verbatim) */
/* ═══ SKILLS — tool-count table + single-surface tool editor (control-center-chatbot) ═══ */
(function(){
'use strict';
var SERVER_NAMES = { filesystem:'File System Tools', github:'GitHub Integration', slack:'Slack Notifications', cc:'Control Center' };
var CATALOG = {
  filesystem: [
    { original:'read_file', canonical:'filesystem____read_file', desc:'Read file contents from path' },
    { original:'list_directory', canonical:'filesystem____list_directory', desc:'List directory contents' },
    { original:'copy_file', canonical:'filesystem____copy_file', desc:'Copy a file to a destination' }
  ],
  github: [
    { original:'create_issue', canonical:'github____create_issue', desc:'Create a new GitHub issue' },
    { original:'list_pull_requests', canonical:'github____list_pull_requests', desc:'List pull requests' },
    { original:'get_pull_request', canonical:'github____get_pull_request', desc:'Read one pull request' }
  ],
  slack: [
    { original:'send_message', canonical:'slack____send_message', desc:'Post a formatted message to a channel' }
  ],
  cc: [
    { original:'invoke_management_tool', canonical:'cc____invoke_management_tool', desc:'Dispatch any registered management tool (permission re-checked per call)' },
    { original:'list_management_tools', canonical:'cc____list_management_tools', desc:'Cheap catalogue: name + description + permission requirement' }
  ]
};
function bind(server, original){
  var t = (CATALOG[server]||[]).filter(function(x){return x.original===original;})[0];
  return { server:server, serverName:SERVER_NAMES[server], original:original, canonical:t?t.canonical:server+'____'+original };
}
var SKILLS = [
  { name:'cc-management', system:true, desc:'Assistant management capability set — dispatched through invoke_management_tool',
    tools:[bind('cc','invoke_management_tool'), bind('cc','list_management_tools')], roles:['admin-user'], active:true },
  { name:'read-analyze-file', desc:'Read and analyze file content with structured output',
    tools:[bind('filesystem','read_file'), bind('filesystem','list_directory')], roles:['analyst','agent-sop'], active:true },
  { name:'github-pr-workflow', desc:'Create and manage pull requests with review automation',
    tools:[bind('github','create_issue'), bind('github','list_pull_requests'), bind('github','get_pull_request')], roles:['agent-skillful'], active:true },
  { name:'slack-notify', desc:'Send formatted Slack notifications and alerts',
    tools:[bind('slack','send_message')], roles:['admin-user','agent-sop'], active:true },
  { name:'db-report', desc:'Query database and format results as structured reports', tools:[], roles:['analyst'], active:true },
  { name:'file-organizer', desc:'Organize files by pattern, extension, or date',
    tools:[bind('filesystem','read_file'), bind('filesystem','list_directory'), bind('filesystem','copy_file')], roles:['agent-skillful'], active:false },
  { name:'ops-escalation', desc:'Escalate operational issues through the Control Center management toolset',
    tools:[bind('cc','invoke_management_tool')], roles:['admin-user'], active:true }
];
var ROLES = ['admin-user','analyst','agent-sop','agent-skillful','auditor'];
var ccMode = false;            /* simulate a caller WITHOUT integration::control_center:read */
var filterQ = '';
var editor = null;             /* { mode, name, draft } */
var pickerSel = [];
var pickerServer = '';

function A(id){ return document.getElementById(id); }
function E(v){ return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

window.skillFilter = function(v){ filterQ=(v||'').toLowerCase(); skillRenderTable(); };
window.skillSetCcMode = function(v){ ccMode=!!v; skillRenderTable(); if(editor) skillRenderEditor(); };
window.skillRenderTable = function(){
  var tbody = A('skills-tbody'); if(!tbody) return;
  var showSystem = A('skill-show-system') && A('skill-show-system').checked;
  var rows = SKILLS.filter(function(k){
    if(k.system && !showSystem) return false;
    if(filterQ && k.name.toLowerCase().indexOf(filterQ)===-1 && (k.desc||'').toLowerCase().indexOf(filterQ)===-1) return false;
    return true;
  });
  tbody.innerHTML = rows.map(function(k){
    var cell = k.tools.length
      ? '<span class="skill-tool-count" title="'+E(k.tools.map(function(t){return t.original;}).join(', '))+'">'+k.tools.length+' tools</span>'
      : '<span class="chip chip-muted" style="font-size:11px">No tools bound</span>';
    var act = '<button class="btn-icon-sm" title="View" onclick="showSkillEditor(\''+E(k.name)+'\',\'view\')">👁️</button>';
    if(!k.system){
      act += '<button class="btn-icon-sm" title="Edit" onclick="showSkillEditor(\''+E(k.name)+'\',\'edit\')">✏️</button>'
           + '<button class="btn-icon-sm" title="Delete" onclick="mcFlashToast(\'Delete skill (prototype).\')">🗑️</button>';
    }
    return '<tr id="row-skill-'+E(k.name)+'">'
      + '<td><div style="display:flex;align-items:center;gap:6px"><strong>'+E(k.name)+'</strong>'
      + (k.system?'<span class="chip chip-blue" style="font-size:10px;padding:1px 7px">System</span>':'')+'</div>'
      + '<div class="skill-desc-caption">'+E(k.desc||'')+'</div></td>'
      + '<td>'+cell+'</td>'
      + '<td><span class="chip '+(k.active?'chip-green':'chip-gray')+'">'+(k.active?'Active':'Inactive')+'</span></td>'
      + '<td class="actions-cell">'+act+'</td></tr>';
  }).join('');
};

window.showSkillEditor = function(name, mode){
  var k = name ? SKILLS.filter(function(x){return x.name===name;})[0] : null;
  mode = mode || (k ? 'edit' : 'create');
  if(k && k.system) mode = 'view';
  editor = { mode:mode, name:name, draft: k ? k.tools.map(function(t){return Object.assign({},t);}) : [] };
  A('skills-list-panel').style.display='none';
  A('skill-editor-panel').style.display='block';
  A('skill-editor-title').textContent = mode==='view' ? ('View Skill: '+(name||'')) : (k ? ('Edit Skill: '+name) : 'Create Skill');
  A('skill-editor-sub').textContent = mode==='view' ? 'Read-only — the same grouped list is used for display and editing'
                                                    : 'Basic info, workflow and bound tools in one surface';
  A('skill-system-note').style.display = (k && k.system) ? 'flex' : 'none';
  A('skill-save-btn').style.display = mode==='view' ? 'none' : 'inline-flex';
  A('skill-editor-actions').style.display = mode==='view' ? 'none' : 'flex';
  A('skill-name-input').value = k ? k.name : '';
  A('skill-name-input').disabled = mode==='view';
  A('skill-desc-input').value = k ? (k.desc||'') : '';
  A('skill-desc-input').disabled = mode==='view';
  A('skill-workflow-input').value = k ? ('Use ' + (k.tools.map(function(t){return t.original;}).join(', ')||'the selected tools') + ' to fulfil the request, then report the outcome.') : '';
  A('skill-workflow-input').disabled = mode==='view';
  skillRenderEditor();
};
window.hideSkillEditor = function(){
  editor = null;
  A('skill-editor-panel').style.display='none';
  A('skills-list-panel').style.display='block';
};
window.skillOnName = function(v){
  var clean = String(v||'').toLowerCase().replace(/[^a-z0-9-]/g,'');
  if(clean !== v) A('skill-name-input').value = clean;
};
window.skillRenderEditor = function(){
  if(!editor) return;
  var isView = editor.mode==='view';
  if(editor.draft.length===0){
    A('skill-bound-tools').innerHTML = '<div class="tool-empty">No tools bound</div>';
  }else{
    var groups={};
    editor.draft.forEach(function(t){ (groups[t.server]=groups[t.server]||[]).push(t); });
    A('skill-bound-tools').innerHTML = Object.keys(groups).sort().map(function(slug){
      return '<div style="margin-bottom:10px"><span class="tool-group-label">'+E(groups[slug][0].serverName||slug)+'</span>'
        + groups[slug].map(function(t){
            var locked = (t.server==='cc' && ccMode);
            return '<div class="tool-line"><code>'+E(t.original||t.canonical)+'</code>'
              + '<span class="tool-canonical">'+E(t.canonical)+'</span>'
              + (locked?'<span class="tool-lock" title="Access to this tool requires the Control Center integration permission — shown read-only because this skill uses it.">🔒 read-only</span>':'')
              + '<span class="tool-remove">'+((!isView && !locked) ? '<button class="btn-icon-sm" title="Remove" onclick="skillRemoveTool(\''+E(t.server)+'\',\''+E(t.original)+'\')">🗑️</button>' : '')+'</span>'
              + '</div>';
          }).join('')+'</div>';
    }).join('');
  }
  A('skill-cc-note').style.display = editor.draft.some(function(t){return t.server==='cc' && ccMode;}) ? 'block' : 'none';
  A('skill-tool-ref').textContent = editor.draft.length
    ? editor.draft.map(function(t){ return '- name: '+t.canonical+'\n  original: '+(t.original||'')+'\n  server: '+t.server; }).join('\n')
    : '—';
  A('skill-roles').innerHTML = ROLES.map(function(r){
    var checked = editor.name ? (SKILLS.filter(function(x){return x.name===editor.name;})[0]||{roles:[]}).roles.indexOf(r)!==-1 : false;
    return '<label class="checkbox-item"><input type="checkbox" '+(checked?'checked':'')+' '+(isView?'disabled':'')+'> '+E(r)+'</label>';
  }).join('');
};
window.skillRemoveTool = function(server, original){
  if(!editor) return;
  editor.draft = editor.draft.filter(function(t){ return !(t.server===server && t.original===original); });
  skillRenderEditor();
};
window.skillSave = function(){
  if(!editor) return;
  var name = A('skill-name-input').value.trim();
  if(!name){ mcFlashToast('Name is required.'); return; }
  var existing = SKILLS.filter(function(x){return x.name===name;})[0];
  if(existing && editor.mode==='create'){ mcFlashToast('A skill named “'+name+'” already exists.'); return; }
  if(existing){
    existing.desc = A('skill-desc-input').value.trim();
    existing.tools = editor.draft.slice();
  }else{
    SKILLS.push({ name:name, desc:A('skill-desc-input').value.trim(), tools:editor.draft.slice(), roles:['analyst'], active:true });
  }
  hideSkillEditor(); skillRenderTable();
  mcFlashToast('Skill “'+name+'” saved.');
};
window.skillOpenToolPicker = function(){
  if(!editor) return;
  pickerSel = editor.draft.map(function(t){ return t.canonical; });
  skillRenderPicker();
  A('skill-tool-modal').classList.add('open');
};
window.skillCloseToolPicker = function(){ A('skill-tool-modal').classList.remove('open'); };
window.skillRenderPicker = function(){
  var locked = editor.draft.filter(function(t){ return t.server==='cc' && ccMode; });
  var html = '<div class="alert alert-info" style="margin-bottom:14px"><div>The grouped list under <b>Bound Tools</b> is both the display and the editor. Save sends the union of the selected ids; pinned entries are always included, so a save can never silently drop a dependency the caller cannot see.</div></div>';
  html += '<div class="form-group"><label>Filter by MCP Server</label><select class="form-control" onchange="skillPickerServer(this.value)">'
    + '<option value="">All servers</option>'
    + Object.keys(CATALOG).filter(function(sl){ return !(sl==='cc' && ccMode); }).map(function(sl){
        return '<option value="'+sl+'" '+(pickerServer===sl?'selected':'')+'>'+sl+'</option>';
      }).join('')+'</select></div>';
  Object.keys(CATALOG).forEach(function(sl){
    if(sl==='cc' && ccMode) return;
    if(pickerServer && pickerServer!==sl) return;
    html += '<div style="margin-bottom:12px"><span class="tool-group-label">'+E(SERVER_NAMES[sl])+'</span>';
    CATALOG[sl].forEach(function(t){
      html += '<label class="checkbox-item"><input type="checkbox" '+(pickerSel.indexOf(t.canonical)!==-1?'checked':'')+' onchange="skillPick(\''+t.canonical+'\',\''+sl+'\',\''+t.original+'\',this.checked)">'
        + '<span><code>'+E(t.original)+'</code> <span class="text-secondary" style="font-size:11px">'+E(t.canonical)+'</span>'
        + '<div class="text-sm text-secondary">'+E(t.desc)+'</div></span></label>';
    });
    html += '</div>';
  });
  if(locked.length){
    html += '<div style="margin-bottom:12px"><span class="tool-group-label" style="background:#FFF7ED;border-color:#FFE0B2;color:#C2410C">Referenced (read-only)</span>';
    locked.forEach(function(t){
      html += '<label class="checkbox-item"><input type="checkbox" checked disabled> <code>'+E(t.canonical)+'</code> <span class="text-sm text-secondary">'+E(t.serverName)+'</span> 🔒</label>';
    });
    html += '<div class="form-hint">Access to this tool requires the Control Center integration permission — shown read-only because this skill uses it.</div></div>';
  }
  A('skill-tool-picker-body').innerHTML = html;
};
window.skillPickerServer = function(v){ pickerServer = v||''; skillRenderPicker(); };
window.skillPick = function(canonical, server, original, checked){
  if(checked){ if(pickerSel.indexOf(canonical)===-1) pickerSel.push(canonical); }
  else pickerSel = pickerSel.filter(function(c){ return c!==canonical; });
};
window.skillConfirmPicker = function(){
  var pinned = editor.draft.filter(function(t){ return t.server==='cc' && ccMode; });
  var ids = pickerSel.slice();
  pinned.forEach(function(t){ if(ids.indexOf(t.canonical)===-1) ids.push(t.canonical); });
  var next = [];
  Object.keys(CATALOG).forEach(function(sl){
    CATALOG[sl].forEach(function(t){ if(ids.indexOf(t.canonical)!==-1) next.push(bind(sl, t.original)); });
  });
  editor.draft.forEach(function(t){ if(t.server==='cc' && ccMode && !next.some(function(n){return n.canonical===t.canonical;})) next.push(t); });
  editor.draft = next;
  skillCloseToolPicker(); skillRenderEditor();
};
window.skillAddFromAssistant = function(name, desc, toolNames, role){
  if(SKILLS.some(function(x){return x.name===name;})) return;
  var tools = [];
  toolNames.forEach(function(cn){
    var parts = cn.split('____');
    tools.push(bind(parts[0], parts[1]));
  });
  SKILLS.push({ name:name, desc:desc, tools:tools, roles:[role||'agent-skillful'], active:true });
  skillRenderTable();
};

skillRenderTable();
})();
/* ═══ CONTROL CENTER ASSISTANT (control-center-chatbot) — launcher, conversation, sessions, approval ═══ */
var ASST = {
  open:false, fullscreen:false, streaming:false, greeted:false,
  session:null, msgs:null, approval:null, forceNew:false,
  sessions:{ showEnded:false, page:1, from:'', to:'' }
};
var ASST_PAGE_SIZE = 10, ASST_WINDOW_DAYS = 7;
function asstEl(id){ return document.getElementById(id); }
function asstEsc(v){ return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function asstNow(){ var d=new Date(); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'); }
function asstAgo(days,hours){
  var t=new Date(Date.now()-((days*24+hours)*3600*1000));
  var p=function(n){return String(n).padStart(2,'0');};
  return t.getFullYear()+'-'+p(t.getMonth()+1)+'-'+p(t.getDate())+' '+p(t.getHours())+':'+p(t.getMinutes());
}
function asstToday(offsetDays){
  var t=new Date(Date.now()-(offsetDays||0)*24*3600*1000);
  var p=function(n){return String(n).padStart(2,'0');};
  return t.getFullYear()+'-'+p(t.getMonth()+1)+'-'+p(t.getDate());
}
function asstToast(msg,type){
  var t=document.createElement('div');
  t.textContent=msg;
  var bg = type==='success' ? '#1B5E20' : (type==='error' ? '#C62828' : '#1565C0');
  t.style.cssText='position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:'+bg+';color:#fff;padding:10px 18px;border-radius:6px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:9999';
  document.body.appendChild(t);
  setTimeout(function(){ t.style.opacity='0'; t.style.transition='opacity .3s ease'; setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); },350); },3200);
}

/* markdown → sanitised HTML (headings, bold, code, lists, GFM tables) */
function asstMd(src){
  var lines=String(src||'').split('\n'), out=[], i=0;
  function inline(v){
    return asstEsc(v)
      .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
      .replace(/`([^`]+)`/g,'<code>$1</code>')
      .replace(/\*([^*]+)\*/g,'<em>$1</em>');
  }
  while(i<lines.length){
    var line=lines[i];
    if(!line.trim()){ i++; continue; }
    if(/^\s*\|/.test(line) && i+1<lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i+1])){
      var head=line.trim().replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim();});
      i+=2; var body=[];
      while(i<lines.length && /^\s*\|/.test(lines[i])){
        body.push(lines[i].trim().replace(/^\||\|$/g,'').split('|').map(function(c){return c.trim();})); i++;
      }
      out.push('<table><thead><tr>'+head.map(function(h){return '<th>'+inline(h)+'</th>';}).join('')+'</tr></thead><tbody>'
        + body.map(function(r){return '<tr>'+r.map(function(c){return '<td>'+inline(c)+'</td>';}).join('')+'</tr>';}).join('')
        + '</tbody></table>');
      continue;
    }
    if(/^#{1,6}\s/.test(line)){ out.push('<h4>'+inline(line.replace(/^#{1,6}\s/,''))+'</h4>'); i++; continue; }
    if(/^\s*[-*]\s/.test(line)){
      var items=[];
      while(i<lines.length && /^\s*[-*]\s/.test(lines[i])){ items.push('<li>'+inline(lines[i].replace(/^\s*[-*]\s/,''))+'</li>'); i++; }
      out.push('<ul>'+items.join('')+'</ul>'); continue;
    }
    if(/^\s*\d+\.\s/.test(line)){
      var oitems=[];
      while(i<lines.length && /^\s*\d+\.\s/.test(lines[i])){ oitems.push('<li>'+inline(lines[i].replace(/^\s*\d+\.\s/,''))+'</li>'); i++; }
      out.push('<ol>'+oitems.join('')+'</ol>'); continue;
    }
    out.push('<p>'+inline(line)+'</p>'); i++;
  }
  return out.join('');
}

/* sessions (timestamps relative to now — the default 7-day window is always meaningful) */
var ASST_SESSIONS = [
  { id:'cs-204', title:'Skill & role setup',             status:'active',   updated:asstAgo(0,1) },
  { id:'cs-203', title:'Create triage skill',            status:'active',   updated:asstAgo(0,7) },
  { id:'cs-201', title:'Agent type for onboarding',      status:'active',   updated:asstAgo(1,3) },
  { id:'cs-198', title:'Grant SOP to analyst role',      status:'closed',   updated:asstAgo(2,6) },
  { id:'cs-196', title:'Which roles use slack-notify?',  status:'closed',   updated:asstAgo(2,12) },
  { id:'cs-193', title:'MCP server review',              status:'archived', updated:asstAgo(3,2) },
  { id:'cs-190', title:'Schedule cleanup (declined)',    status:'error',    updated:asstAgo(4,5) },
  { id:'cs-187', title:'Update model config',            status:'closed',   updated:asstAgo(4,10) },
  { id:'cs-185', title:'Data type for invoices',         status:'closed',   updated:asstAgo(5,9) },
  { id:'cs-182', title:'Role permission audit',          status:'closed',   updated:asstAgo(5,14) },
  { id:'cs-180', title:'Identity provisioning',          status:'closed',   updated:asstAgo(6,1) },
  { id:'cs-177', title:'SOP composition review',         status:'closed',   updated:asstAgo(6,8) },
  { id:'cs-175', title:'Bind slack tool to a skill',     status:'closed',   updated:asstAgo(6,17) },
  { id:'cs-172', title:'Which skills are unused?',       status:'closed',   updated:asstAgo(7,4) },
  { id:'cs-171', title:'Add identity for onboarding bot',status:'closed',   updated:asstAgo(7,9) }
];
var ASST_STATUS = { active:'Active', closed:'Closed', archived:'Archived', error:'Error' };
var ASST_RESUME_TURNS = [
  { role:'user', md:'Which roles can use slack-notify?' },
  { role:'agent', md:'**slack-notify** is granted to 2 roles:\n\n- `admin-user`\n- `agent-sop`\n\nIt wraps 1 tool: `slack____send_message`. Ask me to "grant slack-notify to analyst" and I will preview the change first.' }
];

/* ── open / close ── */
function asstModelConfigured(){
  var sel=asstEl('cfg-assistant-model');
  return !sel || !!sel.value;
}
function asstSyncModelHint(){
  var el=asstEl('cfg-assistant-model-state'); if(!el) return;
  el.style.color = asstModelConfigured() ? '#15803D' : '#B45309';
  el.textContent = asstModelConfigured()
    ? '✓ Configured — the assistant can converse in this workspace.'
    : '⚠️ Not configured — opening the assistant shows setup guidance and disables the input.';
}
function asstOnModelChange(){ asstSyncModelHint(); if(ASST.open) asstGate(); }
function asstSaveModel(){ asstSyncModelHint(); mcFlashToast(asstModelConfigured() ? 'Assistant model saved for this workspace.' : 'Assistant model cleared — the assistant will show setup guidance.'); }

function asstOpen(){
  var fab=asstEl('asst-fab');
  fab.classList.add('resolving'); fab.textContent='◌';
  setTimeout(function(){
    fab.classList.remove('resolving'); fab.textContent='🤖';
    ASST.open=true;
    asstEl('asst-overlay').classList.add('open');
    if(ASST.forceNew){
      ASST.forceNew=false; asstReset(true);
    }else if(!ASST.msgs){
      var active=ASST_SESSIONS.filter(function(x){return x.status==='active';}).sort(function(a,b){return a.updated<b.updated?1:-1;});
      ASST.session=active[0]||null;
      ASST.msgs=ASST_RESUME_TURNS.slice();
    }
    asstHeader(); asstGate(); asstRenderMessages(); asstActionBar();
    asstEl('asst-input').focus();
  },420);
}
function asstClose(quiet){
  ASST.open=false;
  ['asst-overlay','asst-preview-overlay','asst-sessions-overlay'].forEach(function(id){ var el=asstEl(id); if(el) el.classList.remove('open'); });
  if(!quiet && ASST.msgs && ASST.msgs.length){ asstToast('Exited — the session stays active. Reopening resumes it.'); }
}
function asstToggleFullscreen(){
  ASST.fullscreen=!ASST.fullscreen;
  asstEl('asst-dialog').classList.toggle('fullscreen',ASST.fullscreen);
}
function asstHeader(){
  var s=ASST.session;
  asstEl('asst-title').textContent=(s&&s.title)?s.title:'Control Center Assistant';
  var chip=asstEl('asst-conn-chip');
  var waiting=ASST.approval && !ASST.approval.resolved;
  chip.className='chip '+(waiting?'chip-yellow':'chip-green');
  chip.textContent=waiting?'Waiting for your input…':'Connected';
}
function asstGate(){
  var unconfigured=!asstModelConfigured();
  asstEl('asst-model-alert').style.display=unconfigured?'flex':'none';
  var interventionPending=!!(ASST.approval&&!ASST.approval.resolved);
  var inp=asstEl('asst-input'), send=asstEl('asst-send');
  inp.disabled=unconfigured||interventionPending;
  inp.placeholder=unconfigured?'Configure an assistant model to start chatting'
    :(interventionPending?'Waiting for the intervention response...':'Type a message… (Enter to send)');
  send.disabled=unconfigured||interventionPending;
}
function asstGoConfigure(){
  asstClose(true);
  showView('system-config');
  var sel=asstEl('cfg-assistant-model');
  if(sel){ sel.focus(); sel.style.boxShadow='0 0 0 3px var(--primary-light)'; setTimeout(function(){ sel.style.boxShadow=''; },1800); }
  asstToast('Select an assistant model for this workspace.');
}
function asstActionBar(){
  asstEl('asst-btn-new').disabled=ASST.streaming;
  asstEl('asst-btn-end').disabled=ASST.streaming;
}

/* ── messages ── */
function asstScroll(){ var m=asstEl('asst-messages'); if(m) m.scrollTop=m.scrollHeight; }
function asstRenderMessages(){
  var paper=asstEl('asst-messages'); paper.innerHTML='';
  if(!ASST.msgs || !ASST.msgs.length){
    var e=document.createElement('div'); e.className='asst-empty'; e.textContent='Send a message to begin the conversation.';
    paper.appendChild(e);
  }else{
    ASST.msgs.forEach(function(m){ asstAppend(m.role,m.md,m.time,true); });
  }
  asstScroll();
}
function asstAppend(role,md,time,skipStore){
  var paper=asstEl('asst-messages'); if(!paper) return null;
  var empty=paper.querySelector('.asst-empty'); if(empty) empty.remove();
  var el=document.createElement('div');
  el.className='msg msg-'+role;
  var av=role==='user'
    ? '<div style="width:28px;height:28px;border-radius:50%;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0">JD</div>'
    : '<div style="width:28px;height:28px;border-radius:50%;background:#E0E7FF;color:#4338CA;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0">🤖</div>';
  el.innerHTML=av+'<div style="min-width:0"><div class="msg-bubble">'
    +(role==='agent'?asstMd(md):asstEsc(md).replace(/\n/g,'<br>'))
    +'</div><div class="asst-time">'+asstEsc(time||asstNow())+'</div></div>';
  paper.appendChild(el);
  if(!skipStore) ASST.msgs.push({role:role,md:md,time:time||asstNow()});
  asstScroll();
  return el;
}
function asstUser(t){ asstAppend('user',t); }
function asstAgent(md){ asstAppend('agent',md); }
function asstTyping(){
  var paper=asstEl('asst-messages');
  var empty=paper.querySelector('.asst-empty'); if(empty) empty.remove();
  var el=document.createElement('div');
  el.className='msg msg-agent';
  el.innerHTML='<div style="width:28px;height:28px;border-radius:50%;background:#E0E7FF;color:#4338CA;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0">🤖</div>'
    +'<div class="msg-bubble"><span class="asst-typing"><span></span><span></span><span></span></span></div>';
  paper.appendChild(el); asstScroll(); return el;
}
function asstToolStep(text){
  var paper=asstEl('asst-messages');
  var el=document.createElement('div');
  el.className='asst-tool';
  el.innerHTML='<span class="asst-dot"></span><span>'+asstEsc(text)+'</span>';
  paper.appendChild(el); asstScroll(); return el;
}
function asstTypingThen(fn,delay){
  var el=asstTyping();
  setTimeout(function(){ el.remove(); fn(); }, delay||700);
}
function asstAutoGrow(t){ t.style.height='auto'; t.style.height=Math.min(t.scrollHeight,110)+'px'; }
function asstOnKey(e){ if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); asstSend(); } }
function asstSend(){
  var inp=asstEl('asst-input'); var text=inp.value.trim();
  if(!text||!asstModelConfigured()) return;
  if(ASST.streaming){ asstToast('The assistant is still working on the previous turn.'); return; }
  if(ASST.approval&&!ASST.approval.resolved) return;
  inp.value=''; asstAutoGrow(inp);
  asstUser(text); asstRoute(text);
}
/* ═══ CONTROL CENTER ASSISTANT — flows, sessions, approval (control-center-chatbot) ═══ */
function asstDetect(t){
  if(/\bagent type\b|\bagent-type\b/.test(t)) return 'agentType';
  if(/\bidentity\b/.test(t)) return 'identity';
  if(/\b(sop|runbook)\b/.test(t)) return 'sop';
  if(/\bskill\b/.test(t)) return 'skill';
  if(/\brole\b/.test(t)) return 'role';
  if(/\bmodel config\b/.test(t)) return 'modelConfig';
  if(/\bschedule\b|\bcron\b/.test(t)) return 'schedule';
  if(/\bmcp\b|\bconnection\b/.test(t)) return 'mcpHub';
  if(/\bdata type\b/.test(t)) return 'dataType';
  return null;
}
function asstName(text){
  var m=text.match(/called\s+["']?([\w\-\.@]+)/i)||text.match(/named\s+["']?([\w\-\.@]+)/i)||text.match(/["']([\w\-\.@]+)["']/);
  return m?m[1]:null;
}
function asstRoute(text){
  var t=text.toLowerCase();
  ASST.streaming=true; asstHeader(); asstGate(); asstActionBar();
  if(/\b(delete|remove|destroy|purge|erase)\b/.test(t)){ asstFlowDelete(asstDetect(t)); return; }
  if(/\b(api key|apikey|notification|webhook|system config|permission|tenant|platform)\b/.test(t)
     && !/\b(agent role|agent identity|agent type)\b/.test(t)){ asstFlowOutOfScope(); return; }
  if(/\b(update|change|rename|add the tool|bind|grant|reconfigure)\b/.test(t)){ asstFlowUpdate(asstDetect(t)||'skill', text); return; }
  if(/\b(create|add|new|configure|set up|make|provision)\b/.test(t)){
    var r=asstDetect(t);
    if(r){ asstFlowCreate(r, asstName(text), text); return; }
    asstFinish(function(){ asstAgent('What would you like to create? I can manage **skills, SOPs, agent types, roles, identities, model configs, schedules, MCP Hub connections** and **data types** — for example, *“create a skill called triage-inbox”*.'); });
    return;
  }
  if(/\b(list|show|which|describe|how many|what|who)\b/.test(t)){ asstFlowQuery(asstDetect(t)); return; }
  asstFinish(function(){ asstAgent('I manage the **Agents** menu. Try *“create a skill called triage-inbox”*, *“update slack-notify to bind the slack tool”*, or *“list agent types”*. I can create, update and query — but never delete.'); });
}
function asstFinish(fn){
  asstTypingThen(function(){
    fn();
    ASST.streaming=false; asstHeader(); asstGate(); asstActionBar();
  },750);
}
function asstFlowDelete(resKey){
  var labels={skill:'skills',sop:'SOPs',agentType:'agent types',role:'roles',identity:'identities',modelConfig:'model configs',schedule:'schedules',mcpHub:'MCP Hub connections',dataType:'data types'};
  asstFinish(function(){
    asstAgent('### 🚫 Deletion is not supported\n'
      +'I cannot delete **'+(resKey?(labels[resKey]||'resources'):'resources')+'**. No delete tool is registered on the MCP surface, so this is impossible rather than merely discouraged — it applies to skills, SOPs, agent types, roles, identities, model configs, schedules, MCP Hub connections and data types.\n\n'
      +'You can still deactivate an item from its editor, but I will not remove anything from the platform.');
  });
}
function asstFlowOutOfScope(){
  asstFinish(function(){
    asstAgent('### 🌐 Out of scope — not an Agents task\n'
      +'That request targets another module group (for example `integration::api_keys` or `system::*`).\n\n'
      +'My management scope is limited to the **Agents** menu (`agent::*`) plus MCP Hub connections (`integration::mcp_hub`). I decline the rest before any write.');
  });
}
function asstFlowQuery(resKey){
  asstFinish(function(){
    if(resKey==='skill'){
      asstAgent('**7 skills** in this workspace (1 system):\n\n'
        +'- **cc-management** — system · 2 tools\n- **read-analyze-file** — 2 tools\n- **github-pr-workflow** — 3 tools\n- **slack-notify** — 1 tool\n- **db-report** — no tools bound (inert)\n- **file-organizer** — 3 tools\n- **ops-escalation** — 1 tool');
    }else if(resKey==='role'){
      asstAgent('**Agent roles** in this workspace:\n\n- `admin-user` — full agent administration\n- `analyst` — read-only analysis\n- `agent-sop` — runs SOPs end to end\n- `agent-skillful` — generalist skill access\n- `auditor` — read-only audit trails');
    }else if(resKey==='agentType'){
      asstAgent('**Agent types**: support-agent (conversational), invoice-triage (typed), churn-analysis (typed), data-analyst, pr-reviewer, ops-assistant.\n\nAsk *“which roles does support-agent have?”* for detail.');
    }else{
      asstAgent('**Current Agents configuration**\n\n- Skills: 7 (1 system)\n- Agent types: 6\n- Agent roles: 5\n- MCP servers: 5 (1 system-managed)\n\nAsk me to *“list agent types”* or *“which roles can use slack-notify?”* for detail.');
    }
  });
}

/* ── create / update ── */
function asstPickTools(raw){
  var t=raw.toLowerCase(), out=[];
  if(/\bslack\b/.test(t)) out.push('slack____send_message');
  if(/\bgithub\b|\bissue\b|\bpull request\b/.test(t)) out.push('github____create_issue');
  if(/\bfile\b/.test(t)) out.push('filesystem____read_file');
  return out.length?out:['github____create_issue','slack____send_message'];
}
function asstFlowCreate(resKey,name,raw){
  var labels={skill:'Skill',sop:'SOP',agentType:'Agent Type',role:'Agent Role',identity:'Agent Identity',modelConfig:'Model Config',schedule:'Schedule',mcpHub:'MCP Hub connection',dataType:'Data Type'};
  if(!name){
    asstFinish(function(){ asstAgent('Sure — I can create a **'+labels[resKey]+'**. What should it be **called**?\n\nI resolve the platform model first: every field is previewed, and nothing is written until you approve.'); });
    return;
  }
  if(resKey!=='skill' && resKey!=='agentType'){
    asstFinish(function(){ asstAgent('I can manage **'+labels[resKey]+'** with the same contract: exact payload → field table preview → your approval → `invoke_management_tool`.\n\nThis mock demonstrates the **Skill** and **Agent Type** create flows end-to-end.'); });
    return;
  }
  var values;
  if(resKey==='skill'){
    var tools=asstPickTools(raw);
    values={ name:name, desc:'Route inbound support tickets by intent', tools:tools, role:'agent-skillful',
             workflow:'Use the bound tools to route inbound support tickets, then report the outcome.' };
    asstPresentApproval('create','skill',values,
      '**Create Skill: '+name+'**\n\n| Field | Value |\n| --- | --- |\n'
      +'| Name | `'+name+'` |\n| Description | '+values.desc+' |\n'
      +'| Tools | '+tools.map(function(x){return '`'+x+'`';}).join(', ')+' |\n'
      +'| Workflow | '+values.workflow+' |\n| Assigned role | `agent-skillful` |');
  }else{
    values={ name:name, kind:'Conversational', model:'gpt-4o', identity:'ops-assistant@agents', role:'agent-skillful', skills:'github-pr-workflow, read-analyze-file', maxIterations:24 };
    asstPresentApproval('create','agentType',values,
      '**Create Agent Type: '+name+'**\n\n| Field | Value |\n| --- | --- |\n'
      +'| Name | `'+name+'` |\n| Kind | Conversational |\n| Model | `gpt-4o` |\n'
      +'| Identity | `ops-assistant@agents` |\n| Role | `agent-skillful` |\n'
      +'| Skills granted | github-pr-workflow, read-analyze-file |\n| Max iterations | 24 |');
  }
}
function asstFlowUpdate(resKey,raw){
  if(resKey!=='skill'){
    asstFinish(function(){ asstAgent('Updates follow the same contract — only the **changed** fields are shown as *old → new*, then I wait for approval. This mock demonstrates the Skill update path: try *“update slack-notify to bind the slack tool”*.'); });
    return;
  }
  var target='slack-notify';
  ['read-analyze-file','github-pr-workflow','slack-notify','db-report','file-organizer','ops-escalation'].forEach(function(n){
    if(raw.toLowerCase().indexOf(n)!==-1) target=n;
  });
  if(/\bgrant\b|assign to role/.test(raw.toLowerCase())){
    asstPresentApproval('update','skill',{name:target,changes:[{field:'Granted roles',from:'admin-user, agent-sop',to:'admin-user, agent-sop, analyst'}]},
      '**Update Skill: '+target+'**\n\n| Field | Old | New |\n| --- | --- | --- |\n| Granted roles | admin-user, agent-sop | admin-user, agent-sop, analyst |');
    return;
  }
  asstPresentApproval('update','skill',{name:target,changes:[{field:'Tools',from:'(current bindings)',to:'slack____send_message, github____create_issue'},{field:'Workflow',from:'(current workflow)',to:'Updated to use the new tool set'}]},
    '**Update Skill: '+target+'**\n\n| Field | Old | New |\n| --- | --- | --- |\n| Tools | (current bindings) | `slack____send_message`, `github____create_issue` |\n| Workflow | (current workflow) | Updated to use the new tool set |');
}
function asstPresentApproval(mode,resKey,values,md){
  ASST.approval={mode:mode,resKey:resKey,values:values,md:md,resolved:false};
  var s1=asstToolStep('search_assistant_knowledge("confirmation-preview-format")');
  var s2=asstToolStep('get_management_tool_schema("'+(mode==='create'?'create_':'update_')+resKey+'")');
  setTimeout(function(){
    s1.classList.add('done'); s2.classList.add('done');
    var s3=asstToolStep('human_intervene(intervention_type="approval") — waiting for you');
    var card=document.createElement('div');
    card.className='asst-iv'; card.id='asst-approval-card';
    card.innerHTML='<div class="asst-iv-head"><span style="font-size:18px;color:#B45309">⚠️</span>'
      +'<div style="flex:1"><div class="asst-iv-title">Control Center Assistant requires your input</div>'
      +'<div class="asst-iv-sub">Sub-agent delegated by Control Center Assistant — depth 0</div>'
      +'<span class="chip chip-yellow" style="margin-top:5px;font-size:10px">Approval Required</span></div>'
      +'<button class="btn-icon" title="Expand" onclick="asstOpenPreview()">⤢</button></div>'
      +'<div class="asst-iv-body">'+asstMd(md)+'</div>'
      +'<div class="asst-iv-actions">'
      +'<button class="btn btn-sm" style="background:#16A34A;color:#fff;justify-content:center" onclick="asstResolve(true)">✓ Approve</button>'
      +'<button class="btn btn-sm" style="background:#fff;border:1px solid #FECACA;color:#B91C1C;justify-content:center" onclick="asstResolve(false)">✕ Deny</button>'
      +'</div>'
      +'<div class="asst-iv-dismiss"><button onclick="asstDismiss()">Dismiss / Cancel</button></div>';
    asstEl('asst-messages').appendChild(card);
    ASST.approval.stepEl=s3;
    asstScroll(); asstHeader(); asstGate(); asstActionBar();
  },900);
}
function asstOpenPreview(){
  if(!ASST.approval) return;
  asstEl('asst-preview-body').innerHTML=asstMd(ASST.approval.md);
  asstEl('asst-preview-overlay').classList.add('open');
}
function asstClosePreview(){ asstEl('asst-preview-overlay').classList.remove('open'); }
function asstDismiss(){
  if(!ASST.approval||ASST.approval.resolved) return;
  var step=ASST.approval.stepEl;
  if(step){ step.classList.add('done'); step.innerHTML='<span class="asst-dot"></span><span>human_intervene — dismissed (operation NOT executed)</span>'; }
  var card=asstEl('asst-approval-card'); if(card) card.remove();
  ASST.approval=null;
  asstFinish(function(){ asstAgent('Dismissed — **nothing was written**. Tell me what to change, or ask for something else.'); });
}
function asstResolve(approve){
  var ap=ASST.approval; if(!ap||ap.resolved) return;
  ap.resolved=true; asstClosePreview();
  var card=asstEl('asst-approval-card'), step=ap.stepEl;
  if(!approve){
    if(step){ step.classList.add('done'); step.innerHTML='<span class="asst-dot"></span><span>human_intervene → denied (operation NOT executed)</span>'; }
    if(card){
      card.querySelector('.asst-iv-body').innerHTML='<div style="font-size:12.5px;color:#B91C1C;font-weight:600">✕ Denied — no write was performed.</div>';
      var acts=card.querySelector('.asst-iv-actions'); if(acts) acts.remove();
      var dis=card.querySelector('.asst-iv-dismiss'); if(dis) dis.remove();
    }
    ASST.approval=null; ASST.streaming=false;
    asstHeader(); asstGate(); asstActionBar();
    asstTypingThen(function(){ asstAgent('No changes were made. Which value should be different? I will rebuild the preview — for example *“use the skill name triage-inbox-v2”* or *“only bind slack”*.'); },400);
    return;
  }
  if(step){ step.classList.add('done'); step.innerHTML='<span class="asst-dot"></span><span>human_intervene → approved</span>'; }
  var exec=asstToolStep('invoke_management_tool("'+(ap.mode==='create'?'create_':'update_')+ap.resKey+'", payload)');
  setTimeout(function(){
    exec.classList.add('done');
    exec.innerHTML='<span class="asst-dot"></span><span>✓ '+(ap.mode==='create'?'create_':'update_')+ap.resKey+' → 200 OK (permission re-checked)</span>';
    var v=ap.values;
    if(ap.resKey==='skill' && ap.mode==='create'){
      skillAddFromAssistant(v.name, v.desc, v.tools, v.role);
      asstAgent('### ✓ Skill “'+v.name+'” saved\n'
        +'- **Name**: `'+v.name+'`\n- **Tools**: '+v.tools.map(function(x){return '`'+x+'`';}).join(', ')+'\n- **Assigned role**: `'+v.role+'`\n\n'
        +'Attributed to you — the audit trail records your identity, not a service account.');
      var row=document.createElement('div');
      row.style.cssText='display:flex;gap:8px;margin-left:36px';
      row.innerHTML='<button class="btn btn-primary btn-sm" onclick="asstGotoSkills(\''+asstEsc(v.name)+'\')">Open in Skills →</button>'
        +'<span class="text-sm text-secondary" style="align-self:center">Row updates without a page reload</span>';
      asstEl('asst-messages').appendChild(row);
      asstToast('Skill “'+v.name+'” created.','success');
    }else if(ap.resKey==='skill' && ap.mode==='update'){
      asstAgent('### ✓ Skill “'+v.name+'” updated\n'+v.changes.map(function(c){return '- **'+c.field+'**: '+c.to;}).join('\n')
        +'\n\nAttributed to you — the audit trail records your identity, not a service account.');
      asstToast('Skill “'+v.name+'” updated.','success');
    }else if(ap.resKey==='agentType' && ap.mode==='create'){
      asstAgent('### ✓ Agent Type “'+v.name+'” created\n'
        +'- **Kind**: '+v.kind+'\n- **Model**: `'+v.model+'`\n- **Identity**: `'+v.identity+'`\n- **Role**: `'+v.role+'`\n'
        +'- **Skills granted**: '+v.skills+'\n- **Max iterations**: '+v.maxIterations+'\n\n'
        +'An agent type is only created when it has a working model plus an identity or a role — this one satisfies both.');
      asstToast('Agent Type “'+v.name+'” created.','success');
    }
    if(card) card.remove();
    ASST.approval=null; ASST.streaming=false;
    asstScroll(); asstHeader(); asstGate(); asstActionBar();
  },900);
}
function asstGotoSkills(name){
  asstClose(true); showView('skills');
  var row=asstEl('row-skill-'+name);
  if(row){ row.scrollIntoView({behavior:'smooth',block:'center'}); row.classList.remove('flash'); void row.offsetWidth; row.classList.add('flash'); }
}

/* ── session lifecycle ── */
function asstReset(isNew){
  ASST.msgs=[]; ASST.approval=null; ASST.streaming=false;
  if(isNew) ASST.session={ id:'cs-new-'+Date.now(), title:null, status:'active', updated:'' };
  asstEl('asst-preview-overlay').classList.remove('open');
  asstHeader(); asstGate(); asstRenderMessages(); asstActionBar();
}
function asstNewSession(){
  if(ASST.streaming){ asstToast('Wait for the current turn to finish.'); return; }
  asstReset(true);
  asstToast('New session started — the previous session stays active.','success');
}
function asstOpenEnd(){ if(ASST.streaming){ asstToast('End the in-flight turn first.'); return; } asstEl('asst-end-overlay').classList.add('open'); }
function asstCloseEnd(){ asstEl('asst-end-overlay').classList.remove('open'); }
function asstConfirmEnd(){
  if(ASST.session&&ASST.session.id){
    ASST_SESSIONS.forEach(function(x){ if(x.id===ASST.session.id) x.status='closed'; });
  }
  ASST.forceNew=true; asstCloseEnd(); asstClose(true);
  asstToast('Session ended — the next open starts a new session.','success');
}
function asstOpenSessions(){
  var d=ASST.sessions;
  if(!d.from){ d.from=asstToday(ASST_WINDOW_DAYS); d.to=asstToday(0); }
  asstEl('asst-sess-from').value=d.from;
  asstEl('asst-sess-to').value=d.to;
  asstEl('asst-show-ended').checked=d.showEnded;
  d.page=1; asstRenderSessions();
  asstEl('asst-sessions-overlay').classList.add('open');
}
function asstCloseSessions(){ asstEl('asst-sessions-overlay').classList.remove('open'); }
function asstShowEnded(v){ ASST.sessions.showEnded=v; ASST.sessions.page=1; asstRenderSessions(); }
function asstDateChange(){
  ASST.sessions.from=asstEl('asst-sess-from').value;
  ASST.sessions.to=asstEl('asst-sess-to').value;
  ASST.sessions.page=1; asstRenderSessions();
}
function asstPage(p){ ASST.sessions.page=p; asstRenderSessions(); }
function asstFiltered(){
  var d=ASST.sessions, from=d.from||'0000-01-01', to=d.to||'9999-12-31';
  return ASST_SESSIONS.filter(function(x){
    if(!d.showEnded && x.status!=='active') return false;
    var day=x.updated.slice(0,10);
    return day>=from && day<=to;
  }).sort(function(a,b){ return a.updated<b.updated?1:-1; });
}
function asstRenderSessions(){
  var d=ASST.sessions, rows=asstFiltered();
  var pages=Math.max(1,Math.ceil(rows.length/ASST_PAGE_SIZE));
  if(d.page>pages) d.page=pages;
  var start=(d.page-1)*ASST_PAGE_SIZE;
  var pageRows=rows.slice(start,start+ASST_PAGE_SIZE);
  asstEl('asst-sessions-list').innerHTML = pageRows.length===0
    ? '<div class="text-secondary" style="text-align:center;padding:24px;font-size:13px">No conversation sessions yet. Start one to begin.</div>'
    : pageRows.map(function(x){
        var ended=x.status!=='active';
        var current=ASST.session&&x.id===ASST.session.id;
        var right=ended?'<span class="chip chip-gray" style="font-size:10px">Ended</span>'
          :(current?'<span class="chip chip-blue" style="font-size:10px">Current</span>'
          :'<button class="btn btn-xs btn-secondary" onclick="asstResume(\''+x.id+'\')">Resume</button>');
        return '<div class="asst-sess-row'+(current?' current':'')+'"><div class="asst-sess-main">'
          +'<div class="asst-sess-title">'+(x.title?asstEsc(x.title):'<em class="text-secondary">Untitled session</em>')+'</div>'
          +'<div class="asst-sess-meta">'+asstEsc(ASST_STATUS[x.status]||x.status)+' · '+asstEsc(x.updated)+'</div></div>'
          +right+'</div>';
      }).join('');
  var pager='<button class="asst-pager-btn" onclick="asstPage('+Math.max(1,d.page-1)+')" '+(d.page===1?'disabled':'')+'>‹</button>';
  for(var i=1;i<=pages;i++){ pager+='<button class="asst-pager-btn'+(i===d.page?' active':'')+'" onclick="asstPage('+i+')">'+i+'</button>'; }
  pager+='<button class="asst-pager-btn" onclick="asstPage('+Math.min(pages,d.page+1)+')" '+(d.page===pages?'disabled':'')+'>›</button>';
  asstEl('asst-sessions-pager').innerHTML=pager;
}
function asstResume(id){
  if(ASST.streaming){ asstToast('Wait for the current turn to finish.'); return; }
  var target=ASST_SESSIONS.filter(function(x){return x.id===id;})[0];
  if(!target||target.status!=='active'){ asstToast('Ended sessions can be viewed but not resumed.'); return; }
  asstCloseSessions();
  ASST.session=target;
  ASST.msgs=[
    { role:'user', md:'Continue from this session.' },
    { role:'agent', md:'**Resumed “'+(target.title||'Untitled session')+'”.** Persisted turns are restored from this session — the previous session stays active, nothing is ended or archived.\n\nWhat would you like to do next?' }
  ];
  ASST.approval=null;
  asstHeader(); asstRenderMessages(); asstActionBar();
  asstToast('Resumed “'+(target.title||target.id)+'”.');
}
asstSyncModelHint();

/* The assistant only exists inside the signed-in app shell — hide the launcher while the
   login page is on screen (the master mock opens on the login page by default). */
function asstSyncChrome(){
  var lp=document.getElementById('login-page');
  var signedIn = !lp || lp.style.display==='none' || getComputedStyle(lp).display==='none';
  var fab=document.getElementById('asst-fab');
  if(fab) fab.style.display = signedIn ? 'flex' : 'none';
  if(!signedIn && ASST.open) asstClose(true);
}
(function(){
  var fab=document.getElementById('asst-fab');
  if(fab) fab.classList.add('left-of-demo');   /* dashboard is the initial view */
  var lp=document.getElementById('login-page');
  if(lp && window.MutationObserver){ new MutationObserver(asstSyncChrome).observe(lp,{attributes:true,attributeFilter:['style']}); }
  asstSyncChrome();
})();

// ═══════════════════════════════ AGENT CLIENT (third-party-agent-integration) ═══════════════════════════════
function acOpen(id){ document.getElementById(id).classList.add('open'); }
function acClose(id){ document.getElementById(id).classList.remove('open'); }
function acCloseIfOverlay(e,id){ if(e.target===e.currentTarget) acClose(id); }
var AC_TYPES = [
  {id:'support-conversational', kind:'conversation'},
  {id:'inbox-triage', kind:'typed'},
  {id:'knowledge-base', kind:'conversation'},
  {id:'pr-reviewer', kind:'typed'}
];
var AC_CLIENTS = [
  {id:1, name:'Acme Support Bot', hint:'phn_cl_pk_acme', agent:'support-conversational', keyType:'publishable', origins:'https://acme.com', rate:'100 / min', status:'active'},
  {id:2, name:'Nimbus Classifier', hint:'phn_cl_sk_nimbus', agent:'inbox-triage', keyType:'secret', origins:'https://nimbus.io', rate:'500 / min', status:'active'}
];
var acCreateAgent = '', acEditId = null;

function atdTab(tabEl, panelId) {
  // Scoped tab switcher for the Agent Type Details modal (modal is outside .view)
  var modal = document.getElementById('agentTypeDetailsModal');
  modal.querySelectorAll('.tabs .tab').forEach(function(t){ t.classList.remove('active'); });
  tabEl.classList.add('active');
  modal.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.remove('active'); });
  var panel = document.getElementById(panelId);
  if (panel) panel.classList.add('active');
}

function acChip(kind){ return '<span class="chip ' + (kind==='secret'?'chip-purple':'chip-blue') + '">' + kind + '</span>'; }
function acStatusChip(s){
  return s==='active' ? '<span class="chip chip-green"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#22C55E;margin-right:6px"></span>Active</span>'
                      : '<span class="chip chip-gray"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#94A3B8;margin-right:6px"></span>Inactive</span>';
}
function acRenderTable(){
  var tb = document.getElementById('acTbody');
  if (!tb) return;
  tb.innerHTML = '';
  AC_CLIENTS.forEach(function(c){
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><strong>' + c.name + '</strong><br><span class="font-mono text-xs" style="color:var(--text-secondary)">' + c.hint + '…</span></td>' +
      '<td><span class="chip chip-gray font-mono">' + c.agent + '</span></td>' +
      '<td>' + acChip(c.keyType) + '</td>' +
      '<td class="text-sm">' + c.origins.replace(/\n/g,'<br>') + '</td>' +
      '<td>' + c.rate + '</td>' +
      '<td>' + acStatusChip(c.status) + '</td>' +
      '<td class="actions-cell">' +
        '<button class="btn btn-xs btn-secondary" onclick="acOpenEdit(' + c.id + ')">Edit</button>' +
        '<button class="btn btn-xs btn-secondary" onclick="acToggle(' + c.id + ')">' + (c.status==='active'?'Deactivate':'Activate') + '</button>' +
        '<button class="btn btn-xs btn-danger" onclick="acRemove(' + c.id + ')">Remove</button>' +
      '</td>';
    tb.appendChild(tr);
  });
  acRenderAtdClients();
}
function acRenderAtdClients(){
  var tb = document.getElementById('atdAcTbody');
  if (!tb) return;
  var agent = document.querySelector('#agentTypeDetailsModal .modal-header h3').textContent.replace('Agent Type: ','');
  var mine = AC_CLIENTS.filter(function(c){ return c.agent === agent; });
  tb.innerHTML = '';
  if (!mine.length){ tb.innerHTML = '<tr><td colspan="6" class="text-secondary">No clients for this agent type yet.</td></tr>'; return; }
  mine.forEach(function(c){
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td><strong>' + c.name + '</strong></td>' +
      '<td>' + acChip(c.keyType) + '</td>' +
      '<td class="text-sm">' + c.origins.replace(/\n/g,'<br>') + '</td>' +
      '<td>' + c.rate + '</td>' +
      '<td>' + acStatusChip(c.status) + '</td>' +
      '<td class="actions-cell"><button class="btn btn-xs btn-secondary" onclick="acOpenEdit(' + c.id + ')">Edit</button></td>';
    tb.appendChild(tr);
  });
}
function acToggle(id){
  var c = AC_CLIENTS.find(function(x){ return x.id===id; });
  c.status = c.status==='active' ? 'inactive' : 'active';
  acRenderTable();
  showToast(c.status==='active' ? '✓ "'+c.name+'" activated — credential works again' : '🔒 "'+c.name+'" deactivated — credential immediately unusable (reversible)');
}
function acRemove(id){
  var c = AC_CLIENTS.find(function(x){ return x.id===id; });
  if (!confirm('Remove "'+c.name+'" permanently? The credential and its audit trail are deleted. This cannot be undone.')) return;
  AC_CLIENTS = AC_CLIENTS.filter(function(x){ return x.id!==id; });
  acRenderTable();
  showToast('🗑️ "'+c.name+'" removed — credential and audit trail deleted');
}
// Create dialog
function acOpenCreate(preset){
  acCreateAgent = preset || '';
  document.getElementById('acName').value = '';
  document.getElementById('acAgent').value = acCreateAgent;
  document.getElementById('acOrigins').value = '';
  document.getElementById('acRate').value = 100;
  document.getElementById('acKeyType').value = 'secret';
  acOnKeyType();
  acOpen('acCreateModal');
  acValidateCreate();
}
function acFilterTypes(){
  var q = document.getElementById('acAgent').value.toLowerCase();
  var list = document.getElementById('acAgentList');
  list.style.display = 'block';
  list.innerHTML = '';
  list.style.cssText = 'position:absolute;z-index:60;background:#fff;border:1px solid var(--border);border-radius:var(--radius-sm);box-shadow:var(--shadow-md);max-height:180px;overflow-y:auto';
  AC_TYPES.filter(function(a){ return a.id.toLowerCase().indexOf(q) !== -1; }).forEach(function(a){
    var d = document.createElement('div');
    d.style.cssText = 'padding:8px 12px;font-size:13px;cursor:pointer;display:flex;justify-content:space-between';
    d.innerHTML = '<span>' + a.id + '</span><span class="chip chip-gray">' + a.kind + '</span>';
    d.onmouseover = function(){ d.style.background = 'var(--primary-light)'; };
    d.onmouseout = function(){ d.style.background = ''; };
    d.onclick = function(){ acCreateAgent = a.id; document.getElementById('acAgent').value = a.id; list.style.display='none'; acValidateCreate(); };
    list.appendChild(d);
  });
}
document.addEventListener('click', function(e){
  if (!e.target.closest || !e.target.closest('#acAgent, #acAgentList')) {
    var l = document.getElementById('acAgentList'); if (l) l.style.display='none';
  }
});
function acOnKeyType(){
  var pub = document.getElementById('acKeyType').value === 'publishable';
  document.getElementById('acPubWarn').style.display = pub ? 'block' : 'none';
  acValidateCreate();
}
function acValidateCreate(){
  var pub = document.getElementById('acKeyType').value === 'publishable';
  var origins = document.getElementById('acOrigins').value.trim();
  var ok = acCreateAgent && document.getElementById('acName').value.trim() && (!pub || origins.length > 0);
  document.getElementById('acSaveBtn').disabled = !ok;
  document.getElementById('acOriginWarn').style.display = (pub && origins.length===0) ? 'block' : 'none';
}
function acSaveCreate(){
  var name = document.getElementById('acName').value.trim();
  var pub = document.getElementById('acKeyType').value === 'publishable';
  var key = 'phn_cl_' + (pub ? 'pk_' : 'sk_') + name.toLowerCase().replace(/[^a-z0-9]+/g,'').slice(0,8);
  AC_CLIENTS.push({id:Date.now(), name:name, hint:key, agent:acCreateAgent, keyType:pub?'publishable':'secret',
    origins:document.getElementById('acOrigins').value.trim(),
    rate:document.getElementById('acRate').value + ' / ' + document.getElementById('acRateWindow').value.replace('per ',''), status:'active'});
  acRenderTable();
  acClose('acCreateModal');
  document.getElementById('acCredName').textContent = name;
  document.getElementById('acCredValue').textContent = key + '_' + Math.random().toString(36).slice(2,14);
  document.getElementById('acCredPubWarn').style.display = pub ? 'block' : 'none';
  acOpen('acCredModal');
  showToast('✓ Client "'+name+'" created');
}
function acCopyCred(){
  var v = document.getElementById('acCredValue').textContent;
  if (navigator.clipboard) navigator.clipboard.writeText(v).catch(function(){});
  showToast('📋 Credential copied to clipboard');
}
// Edit dialog
function acOpenEdit(id){
  var c = AC_CLIENTS.find(function(x){ return x.id===id; }); if (!c) return;
  acEditId = id;
  document.getElementById('aceName').textContent = c.name;
  document.getElementById('aceAgent').value = c.agent;
  document.getElementById('aceKeyType').value = c.keyType;
  document.getElementById('aceOrigins').value = c.origins;
  document.getElementById('aceRate').value = parseInt(c.rate);
  document.getElementById('aceRateWindow').value = 'per ' + c.rate.split(' / ')[1];
  acOpen('acEditModal');
}
function acSaveEdit(){
  var c = AC_CLIENTS.find(function(x){ return x.id===acEditId; });
  var origins = document.getElementById('aceOrigins').value.trim();
  if (c.keyType==='publishable' && !origins){
    document.getElementById('aceOriginWarn').style.display='block'; return;
  }
  document.getElementById('aceOriginWarn').style.display='none';
  c.origins = origins;
  c.rate = document.getElementById('aceRate').value + ' / ' + document.getElementById('aceRateWindow').value.replace('per ','');
  acRenderTable();
  acClose('acEditModal');
  showToast('✓ "'+c.name+'" updated — origins and rate limit only');
}
// Stateful widget chat
var acSessionOn = false, acMsgIdx = 0;
var AC_REPLIES = [
  'Thanks for reaching out! I can help with order issues, returns, and account questions.',
  'I found your account. Here is a summary of your recent orders:<br><table style="border-collapse:collapse;margin:6px 0;font-size:12.5px"><tr><th style="border:1px solid #E9E2F7;padding:5px 9px">Order</th><th style="border:1px solid #E9E2F7;padding:5px 9px">Item</th><th style="border:1px solid #E9E2F7;padding:5px 9px">Status</th></tr><tr><td style="border:1px solid #E9E2F7;padding:5px 9px">#1234</td><td style="border:1px solid #E9E2F7;padding:5px 9px">Laptop</td><td style="border:1px solid #E9E2F7;padding:5px 9px">Delivered Oct 28</td></tr><tr><td style="border:1px solid #E9E2F7;padding:5px 9px">#1239</td><td style="border:1px solid #E9E2F7;padding:5px 9px">Mouse</td><td style="border:1px solid #E9E2F7;padding:5px 9px">In transit</td></tr></table>Which order do you need help with?',
  'I\u2019ve initiated a return for order <strong>#1234</strong>. Your return details:<br><pre class="font-mono text-xs" style="background:#1E293B;color:#E2E8F0;border-radius:6px;padding:10px;overflow-x:auto">{\n  "return_id": "ret_8841",\n  "refund_amount": 1299.00,\n  "currency": "USD",\n  "label_delivery": "email within 5 minutes"\n}</pre>',
  'Anything else I can help you with?'
];
function acAddBot(html){
  var body = document.getElementById('acChatBody');
  var m = document.createElement('div');
  m.style.cssText = 'max-width:82%;padding:9px 13px;border-radius:14px;background:#fff;border:1px solid #E9E2F7;border-top-left-radius:4px;align-self:flex-start;font-size:13.5px;line-height:1.45';
  m.innerHTML = html;
  body.appendChild(m); body.scrollTop = body.scrollHeight;
}
function acStartSession(){
  acSessionOn = true; acMsgIdx = 0;
  document.getElementById('acSessionChip').innerHTML = '<span style="color:#15803D;font-weight:600">● Session conv_8f3a21</span> — context shared across messages';
  document.getElementById('acBtnStart').disabled = true;
  document.getElementById('acBtnEnd').disabled = false;
  document.getElementById('acChatInput').disabled = false;
  document.getElementById('acChatSend').disabled = false;
  document.getElementById('acChatInput').placeholder = 'Type a message…';
  acAddBot('Session started. You can send multiple messages — I remember the full conversation context.');
  showToast('▶ Conversation session started');
}
function acEndSession(){
  acSessionOn = false;
  document.getElementById('acSessionChip').textContent = '● No session';
  document.getElementById('acBtnStart').disabled = false;
  document.getElementById('acBtnEnd').disabled = true;
  document.getElementById('acChatInput').disabled = true;
  document.getElementById('acChatSend').disabled = true;
  document.getElementById('acChatInput').value = '';
  document.getElementById('acChatInput').placeholder = 'Start a session to begin chatting…';
  acAddBot('Session ended. Context cleared — start a new session anytime.');
  showToast('■ Session ended');
}
function acSendChat(){
  var inp = document.getElementById('acChatInput');
  var body = document.getElementById('acChatBody');
  var text = inp.value.trim();
  if (!text || !acSessionOn) return;
  var um = document.createElement('div');
  um.style.cssText = 'max-width:82%;padding:9px 13px;border-radius:14px;background:#6D28D9;color:#fff;border-top-right-radius:4px;align-self:flex-end;font-size:13.5px';
  um.textContent = text;
  body.appendChild(um);
  inp.value = '';
  var typing = document.createElement('div');
  typing.style.cssText = 'color:var(--text-secondary);font-size:12.5px;font-style:italic';
  typing.textContent = 'Acme Support Bot is typing…';
  body.appendChild(typing); body.scrollTop = body.scrollHeight;
  setTimeout(function(){
    typing.remove();
    acAddBot(AC_REPLIES[Math.min(acMsgIdx, AC_REPLIES.length-1)]);
    if (acMsgIdx < AC_REPLIES.length-1) acMsgIdx++;
  }, 900);
}
// Server-side flow sim
function acRunServer(){
  var out = document.getElementById('acServerResult');
  out.innerHTML = '<div class="text-sm text-secondary" style="margin-top:14px;font-style:italic">Agent executing…</div>';
  setTimeout(function(){
    out.innerHTML = '<div style="border:1px solid #B7E4C7;background:#F0F9F4;border-radius:var(--radius);padding:14px;margin-top:14px"><div class="text-xs" style="font-weight:700;color:#15803D;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Valid · typed response (AgentOutput)</div><pre class="font-mono text-xs" style="white-space:pre">{\n  "validation_status": "valid",\n  "output_type": "TriageResult",\n  "data": {\n    "category": "refund_request",\n    "confidence": 0.94,\n    "priority": "high",\n    "sentiment": "negative",\n    "suggested_action": "issue_refund"\n  },\n  "session_id": "sess_5c2f9e"\n}</pre></div>';
  }, 1100);
}
acRenderTable();