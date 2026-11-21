/* Parthenon UX prototype — shared behaviour (relocated verbatim from the single-file prototype) */
// ═══════════════════════════════ STATE ═══════════════════════════════
var currentView = 'dashboard';
var wizardStep = 1;
var sopStepCount = 3;

// ═══════════════════════════════ NAV ═══════════════════════════════
const viewTitles = {
  'dashboard': 'Dashboard',
  'setup-wizard': 'Setup Wizard',
  'mcp-hub': 'MCP Hub',
  'skills': 'Skills',
  'sops': 'Standard Operating Procedures',
  'agents': 'Agent Types',
  'agent-management-panel': 'Agent Management Panel',
  'gateway': 'Gateway',
  'schedules': 'Schedules',
  'notifications': 'Notification Integration',
  'observability': 'Observability',
  'security-audit': 'Service Segregation Security Audit',
  'chat': 'Communication Hub',
  'conversations': 'Conversations',
  'results': 'Results',
  'permissions': 'Permissions & Access',
  'model-configs': 'Model Configs',
  'agent-roles': 'Agent Roles',
  'agent-identities': 'Agent Identities',
  'agent-executions': 'Agent Executions',
  'agent-logs': 'Agent Logs',
  'runtime-monitor': 'Agent Runtime Monitor',
  'agent-trails': 'Agent Trails',
  'system-config': 'System Config',
  'sysone-providers': 'System One Providers',
  'conversational-intervention': 'Conversational Agent Intervention',
  'intervene-requests': 'Intervene Requests',
  'data-types': 'Agent Data Types',
  'decision-tools': 'Decision Tools',
  'agent-outputs': 'Agent Outputs',
  'project-showcase': 'Project Showcase',
  'api-keys': 'API Key Management',
  'agent-clients': 'Agent Client',
  'tenant-settings': 'Tenant Settings',
  'tenant-members': 'Members',
  'tenant-identity-providers': 'Identity Providers',
  'platform-settings': 'Platform Settings',
  'platform-tenants': 'Tenants',
  'platform-audit': 'Tenant Security Audit'
};


    function toggleNavGroup(el) {
        const group = el.closest('.nav-parent-group');
        if (!group) return;
        // Locked-open groups cannot be toggled
        if (group.classList.contains('locked-open')) return;
        group.classList.toggle('collapsed');
        el.setAttribute('aria-expanded', !group.classList.contains('collapsed'));
    }
    
    function openAgentDetails(agentType) {
        openModal('agentTypeDetailsModal');
    }
    function openExecutionDetails() {
        openModal('executionDetailsModal');
    }
    function openRoleView() {
        openModal('roleViewModal');
    }
    function openIdentityView() {
        openModal('identityViewModal');
    }
    function openAllExecutions() {
        closeModal('agentTypeDetailsModal');
        const event = new Event('click');
        document.querySelector('[data-view="agent-executions"]').dispatchEvent(event);
        document.querySelector('[data-view="agent-executions"]').click();
    }

    function nav(el, viewId) {
  showView(viewId);
  // Update active nav item
  document.querySelectorAll('.nav-item').forEach(function(item) {
    item.classList.remove('active');
  });
  // Update parent group active state
  document.querySelectorAll('.nav-parent-group').forEach(function(g) {
    g.classList.remove('active');
  });
  if (el && el.classList) {
    el.classList.add('active');
    // Mark parent group as active
    const parentGroup = el.closest('.nav-parent-group');
    if (parentGroup) parentGroup.classList.add('active');
  } else {
    // Find nav item by data-view
    var items = document.querySelectorAll('.nav-item[data-view="' + viewId + '"]');
    if (items.length) {
      items[0].classList.add('active');
      const parentGroup = items[0].closest('.nav-parent-group');
      if (parentGroup) parentGroup.classList.add('active');
    }
  }
}

function showView(viewId) {
  document.querySelectorAll('.view').forEach(function(v) {
    v.classList.remove('active');
  });
  var target = document.getElementById('view-' + viewId);
  if (target) {
    target.classList.add('active');
    currentView = viewId;
    document.getElementById('topbar-title').textContent = viewTitles[viewId] || viewId;
  }
  // Scroll main content to top
  var mc = document.querySelector('.main-content');
  if (mc) mc.scrollTop = 0;
  // Dashboard demo controls only apply to the dashboard — and must not cover the assistant launcher
  var dashPanel = document.getElementById('dash-demo-panel');
  if (dashPanel) dashPanel.style.display = (viewId === 'dashboard') ? '' : 'none';
  var asstFab = document.getElementById('asst-fab');
  if (asstFab) asstFab.classList.toggle('left-of-demo', viewId === 'dashboard');
}

function toggleGroup(groupId) {
  var grp = document.getElementById(groupId);
  if (grp) grp.classList.toggle('collapsed');
}

function toggleParentGroup(pgId) {
  var pg = document.getElementById(pgId);
  if (pg) pg.classList.toggle('collapsed');
}

// ═══════════════════════════════ MODALS ═══════════════════════════════
function openModal(modalId) {
  var modal = document.getElementById(modalId);
  if (modal) modal.classList.add('open');
}

function closeModal(modalId) {
  var modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('open');
}

function closeModalIfOverlay(event, modalId) {
  if (event.target === event.currentTarget) closeModal(modalId);
}

// ═══════════════════════════════ MCP HUB ═══════════════════════════════
var MCP_SESSIONS = {
  'filesystem': [
    { id:'fs1', name:'Production File Access', auth_type:'api_key', is_active:true, is_default:true, description:'Production environment file tools' },
    { id:'fs2', name:'Staging File Access', auth_type:'api_key', is_active:true, is_default:false, description:'' },
    { id:'fs3', name:'Passthrough Agent', auth_type:'passthrough', is_active:true, is_default:false, description:'Forward agent identity JWT' }
  ],
  'github': [],
  'slack-tools': [
    { id:'sl1', name:'Slack Webhook', auth_type:'bearer_token', is_active:true, is_default:true, description:'' },
    { id:'sl2', name:'Slack OAuth', auth_type:'oauth2', is_active:true, is_default:false, description:'OAuth-based Slack access' },
    { id:'sl3', name:'Slack OAuth — Reporting', auth_type:'oauth2', is_active:true, is_default:false, description:'Read-only analytics scope' },
    { id:'sl4', name:'Slack OAuth — Incident Channel', auth_type:'oauth2', is_active:true, is_default:false, description:'Paging integration for the incident channel',
      requires_reauth:true, last_refresh_error:'No such refresh token found' }
  ]
};

/* OAuth timestamps are anchored to "now" so the prototype always shows all three token
   states regardless of when it is opened:
     sl2 — healthy (access +34h, refresh +26d)      → "Valid (34h)" + green refresh action
     sl3 — access AND refresh expired (-6h / -2d)   → "Expired" + red re-auth action
     sl4 — unrecoverable refresh failure            → "Needs re-authentication" + stored reason */
(function(){
  var now = new Date().getTime(), H = 3600000, D = 24 * H;
  (MCP_SESSIONS['slack-tools'] || []).forEach(function(s){
    if (s.id === 'sl2') {
      s.oauth_expires_at = new Date(now + 34 * H).toISOString();
      s.oauth_refresh_expires_at = new Date(now + 26 * D).toISOString();
    }
    if (s.id === 'sl3') {
      s.oauth_expires_at = new Date(now - 6 * H).toISOString();
      s.oauth_refresh_expires_at = new Date(now - 2 * D).toISOString();
    }
  });
})();
var MCP_AUTH_LABELS = { api_key:'API Key', bearer_token:'Bearer Token', basic_auth:'Basic Auth', oauth2:'OAuth 2.0', none:'No Auth', passthrough:'Passthrough' };
var MCP_AUTH_DESCS = {
  api_key:'Authenticate using an API key sent as a header.',
  bearer_token:'Authenticate using a static Bearer token.',
  basic_auth:'Authenticate using HTTP Basic Authentication (username + password).',
  oauth2:'Authenticate using OAuth 2.0 authorization code flow with automatic token refresh.',
  none:'No authentication is required for this MCP server.',
  passthrough:'Credentials are forwarded from the calling agent identity. No server-side credentials are stored.'
};
var mcpCurrentServer = '';
var mcpEditingSessionId = null;

function mcpOpenSessions(slug) {
  mcpCurrentServer = slug;
  var sessions = MCP_SESSIONS[slug] || [];
  document.getElementById('modal-sessions-title').textContent = 'Sessions — ' + slug;
  mcpRenderSessionsList(sessions);
  document.getElementById('btn-add-session-modal').onclick = function(){ mcpOpenSessionForm(null); };
  openModal('modal-sessions');
}

function mcpRenderSessionsList(sessions) {
  var body = document.getElementById('modal-sessions-body');
  var n = sessions.length;
  var autoDefault = n === 1;

  if (n === 0) {
    body.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><div style="font-weight:600;color:var(--text-primary)">No sessions configured</div><div style="font-size:12px;color:var(--text-secondary)">Add at least one session to enable syncing.</div></div>';
    return;
  }

  var h = '<div id="session-delete-error-msg" style="font-size:11px;color:var(--error);display:none;margin-bottom:8px"></div>';

  if (autoDefault) {
    h += '<div class="alert alert-info" style="margin-bottom:12px"><span style="margin-right:6px">💡</span>Only one session exists — it is automatically treated as the default. Add more sessions to choose a different default.</div>';
  } else {
    h += '<div class="alert alert-info" style="margin-bottom:12px"><span style="margin-right:6px">★</span>Select one session as the default. The default session is used for sync operations and tool routing.</div>';
  }

  h += '<div class="table-wrap"><table><thead><tr>' +
    '<th style="width:36px"></th><th>Name</th><th>Auth Type</th><th>Token Status</th><th>Status</th><th>Actions</th></tr></thead><tbody>';

  sessions.forEach(function(s){
    var isD = s.is_default || autoDefault;
    var tokenStatus = mcpTokenStatus(s);
    var radioCls = '';
    if (isD) radioCls = autoDefault ? 'style="border-color:#C4B5FD;background:transparent" title="Auto-default (sole session)"' : 'style="border-color:#2563EB;background:#2563EB" title="Current default"';
    h += '<tr' + (s.requires_reauth ? ' class="row-needs-reauth"' : '') + '>' +
      '<td><div style="width:18px;height:18px;border-radius:50%;border:2px solid ' + (isD ? (autoDefault ? '#C4B5FD' : '#2563EB') : '#E0E0E0') + ';flex-shrink:0;cursor:' + (autoDefault || !s.is_active ? 'default' : 'pointer') + ';position:relative;display:inline-block;' + (isD && !autoDefault ? 'background:#2563EB' : '') + '" ' +
        (autoDefault || !s.is_active ? '' : 'onclick="mcpSetDefault(\'' + s.id + '\')"') + '>' +
        (isD ? '<span style="position:absolute;width:6px;height:6px;border-radius:50%;background:#fff;top:4px;left:4px"></span>' : '') +
        '</div></td>' +
      '<td><span style="font-weight:500">' + s.name + '</span>' +
        (isD ? ' <span class="chip chip-purple" style="font-size:9px;padding:1px 6px">Default</span>' : '') +
        (s.description ? '<div style="font-size:11px;color:var(--text-secondary)">' + s.description + '</div>' : '') + '</td>' +
      '<td>' + MCP_AUTH_LABELS[s.auth_type] + (s.auth_type === 'passthrough' ? ' <span class="chip chip-blue" style="font-size:10px">passthrough</span>' : '') + '</td>' +
      '<td>' + tokenStatus.cell + '</td>' +
      '<td>' + (s.is_active ? '<span class="chip chip-green">Active</span>' : '<span class="chip chip-gray">Inactive</span>') + '</td>' +
      '<td class="actions-cell">' +
        '<button class="btn-icon-sm" ' + (s.is_default || !s.is_active ? 'disabled' : '') + ' style="' + (s.is_default ? 'color:#6D28D9' : '') + '" onclick="mcpSetDefault(\'' + s.id + '\')" title="' + (s.is_default ? 'Current default' : 'Set as default') + '">★</button>' +
        mcpSessionAuthAction(s) +
        '<button class="btn-icon-sm" onclick="mcpOpenSessionForm(\'' + s.id + '\')" title="Edit">✏️</button>' +
        (isD && n > 1
          ? '<span class="tooltip-wrap" style="display:inline-flex"><button class="btn-icon-sm" disabled style="opacity:0.35" title="Cannot delete default">🗑️</button><span class="tooltip" style="position:absolute;bottom:calc(100%+6px);left:50%;transform:translateX(-50%);background:#1E293B;color:#fff;font-size:11px;padding:5px 10px;border-radius:4px;white-space:nowrap;z-index:500;display:none">Cannot delete the default. Select another first.</span></span>'
          : '<button class="btn-icon-sm" onclick="mcpDeleteSession(\'' + s.id + '\')" title="Delete">🗑️</button>') +
      '</td></tr>';
  });
  h += '</tbody></table></div>';
  body.innerHTML = h;
}

function mcpSetDefault(sessionId) {
  var sessions = MCP_SESSIONS[mcpCurrentServer];
  if (sessions.length <= 1) return;
  var s = sessions.find(function(x){ return x.id === sessionId });
  if (!s || !s.is_active) return;
  if (s.is_default) return;
  sessions.forEach(function(x){ x.is_default = (x.id === sessionId); });
  mcpRenderSessionsList(sessions);
  mcpUpdateServerRow(mcpCurrentServer);
  // mini toast
  var container = document.getElementById('toast-container') || document.body;
  var t = document.createElement('div');
  t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 18px;border-radius:8px;background:#F0FDF4;color:#166534;font-size:13px;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:3000;animation:toastIn 0.25s ease';
  t.textContent = '★ ' + s.name + ' set as default for ' + mcpCurrentServer;
  document.body.appendChild(t);
  setTimeout(function(){ t.style.opacity='0'; t.style.transition='opacity 0.3s'; setTimeout(function(){ t.remove(); },300); },2500);
}

function mcpDeleteSession(sessionId) {
  var sessions = MCP_SESSIONS[mcpCurrentServer];
  var s = sessions.find(function(x){ return x.id === sessionId });
  if (!s) return;
  if (s.is_default && sessions.length > 1) {
    document.getElementById('session-delete-error-msg').textContent = 'Cannot delete the default session while other sessions exist. Designate another as default first.';
    document.getElementById('session-delete-error-msg').style.display = 'block';
    return;
  }
  MCP_SESSIONS[mcpCurrentServer] = sessions.filter(function(x){ return x.id !== sessionId });
  mcpUpdateServerRow(mcpCurrentServer);
  mcpRenderSessionsList(MCP_SESSIONS[mcpCurrentServer]);
}

function mcpUpdateServerRow(slug) {
  var sessions = MCP_SESSIONS[slug] || [];
  var row = document.getElementById('mcp-row-' + slug);
  if (!row) return;
  row.setAttribute('data-sessions', sessions.length);
  var tds = row.querySelectorAll('td');
  if (tds[4]) {
    tds[4].innerHTML = sessions.length === 0
      ? '<span class="chip chip-gray">0 sessions</span>'
      : '<span>' + sessions.length + ' sessions</span>';
  }
}

/* ═══ MCP SESSION TOKEN STATE — mirrors McpSessionManager.getTokenStatus() ═══
   An unrecoverable OAuth refresh failure sets requires_reauth + last_refresh_error;
   the status chip turns red, carries the stored reason as a tooltip, and the action
   becomes a red re-auth button. Completing re-auth updates the SAME session in place. */
function mcpIsRefreshTokenValid(s) {
  if (!s.oauth_refresh_expires_at) return false;
  return new Date(s.oauth_refresh_expires_at) > new Date();
}

function mcpTokenStatus(s) {
  if (s.auth_type !== 'oauth2') {
    return { label: 'N/A', cell: '<span class="text-secondary">—</span>' };
  }
  var label, cls, icon = '';
  if (s.requires_reauth) {
    label = 'Needs re-authentication'; cls = 'chip-red'; icon = '⚠';
  } else if (!s.oauth_expires_at) {
    label = 'Unknown'; cls = 'chip-yellow'; icon = '⚠';
  } else {
    var hours = (new Date(s.oauth_expires_at).getTime() - new Date().getTime()) / 3600000;
    if (hours < 0) { label = 'Expired'; cls = 'chip-red'; icon = '⚠'; }
    else if (hours < 1) { label = 'Expiring Soon'; cls = 'chip-yellow'; icon = '⚠'; }
    else {
      var txt = hours < 24 ? Math.floor(hours) + 'h' : Math.floor(hours / 24) + 'd';
      label = 'Valid (' + txt + ')'; cls = 'chip-green'; icon = '✓';
    }
  }
  var chip = '<span class="chip ' + cls + '">' + (icon ? icon + ' ' : '') + label + '</span>';
  if (s.requires_reauth && s.last_refresh_error) {
    return {
      label: label,
      cell: '<span class="tooltip-wrap" style="display:inline-flex">' + chip +
            '<span class="tooltip" style="white-space:normal;width:220px"><strong>Refresh failed:</strong> ' + s.last_refresh_error + '</span></span>'
    };
  }
  return { label: label, cell: chip };
}

function mcpSessionAuthAction(s) {
  if (s.auth_type !== 'oauth2') return '';
  if (!s.requires_reauth && mcpIsRefreshTokenValid(s)) {
    return '<button class="btn-icon-sm" style="color:#15803D" onclick="mcpRefreshSessionToken(\'' + mcpCurrentServer + '\',\'' + s.id + '\')" title="Refresh OAuth Token">🔄</button>';
  }
  var tip = s.requires_reauth ? 'Needs re-authentication' : 'Re-authenticate (refresh token expired)';
  return '<button class="btn-icon-sm" style="color:var(--error)" onclick="mcpSessionReauth(\'' + mcpCurrentServer + '\',\'' + s.id + '\')" title="' + tip + '">🔑</button>';
}

function mcpToast(msg, type) {
  var t = document.createElement('div');
  var bg = type === 'success' ? '#F0FDF4' : type === 'error' ? '#FEF2F2' : '#EFF6FF';
  var fg = type === 'success' ? '#166534' : type === 'error' ? '#991B1B' : '#1E40AF';
  t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 18px;border-radius:8px;background:' + bg + ';color:' + fg + ';font-size:13px;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:3000;animation:toastIn 0.25s ease;max-width:560px';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function(){ t.style.opacity='0'; t.style.transition='opacity 0.3s'; setTimeout(function(){ t.remove(); },300); },2800);
}

function mcpRefreshSessionToken(slug, sessionId) {
  var sessions = MCP_SESSIONS[slug] || [];
  var s = sessions.find(function(x){ return x.id === sessionId; });
  if (!s) return;
  s.oauth_expires_at = new Date(new Date().getTime() + 3600000).toISOString();
  mcpRenderSessionsList(sessions);
  mcpRenderReauthBanner();
  mcpToast('OAuth token refreshed for ' + s.name + '.', 'success');
}

function mcpSessionReauth(slug, sessionId) {
  var sessions = MCP_SESSIONS[slug] || [];
  var s = sessions.find(function(x){ return x.id === sessionId; });
  if (!s) return;
  mcpToast('Opening OAuth re-authentication for ' + s.name + '…', 'info');
  /* Stands in for the OAuth popup + callback: tokens are refreshed in place on the
     same session record, so the row, its default flag and its bindings are unchanged. */
  setTimeout(function(){
    s.requires_reauth = false;
    s.last_refresh_error = null;
    s.oauth_expires_at = new Date(new Date().getTime() + 3600000).toISOString();
    s.oauth_refresh_expires_at = new Date(new Date().getTime() + 30 * 24 * 3600000).toISOString();
    mcpRenderSessionsList(sessions);
    mcpRenderReauthBanner();
    mcpUpdateServerRow(slug);
    mcpToast('Session re-authenticated — tokens updated in place.', 'success');
  }, 1200);
}

/* Cross-server banner: surfaces every session whose refresh failed unrecoverably. */
function mcpRenderReauthBanner() {
  var wrap = document.getElementById('mcp-reauth-banner');
  if (!wrap) return;
  var flagged = [];
  Object.keys(MCP_SESSIONS).forEach(function(slug){
    (MCP_SESSIONS[slug] || []).forEach(function(s){
      if (s.auth_type === 'oauth2' && s.requires_reauth) flagged.push({ slug: slug, session: s });
    });
  });
  if (!flagged.length) { wrap.innerHTML = ''; return; }
  var names = flagged.map(function(f){ return f.session.name; }).join(', ');
  wrap.innerHTML = '<div class="alert alert-error" style="align-items:center">' +
    '<span style="font-size:16px">⚠️</span>' +
    '<div style="flex:1"><strong>' + flagged.length + ' session' + (flagged.length > 1 ? 's' : '') + ' need' + (flagged.length > 1 ? '' : 's') + ' re-authentication</strong>' +
    '<div style="margin-top:2px">' + names + ' — the OAuth refresh token could not be renewed. Tool calls routed through this session fail until it is re-authenticated.</div></div>' +
    '<button class="btn btn-sm btn-secondary" style="background:#fff;color:#991B1B;border-color:#FECACA" onclick="mcpOpenSessions(\'' + flagged[0].slug + '\')">🔑 Review session</button>' +
    '</div>';
}

/* Render the banner on load (DOM is already parsed — this script sits at the end of body). */
mcpRenderReauthBanner();

function mcpSync(slug) {
  var sessions = MCP_SESSIONS[slug] || [];
  if (sessions.length === 0) {
    var t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 18px;border-radius:8px;background:#FEF3C7;color:#92400E;font-size:13px;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:3000;animation:toastIn 0.25s ease';
    t.textContent = 'Cannot sync: no sessions configured. Add a session first.';
    document.body.appendChild(t);
    setTimeout(function(){ t.style.opacity='0'; t.style.transition='opacity 0.3s'; setTimeout(function(){ t.remove(); },300); },2500);
    return;
  }
  var cell = document.querySelector('#mcp-row-' + slug + ' td:nth-child(6)');
  if (cell) cell.innerHTML = '<span style="color:var(--primary)">Syncing...</span>';
  setTimeout(function(){
    if (cell) {
      cell.innerHTML = '<span class="text-secondary">Just now</span><div class="text-xs" style="color:var(--success);margin-top:2px">8 tools discovered</div>';
    }
    var t = document.createElement('div');
    t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 18px;border-radius:8px;background:#F0FDF4;color:#166534;font-size:13px;font-weight:500;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:3000;animation:toastIn 0.25s ease';
    t.textContent = 'Sync complete — 8 tools discovered from ' + slug;
    document.body.appendChild(t);
    setTimeout(function(){ t.style.opacity='0'; t.style.transition='opacity 0.3s'; setTimeout(function(){ t.remove(); },300); },2500);
  }, 1000);
}

// ─── SESSION FORM ───
var mcpFormAutoDiscovery = true;

function mcpOpenSessionForm(sessionId) {
  mcpEditingSessionId = sessionId || null;
  var sessions = MCP_SESSIONS[mcpCurrentServer];
  document.getElementById('session-form-error').style.display = 'none';

  if (sessionId) {
    var existing = sessions.find(function(s){ return s.id === sessionId });
    document.getElementById('modal-session-form-title').textContent = 'Edit Session';
    mcpRenderSessionForm({
      name: existing ? existing.name : '',
      description: existing ? (existing.description || '') : '',
      auth_type: existing ? existing.auth_type : 'api_key',
      is_active: existing ? existing.is_active : true,
      is_saved: !!sessionId
    });
  } else {
    document.getElementById('modal-session-form-title').textContent = 'Add Session';
    mcpRenderSessionForm({
      name: '', description: '', auth_type: 'api_key', is_active: true, is_saved: false
    });
  }
  document.getElementById('btn-save-session-form').onclick = mcpSaveSession;
  openModal('modal-session-form');
}

function mcpRenderSessionForm(f) {
  var body = document.getElementById('modal-session-form-body');
  var h = '';
  h += '<div class="form-group"><label>Name <span style="color:var(--error)">*</span></label><input class="form-control" id="sf-name" value="' + escHtml(f.name) + '" placeholder="Session name"></div>';
  h += '<div class="form-group"><label>Description</label><textarea class="form-control" id="sf-desc" rows="2" placeholder="Optional...">' + escHtml(f.description) + '</textarea></div>';

  // Auth type + info
  var authOpts = ['api_key','bearer_token','basic_auth','oauth2','none','passthrough'];
  h += '<div style="display:flex;align-items:flex-end;gap:8px"><div class="form-group" style="flex:1"><label>Auth Type</label>' +
    '<select class="form-control" id="sf-auth-type" onchange="mcpOnAuthChange()">';
  authOpts.forEach(function(at){
    h += '<option value="' + at + '"' + (f.auth_type === at ? ' selected' : '') + '>' + MCP_AUTH_LABELS[at] + '</option>';
  });
  h += '</select></div>' +
    '<div style="padding-bottom:8px;position:relative"><span style="width:18px;height:18px;border-radius:50%;background:var(--bg);border:1px solid var(--border);color:var(--text-secondary);display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;cursor:help" id="sf-auth-info-icon">?</span>' +
    '<span style="display:none;position:absolute;bottom:calc(100%+4px);right:0;background:#fff;color:var(--text-primary);font-size:11px;padding:6px 10px;border-radius:4px;border:1px solid var(--border);width:200px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:500;line-height:1.4" id="sf-auth-tip">' + MCP_AUTH_DESCS[f.auth_type] + '</span></div></div>';

  // is_active toggle
  h += '<div class="form-group mt-3"><label class="toggle" style="display:inline-flex;align-items:center;gap:8px;cursor:pointer">' +
    '<input type="checkbox" id="sf-is-active" ' + (f.is_active ? 'checked' : '') + ' onchange="var l=document.getElementById(\'sf-active-lbl\');if(l)l.textContent=this.checked?\'Active\':\'Inactive\'">' +
    '<span class="toggle-slider"></span><span id="sf-active-lbl" style="font-size:13px;text-transform:none;letter-spacing:0;font-weight:400">' + (f.is_active ? 'Active' : 'Inactive') + '</span></label></div>';

  h += '<div style="height:1px;background:var(--border);margin:16px 0"></div>';

  // Credential fields
  h += '<div id="sf-creds">' + mcpRenderCredFields(f) + '</div>';
  body.innerHTML = h;

  // info icon hover
  var icon = document.getElementById('sf-auth-info-icon');
  var tip = document.getElementById('sf-auth-tip');
  if (icon && tip) {
    icon.onmouseenter = function(){ tip.style.display = 'block'; };
    icon.onmouseleave = function(){ tip.style.display = 'none'; };
  }
}

function escHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function mcpRenderCredFields(f) {
  var at = f.auth_type;
  if (at === 'api_key') {
    var h = f.is_saved
      ? '<div style="display:flex;align-items:center;gap:6px;padding:8px 12px;border:1px dashed var(--border);border-radius:4px;color:var(--text-secondary);font-size:12px;margin-bottom:12px"><span>🔒</span><span style="letter-spacing:3px;font-family:monospace">●●●●●●●●</span><span>API key is stored securely</span></div>' +
        '<div class="form-group"><label>API Key</label><input class="form-control" type="password" id="sf-api-key" value="" placeholder="Leave blank to keep current key"><div class="form-hint">Enter a new value to update; leave blank to keep the current key.</div></div>'
      : '<div class="form-group"><label>API Key</label><input class="form-control" type="password" id="sf-api-key" value="" placeholder="sk-..."><div class="form-hint">The API key will be sent as <code>X-API-Key</code> header by default.</div></div>';
    h += '<div class="form-group"><label class="toggle" style="display:inline-flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="sf-api-as-bearer"><span class="toggle-slider"></span><span style="font-size:13px;text-transform:none;letter-spacing:0;font-weight:400">Send as Bearer token</span></label><div class="form-hint">When enabled, the API key will be sent as <code>Authorization: Bearer &lt;key&gt;</code> instead of <code>X-API-Key</code>.</div></div>';
    return h;
  }
  if (at === 'bearer_token') {
    return f.is_saved
      ? '<div style="display:flex;align-items:center;gap:6px;padding:8px 12px;border:1px dashed var(--border);border-radius:4px;color:var(--text-secondary);font-size:12px;margin-bottom:12px"><span>🔒</span><span style="letter-spacing:3px;font-family:monospace">●●●●●●●●●●●●</span><span>Bearer token is stored securely</span></div>' +
        '<div class="form-group"><label>Bearer Token</label><input class="form-control" type="password" id="sf-bearer-token" value="" placeholder="Leave blank to keep current token"><div class="form-hint">Enter a new value to update; leave blank to keep the current token.</div></div>'
      : '<div class="form-group"><label>Bearer Token</label><input class="form-control" type="password" id="sf-bearer-token" value="" placeholder="Enter Bearer token..."><div class="form-hint">The token will be sent as <code>Authorization: Bearer &lt;token&gt;</code> header.</div></div>';
  }
  if (at === 'basic_auth') {
    return f.is_saved
      ? '<div style="display:flex;align-items:center;gap:6px;padding:8px 12px;border:1px dashed var(--border);border-radius:4px;color:var(--text-secondary);font-size:12px;margin-bottom:12px"><span>🔒</span><span style="letter-spacing:3px;font-family:monospace">●●●●●●●●</span><span>Credentials are stored securely</span></div>' +
        '<div class="form-group"><label>Username</label><input class="form-control" id="sf-basic-user" value="" placeholder="Leave blank to keep current"></div>' +
        '<div class="form-group"><label>Password</label><input class="form-control" type="password" id="sf-basic-pass" value="" placeholder="Leave blank to keep current"><div class="form-hint">Enter new values to update; leave blank to keep current credentials.</div></div>'
      : '<div class="form-group"><label>Username</label><input class="form-control" id="sf-basic-user" value="" placeholder="Username"></div>' +
        '<div class="form-group"><label>Password</label><input class="form-control" type="password" id="sf-basic-pass" value="" placeholder="Password"><div class="form-hint">Credentials are sent as HTTP Basic Auth header.</div></div>';
  }
  if (at === 'oauth2') {
    var h = '<div class="alert alert-info" style="margin-bottom:12px"><div>🔐 Click the button below to authenticate with the OAuth 2.0 provider. A popup window will guide you through the authorization flow.</div></div>';
    h += '<button class="btn btn-primary" style="width:100%;justify-content:center;margin-bottom:14px" onclick="alert(\'OAuth 2.0 popup flow would open here.\')">🔑 Authenticate with OAuth 2.0</button>';
    h += '<div class="form-group"><label class="toggle" style="display:inline-flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="sf-oauth-auto" checked onchange="mcpToggleOAuthManual()"><span class="toggle-slider"></span><span style="font-size:13px;text-transform:none;letter-spacing:0;font-weight:400">Auto-discovery</span></label><div class="form-hint">When enabled, OAuth 2.0 endpoints are automatically discovered from the server\'s metadata URL.</div></div>';
    h += '<div id="sf-oauth-manual" style="display:none;border:1px solid var(--border);border-radius:6px;padding:14px;background:#FAFBFC;margin-bottom:12px">';
    h += '<div class="form-group"><label>Metadata URL</label><input class="form-control" id="sf-oauth-metadata" placeholder="https://..."><div class="form-hint">OAuth 2.0 server metadata discovery endpoint.</div></div>';
    h += '<div class="form-group"><label>Authorization URL</label><input class="form-control" id="sf-oauth-auth-url" placeholder="https://..."></div>';
    h += '<div class="form-group"><label>Token URL</label><input class="form-control" id="sf-oauth-token-url" placeholder="https://..."></div>';
    h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px"><div class="form-group"><label>Client ID</label><input class="form-control" id="sf-oauth-client-id" placeholder="client_id"></div><div class="form-group"><label>Client Secret</label><input class="form-control" type="password" id="sf-oauth-secret" placeholder="client_secret"></div></div>';
    h += '<div class="form-group"><label>Scope</label><input class="form-control" id="sf-oauth-scope" placeholder="openid profile"></div></div>';
    h += '<div style="font-size:11px;color:var(--text-secondary)">Note: OAuth 2.0 sessions automatically refresh tokens before expiry.</div>';
    return h;
  }
  if (at === 'none') return '<div class="alert alert-info"><div>🔓 No authentication is required for this MCP server.</div></div>';
  if (at === 'passthrough') return '<div class="alert alert-info"><div>🔗 Credentials are forwarded from the calling agent identity. No server-side credentials are stored.</div></div>';
  return '';
}

function mcpOnAuthChange() {
  var sel = document.getElementById('sf-auth-type');
  var tip = document.getElementById('sf-auth-tip');
  if (tip) tip.textContent = MCP_AUTH_DESCS[sel.value];
  var creds = document.getElementById('sf-creds');
  if (creds) creds.innerHTML = mcpRenderCredFields({ auth_type: sel.value, is_saved: !!mcpEditingSessionId });
}

function mcpToggleOAuthManual() {
  var cb = document.getElementById('sf-oauth-auto');
  var panel = document.getElementById('sf-oauth-manual');
  if (panel) panel.style.display = cb && !cb.checked ? 'block' : 'none';
}

function mcpSaveSession() {
  var name = (document.getElementById('sf-name')||{}).value || '';
  if (!name.trim()) {
    document.getElementById('session-form-error').textContent = 'Name is required.';
    document.getElementById('session-form-error').style.display = 'block';
    return;
  }
  var sessions = MCP_SESSIONS[mcpCurrentServer];
  var wasEmpty = sessions.length === 0;
  if (mcpEditingSessionId) {
    var s = sessions.find(function(x){ return x.id === mcpEditingSessionId });
    if (s) {
      s.name = name;
      s.description = (document.getElementById('sf-desc')||{}).value || '';
      s.auth_type = (document.getElementById('sf-auth-type')||{}).value;
      s.is_active = (document.getElementById('sf-is-active')||{}).checked;
    }
  } else {
    sessions.push({
      id: 's' + Date.now(),
      name: name,
      description: (document.getElementById('sf-desc')||{}).value || '',
      auth_type: (document.getElementById('sf-auth-type')||{}).value,
      is_active: (document.getElementById('sf-is-active')||{}).checked,
      is_default: wasEmpty
    });
  }
  mcpUpdateServerRow(mcpCurrentServer);
  mcpRenderSessionsList(sessions);
  closeModal('modal-session-form');
  mcpEditingSessionId = null;
}

function mcpOpenServerForm() { openModal('modal-mcp-server-form'); }

// ═══════════════════════════════ CONVERSATION DETAIL ═══════════════════════════════
function openConvDetail() {
  document.getElementById('drawer-conv-overlay').classList.add('open');
  var d = document.getElementById('drawer-conv');
  d.classList.add('open');
  d.style.right = '0';
}
function closeConvDetail() {
  document.getElementById('drawer-conv-overlay').classList.remove('open');
  var d = document.getElementById('drawer-conv');
  d.classList.remove('open');
  d.style.right = '-560px';
}

// ═══════════════════════════════ RESULT DETAIL ═══════════════════════════════
function openResultDetail() {
  document.getElementById('drawer-result-overlay').classList.add('open');
  var d = document.getElementById('drawer-result');
  d.classList.add('open');
  d.style.right = '0';
}
function closeResultDetail() {
  document.getElementById('drawer-result-overlay').classList.remove('open');
  var d = document.getElementById('drawer-result');
  d.classList.remove('open');
  d.style.right = '-560px';
}

// ═══════════════════════════════ SETUP WIZARD ═══════════════════════════════
var selectedProvider = 'keycloak-new';
var existingType = 'keycloak';

function wizNext() {
  if (wizardStep < 4) { wizardStep++; renderWizard(); }
}
function wizBack() {
  if (wizardStep > 1) { wizardStep--; renderWizard(); }
}
function renderWizard() {
  for (var i = 1; i <= 4; i++) {
    var sc = document.getElementById('sc' + i);
    var sl = document.getElementById('sl' + i);
    if (!sc) continue;
    if (i < wizardStep) {
      sc.className = 'step-circle done';
      sc.textContent = '✓';
      sl.className = 'step-label';
    } else if (i === wizardStep) {
      sc.className = 'step-circle active';
      sc.textContent = i === 4 ? '✓' : i;
      sl.className = 'step-label active';
    } else {
      sc.className = 'step-circle pending';
      sc.textContent = i === 4 ? '✓' : i;
      sl.className = 'step-label pending';
    }
  }
  for (var j = 1; j <= 3; j++) {
    var conn = document.getElementById('conn' + j);
    if (conn) conn.className = 'step-connector' + (j < wizardStep ? ' done' : '');
  }
  
  document.getElementById('wiz-step1').style.display = wizardStep === 1 ? 'block' : 'none';
  document.getElementById('wiz-step2-kc').style.display = (wizardStep === 2 && selectedProvider === 'keycloak-new') ? 'block' : 'none';
  document.getElementById('wiz-step2-ex').style.display = (wizardStep === 2 && selectedProvider === 'existing') ? 'block' : 'none';
  document.getElementById('wiz-step3').style.display = wizardStep === 3 ? 'block' : 'none';
  document.getElementById('wiz-step4').style.display = wizardStep === 4 ? 'block' : 'none';
}

function selectProvider(type) {
  selectedProvider = type;
  document.getElementById('opt-keycloak-new').classList.toggle('selected', type === 'keycloak-new');
  document.getElementById('opt-existing').classList.toggle('selected', type === 'existing');
  document.getElementById('existingSubOptions').style.display = type === 'existing' ? 'flex' : 'none';
}
function selectExistingType(type, e) {
  e.stopPropagation();
  existingType = type;
  document.getElementById('sub-keycloak').classList.toggle('active', type === 'keycloak');
  document.getElementById('sub-entra').classList.toggle('active', type === 'entra');
}
function goToConfig() {
  if (selectedProvider === 'existing') {
    document.getElementById('existingProviderTitle').textContent = existingType === 'entra' ? 'Connect Azure EntraID' : 'Connect Keycloak';
  }
  wizNext();
}

function showErr(id, msg) {
  var input = document.getElementById(id);
  var err = document.getElementById('err-' + id);
  if (input) input.classList.add('error');
  if (err) { err.textContent = msg; err.classList.add('visible'); }
}
function clearErr(id) {
  var input = document.getElementById(id);
  var err = document.getElementById('err-' + id);
  if (input) input.classList.remove('error');
  if (err) err.classList.remove('visible');
}
function val(id) { return (document.getElementById(id)?.value || '').trim(); }

function validateKeycloakNew() {
  let ok = true;
  if (!val('kc-username')) { showErr('kc-username', 'Username is required.'); ok = false; }
  if (!val('kc-password')) { showErr('kc-password', 'Password is required.'); ok = false; }
  if (!val('kc-confirm')) { showErr('kc-confirm', 'Please confirm password.'); ok = false; }
  else if (val('kc-password') !== val('kc-confirm')) { showErr('kc-confirm', 'Passwords mismatch.'); ok = false; }
  if (ok) runLoading('keycloak-new', {
    username: val('kc-username'), realm: val('kc-realm') || 'parthenon'
  });
}
function validateExisting() {
  let ok = true;
  if (!val('oidc-url')) { showErr('oidc-url', 'Provider URL is required.'); ok = false; }
  if (!val('oidc-client-id')) { showErr('oidc-client-id', 'Client ID is required.'); ok = false; }
  if (!val('oidc-secret')) { showErr('oidc-secret', 'Client secret is required.'); ok = false; }
  if (ok) runLoading('existing', {
    url: val('oidc-url'), clientId: val('oidc-client-id'), type: existingType, audience: val('oidc-audience') || val('oidc-client-id')
  });
}

function resetStep(n) {
  var el = document.getElementById('ps-' + n);
  if(!el) return;
  el.className = 'progress-step pending';
  el.querySelector('.step-status').textContent = '○';
}
function activateStep(n) {
  var el = document.getElementById('ps-' + n);
  if(!el) return;
  el.className = 'progress-step active';
  el.querySelector('.step-status').innerHTML = '<div class="mini-spinner"></div>';
}
function completeStep(n) {
  var el = document.getElementById('ps-' + n);
  if(!el) return;
  el.className = 'progress-step done';
  el.querySelector('.step-status').textContent = '✓';
}
function setText(id, t) { var el = document.getElementById(id); if (el) el.textContent = t; }

function runLoading(mode, data) {
  wizNext();
  var isNew = mode === 'keycloak-new';
  setText('ps-1-text', isNew ? 'Provisioning Keycloak...' : 'Validating OIDC endpoint...');
  setText('ps-2-text', isNew ? 'Configuring realm "'+data.realm+'"...' : 'Fetching metadata...');
  setText('ps-3-text', isNew ? 'Creating user "'+data.username+'"...' : 'Verifying credentials...');
  setText('ps-4-text', isNew ? 'Registering OIDC client...' : 'Saving configuration...');
  setText('ps-5-text', isNew ? 'Verifying connectivity...' : 'Testing token endpoint...');
  setText('loadingTitle', isNew ? 'Provisioning Keycloak...' : 'Connecting Provider...');
  
  for (var i = 1; i <= 5; i++) resetStep(i);
  [0, 600, 1200, 1800, 2400].forEach((d, idx) => {
    setTimeout(() => activateStep(idx + 1), d);
    setTimeout(() => completeStep(idx + 1), d + 500);
  });
  setTimeout(() => showSuccess(mode, data), 3000);
}

function showSuccess(mode, data) {
  wizNext();
  var grid = document.getElementById('summaryGrid');
  grid.innerHTML = '';
  function row(k, v) { return `<div class="summary-row"><span class="summary-key">${k}</span><span class="summary-value">${v}</span></div>`; }
  
  if (mode === 'keycloak-new') {
    setText('successTitle', 'Keycloak Configured!');
    setText('successSubtitle', 'A Keycloak instance has been provisioned. Configuration saved to database.');
    grid.innerHTML += row('Provider', 'Keycloak (managed)') + row('Realm', data.realm) + row('Admin User', data.username);
  } else {
    var typeLabel = data.type === 'entra' ? 'Azure EntraID' : 'Keycloak';
    setText('successTitle', typeLabel + ' Connected!');
    setText('successSubtitle', typeLabel + ' OIDC provider validated and saved to database.');
    grid.innerHTML += row('Provider', typeLabel) + row('Client ID', data.clientId) + row('Audience', data.audience);
  }
}

// ═══════════════════════════════ TABS ═══════════════════════════════
/* Decision Results detail (system-one-decision-skills): expand the sample
   execution answer panel inside the Decision Results tab. */
function drExpand() {
  var d = document.getElementById('drDetail');
  if (d) { d.style.display = 'block'; d.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
}

function switchTab(tabEl, panelId) {
  var parent = tabEl.closest('.view') || tabEl.parentElement.closest('div');
  // Deactivate all tabs/panels in this view
  tabEl.parentElement.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  tabEl.classList.add('active');
  var view = tabEl.closest('.view');
  if (view) {
    view.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
    var panel = document.getElementById(panelId);
    if (panel) panel.classList.add('active');
  }
}

// ═══════════════════════════════ SKILL EDITOR ═══════════════════════════════
function showSkillEditor(skillName) {
  document.getElementById('skills-list-panel').style.display = 'none';
  document.getElementById('skill-editor-panel').style.display = 'block';
  document.getElementById('skill-editor-title').textContent = skillName ? 'Edit Skill: ' + skillName : 'Create Skill';
  if (skillName) document.getElementById('skill-name-input').value = skillName;
}
function hideSkillEditor() {
  document.getElementById('skills-list-panel').style.display = 'block';
  document.getElementById('skill-editor-panel').style.display = 'none';
}

// ═══════════════════════════════ SOP EDITOR ═══════════════════════════════
function showSopEditor(sopName) {
  document.getElementById('sops-list-panel').style.display = 'none';
  document.getElementById('sop-editor-panel').style.display = 'block';
  document.getElementById('sop-editor-title').textContent = sopName ? 'Edit SOP: ' + sopName : 'Create SOP';
  if (sopName) document.getElementById('sop-name-input').value = sopName;
}
function hideSopEditor() {
  document.getElementById('sops-list-panel').style.display = 'block';
  document.getElementById('sop-editor-panel').style.display = 'none';
}
function addSopStep() {
  sopStepCount++;
  var container = document.getElementById('sop-steps-container');
  var arrow = document.createElement('div');
  arrow.className = 'step-arrow';
  arrow.textContent = '↓';
  var step = document.createElement('div');
  step.className = 'step-card';
  step.innerHTML = '<div class="step-card-header">' +
    '<div class="step-card-num">' + sopStepCount + '</div>' +
    '<select class="form-control" style="width:180px;padding:5px 10px;font-size:13px">' +
    '<option>Skill Invocation</option><option>Agent Delegation</option></select>' +
    '<div style="flex:1"></div>' +
    '<button class="btn-icon-sm" onclick="this.closest(\'.step-card\').previousSibling.remove();this.closest(\'.step-card\').remove();renumberSteps()">🗑️</button>' +
    '</div>' +
    '<div class="form-group" style="margin-bottom:0">' +
    '<label style="font-size:12px">Skill</label>' +
    '<select class="form-control" style="font-size:13px"><option>read-analyze-file</option><option>github-pr-workflow</option><option>slack-notify</option></select>' +
    '</div>';
  // Insert before the Add Step button
  var addBtn = container.querySelector('div[style*="margin-top"]') || container.lastElementChild;
  container.insertBefore(arrow, addBtn);
  container.insertBefore(step, addBtn);
}
function renumberSteps() {
  document.querySelectorAll('.step-card-num').forEach(function(el, i) {
    el.textContent = (i + 1);
  });
  sopStepCount = document.querySelectorAll('.step-card').length;
}

// ═══════════════════════════════ AGENT TYPE MODAL ═══════════════════════════════
function toggleAgentTypeFields() {
  var inputType = document.getElementById('agent-input-type-select').value;
  document.getElementById('agent-sop-field').style.display = (inputType === 'none') ? 'block' : 'none';
  document.getElementById('agent-input-schema-field').style.display = (inputType === 'typed') ? 'block' : 'none';
  document.getElementById('agent-guardrail-conversation').style.display = (inputType === 'conversation') ? 'block' : 'none';
  document.getElementById('agent-guardrail-non-conversation').style.display = (inputType === 'conversation') ? 'none' : 'block';
  document.getElementById('agent-output-type-select').disabled = (inputType === 'conversation');
  if (inputType === 'conversation') {
    document.getElementById('agent-output-schema-field').style.display = 'none';
    document.getElementById('agent-output-data-type-field').style.display = 'none';
  }
}

function toggleAgentOutputTypeFields() {
  var inputType = document.getElementById('agent-input-type-select').value;
  var outputType = document.getElementById('agent-output-type-select').value;
  document.getElementById('agent-output-schema-field').style.display = (inputType !== 'conversation' && outputType === 'typed') ? 'block' : 'none';
  // ENHANCE-AGENT-OUTPUT-SYSTEM: show data type selector for typed output
  var dtField = document.getElementById('agent-output-data-type-field');
  if (dtField) dtField.style.display = (inputType !== 'conversation' && outputType === 'typed') ? 'block' : 'none';
  // Show badge when a data type is selected
  var sel = document.getElementById('agent-output-data-type-select');
  var badge = document.getElementById('atSelectedDtBadge');
  var nameSpan = document.getElementById('atSelectedDtName');
  if (sel && badge && nameSpan) {
    if (sel.value) { nameSpan.textContent = sel.value; badge.style.display = ''; }
    else badge.style.display = 'none';
  }
}

// ═══════════════════════════════ SCHEDULES ═══════════════════════════════
/* ── DATA ── */
const SCHED_AGENTS = [
  { id: 'abc-123', name: 'Data Analyst Agent', input_type: 'typed' },
  { id: 'def-456', name: 'Report Generator Agent', input_type: 'none' },
  { id: 'ghi-789', name: 'Health Monitor Agent', input_type: 'typed' },
  { id: 'jkl-012', name: 'PR Reviewer Agent', input_type: 'conversation' },
  { id: 'mno-345', name: 'File Manager Agent', input_type: 'none' },
];

let schedData = [
  { id: 'sch-001', name: 'Daily Summary Report', description: 'Generates a daily summary report every weekday morning', cron_expression: '0 8 * * 1-5', target_id: 'abc-123', target_name: 'Data Analyst Agent', status: 'active', input_params: { report_type: 'daily_summary', format: 'markdown' }, created_at: '2026-05-01' },
  { id: 'sch-002', name: 'Hourly Health Check', description: 'Runs a health check on all systems every hour', cron_expression: '0 * * * *', target_id: 'ghi-789', target_name: 'Health Monitor Agent', status: 'active', input_params: { check_level: 'full', notify_on_failure: 'true' }, created_at: '2026-04-15' },
  { id: 'sch-003', name: 'Weekly Data Sync', description: 'Weekly database synchronization', cron_expression: '0 2 * * 1', target_id: 'def-456', target_name: 'Report Generator Agent', status: 'paused', input_params: { sync_mode: 'full' }, created_at: '2026-05-20' },
  { id: 'sch-004', name: 'System Metrics Collector', description: 'Collects system metrics every 5 minutes', cron_expression: '*/5 * * * *', target_id: 'ghi-789', target_name: 'Health Monitor Agent', status: 'active', input_params: { metrics: 'cpu,memory,disk' }, created_at: '2026-06-01' },
  { id: 'sch-005', name: 'PR Review Scan', description: 'Scans open PRs for review readiness', cron_expression: '0 9 * * 1-5', target_id: 'jkl-012', target_name: 'PR Reviewer Agent', status: 'active', input_params: { scan_type: 'readiness', max_prs: '10' }, created_at: '2026-06-05' },
];

let schedExecHistory = [
  { id: 'exec-001', schedule_id: 'sch-001', schedule_name: 'Daily Summary Report', started_at: '2026-06-08 08:00:01 UTC', finished_at: '2026-06-08 08:00:12 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-aa1', status: 'completed' } },
  { id: 'exec-002', schedule_id: 'sch-002', schedule_name: 'Hourly Health Check', started_at: '2026-06-08 15:00:00 UTC', finished_at: '2026-06-08 15:00:05 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-bb2', status: 'completed' } },
  { id: 'exec-003', schedule_id: 'sch-001', schedule_name: 'Daily Summary Report', started_at: '2026-06-07 08:00:01 UTC', finished_at: '2026-06-07 08:00:15 UTC', status: 'failure', error_message: 'Agent instance spawn failed: no available instances', agent_session: { id: 'sess-cc3', status: 'failed' } },
  { id: 'exec-004', schedule_id: 'sch-004', schedule_name: 'System Metrics Collector', started_at: '2026-06-08 15:55:00 UTC', finished_at: '2026-06-08 15:55:02 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-dd4', status: 'completed' } },
  { id: 'exec-005', schedule_id: 'sch-004', schedule_name: 'System Metrics Collector', started_at: '2026-06-08 15:50:00 UTC', finished_at: '2026-06-08 15:50:02 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-ee5', status: 'completed' } },
  { id: 'exec-006', schedule_id: 'sch-002', schedule_name: 'Hourly Health Check', started_at: '2026-06-08 14:00:00 UTC', finished_at: '2026-06-08 14:00:08 UTC', status: 'failure', error_message: 'Timeout: execution exceeded 30s limit', agent_session: { id: 'sess-ff6', status: 'terminated' } },
  { id: 'exec-007', schedule_id: 'sch-002', schedule_name: 'Hourly Health Check', started_at: '2026-06-08 13:00:00 UTC', finished_at: '2026-06-08 13:00:04 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-gg7', status: 'completed' } },
  { id: 'exec-008', schedule_id: 'sch-003', schedule_name: 'Weekly Data Sync', started_at: '2026-06-01 02:00:00 UTC', finished_at: '2026-06-01 02:01:15 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-hh8', status: 'completed' } },
  { id: 'exec-009', schedule_id: 'sch-002', schedule_name: 'Hourly Health Check', started_at: '2026-06-08 16:00:00 UTC', finished_at: null, status: 'running', error_message: null, agent_session: { id: 'sess-ii9', status: 'running' } },
  { id: 'exec-010', schedule_id: 'sch-005', schedule_name: 'PR Review Scan', started_at: '2026-06-08 09:00:00 UTC', finished_at: '2026-06-08 09:00:18 UTC', status: 'success', error_message: null, agent_session: { id: 'sess-jj0', status: 'completed' } },
];

let schedPage = 0;
let schedEditingId = null;
let schedNextId = 6;
let schedSelectedCron = '0 * * * *';
let schedHistoryFilterId = null;

/* ── FORMAT HELPERS ── */
function schedFormatCron(cron) {
  const map = {
    '0 * * * *': 'Every hour', '0 8 * * *': 'Daily at 8:00 AM',
    '0 8 * * 1-5': 'Weekdays at 8:00 AM', '0 8 * * 1': 'Weekly Monday 8:00 AM',
    '0 2 * * 1': 'Weekly Monday 2:00 AM', '*/5 * * * *': 'Every 5 minutes',
    '0 9 * * 1-5': 'Weekdays at 9:00 AM', '0 0 1 1 *': 'Yearly', '0 8 1 * *': 'Monthly on 1st',
  };
  return map[cron] || cron;
}

/* ── LIST ── */
function schedRender() {
  const tbody = document.getElementById('sched-table-body');
  if (!tbody) return;
  const start = schedPage * 5;
  const end = start + 5;
  const items = schedData.slice(start, end);
  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--text-secondary)">No schedules found. Click "Create Schedule" to get started.</td></tr>';
    document.getElementById('sched-pagination-info').textContent = '0 of 0';
    return;
  }
  tbody.innerHTML = items.map(s => {
    const isActive = s.status === 'active';
    const pauseIcon = isActive ? '⏸' : '▶';
    const pauseTitle = isActive ? 'Pause' : 'Resume';
    const statusChip = isActive ? '<span class="chip chip-green">● Active</span>' : '<span class="chip chip-yellow">⏸ Paused</span>';
    return '<tr>' +
      '<td><strong>' + s.name + '</strong><div class="text-xs text-secondary">' + (s.description || '') + '</div></td>' +
      '<td><span class="font-mono text-sm">' + s.cron_expression + '</span><br><span class="text-xs text-secondary">' + schedFormatCron(s.cron_expression) + '</span></td>' +
      '<td><span class="chip chip-blue">' + (s.target_name || s.target_id) + '</span></td>' +
      '<td>' + statusChip + '</td>' +
      '<td class="actions-cell">' +
        '<button class="btn-icon-sm" title="Execution history" onclick="schedShowHistory(\'' + s.id + '\')">📋</button>' +
        '<button class="btn-icon-sm" title="Edit" onclick="schedOpenEdit(\'' + s.id + '\')">✏️</button>' +
        '<button class="btn-icon-sm" title="' + pauseTitle + '" onclick="schedTogglePause(\'' + s.id + '\')">' + pauseIcon + '</button>' +
        '<button class="btn-icon-sm" title="Delete" onclick="schedDelete(\'' + s.id + '\')" style="color:var(--error)">🗑</button>' +
      '</td></tr>';
  }).join('');
  const total = schedData.length;
  const totalPages = Math.ceil(total / 5) || 1;
  document.getElementById('sched-pagination-info').textContent = (start + 1) + '–' + Math.min(end, total) + ' of ' + total;
  document.getElementById('sched-prev-btn').disabled = schedPage === 0;
  document.getElementById('sched-next-btn').disabled = schedPage >= totalPages - 1;
}

function schedPrevPage() { if (schedPage > 0) { schedPage--; schedRender(); } }
function schedNextPage() {
  const totalPages = Math.ceil(schedData.length / 5);
  if (schedPage < totalPages - 1) { schedPage++; schedRender(); }
}

/* ── ACTIONS ── */
function schedTogglePause(id) {
  const s = schedData.find(x => x.id === id);
  if (!s) return;
  const wasActive = s.status === 'active';
  s.status = wasActive ? 'paused' : 'active';
  schedToast(wasActive ? '"' + s.name + '" paused' : '"' + s.name + '" resumed', 'info');
  schedRender();
}

function schedDelete(id) {
  const s = schedData.find(x => x.id === id);
  if (!s) return;
  if (!confirm('Delete schedule "' + s.name + '"? This action cannot be undone.')) return;
  schedData = schedData.filter(x => x.id !== id);
  schedExecHistory = schedExecHistory.filter(x => x.schedule_id !== id);
  schedToast('"' + s.name + '" deleted', 'success');
  schedRender();
}

/* ── CREATE/EDIT DIALOG ── */
function schedOpenCreate() {
  schedEditingId = null;
  document.getElementById('sched-dialog-title').textContent = 'Create Schedule';
  document.getElementById('sched-save-btn').textContent = 'Create Schedule';
  document.getElementById('sched-input-name').value = '';
  document.getElementById('sched-input-desc').value = '';
  document.getElementById('sched-input-target').value = '';
  schedSelectedCron = '0 * * * *';
  schedSyncCron(schedSelectedCron);
  document.getElementById('sched-payload-rows').innerHTML =
    '<div class="payload-row"><input class="key-input" placeholder="Key" value="report_type"><input placeholder="Value" value="daily_summary"><button class="remove-btn" onclick="schedRemovePayload(this)">×</button></div>' +
    '<div class="payload-row"><input class="key-input" placeholder="Key" value="format"><input placeholder="Value" value="markdown"><button class="remove-btn" onclick="schedRemovePayload(this)">×</button></div>';
  document.getElementById('modal-schedule').classList.add('open');
}

function schedOpenEdit(id) {
  const s = schedData.find(x => x.id === id);
  if (!s) return;
  schedEditingId = id;
  document.getElementById('sched-dialog-title').textContent = 'Edit Schedule';
  document.getElementById('sched-save-btn').textContent = 'Save Changes';
  document.getElementById('sched-input-name').value = s.name;
  document.getElementById('sched-input-desc').value = s.description || '';
  document.getElementById('sched-input-target').value = s.target_id;
  schedSelectedCron = s.cron_expression;
  schedSyncCron(schedSelectedCron);
  const params = s.input_params || {};
  const keys = Object.keys(params);
  document.getElementById('sched-payload-rows').innerHTML = keys.length > 0
    ? keys.map(k => '<div class="payload-row"><input class="key-input" placeholder="Key" value="' + k + '"><input placeholder="Value" value="' + params[k] + '"><button class="remove-btn" onclick="schedRemovePayload(this)">×</button></div>').join('')
    : '<div class="payload-row"><input class="key-input" placeholder="Key"><input placeholder="Value"><button class="remove-btn" onclick="schedRemovePayload(this)">×</button></div>';
  document.getElementById('modal-schedule').classList.add('open');
}

function schedCloseDialog(e) {
  if (e && e.target !== e.currentTarget) return;
  var modal = document.getElementById('modal-schedule');
  if (modal) modal.classList.remove('open');
  schedEditingId = null;
}

/* ── CRON EDITOR ── */
function schedSyncCron(cron) {
  var textEl = document.getElementById('sched-cron-text');
  if (textEl) textEl.value = cron;
  var parts = cron.split(' ');
  var minute = parts[0], hour = parts[1], dow = parts[4] || '*';
  var minEl = document.getElementById('sched-cron-minute');
  var hourEl = document.getElementById('sched-cron-hour');
  if (minEl) minEl.value = (minute === '*' || minute.startsWith('*/')) ? '*' : (isNaN(parseInt(minute)) ? '*' : parseInt(minute));
  if (hourEl) hourEl.value = (hour === '*' || hour.startsWith('*/')) ? '*' : (isNaN(parseInt(hour)) ? '*' : parseInt(hour));
  var selectedDays = dow === '*' ? [1,2,3,4,5] : dow.split(',').map(Number);
  document.querySelectorAll('.sched-dow').forEach(function(b) {
    b.classList.toggle('selected', selectedDays.indexOf(parseInt(b.dataset.day)) !== -1);
  });
  schedUpdateShortcuts(cron);
  schedUpdateDesc(cron);
}

function schedOnCronText(val) {
  schedSelectedCron = val.trim() || '0 * * * *';
  schedSyncCron(schedSelectedCron);
}

function schedOnCronSelect() {
  var minute = document.getElementById('sched-cron-minute').value;
  var hour = document.getElementById('sched-cron-hour').value;
  var selected = Array.from(document.querySelectorAll('.sched-dow.selected')).map(function(b) { return parseInt(b.dataset.day); });
  var cronMin = minute === '*' ? '*' : minute;
  var cronHour = hour === '*' ? '*' : hour;
  var cronDow = (selected.length > 0 && selected.length < 7) ? selected.join(',') : '*';
  schedSelectedCron = cronMin + ' ' + cronHour + ' * * ' + cronDow;
  var textEl = document.getElementById('sched-cron-text');
  if (textEl) textEl.value = schedSelectedCron;
  schedUpdateShortcuts(schedSelectedCron);
  schedUpdateDesc(schedSelectedCron);
}

function schedSelectShortcut(btn) {
  document.querySelectorAll('.shortcut-btn').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  var cron = btn.dataset.cron;
  if (cron) { schedSelectedCron = cron; schedSyncCron(cron); }
}

function schedUpdateShortcuts(cron) {
  document.querySelectorAll('.shortcut-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.cron === cron);
  });
}

function schedToggleDow(btn) {
  btn.classList.toggle('selected');
  schedOnCronSelect();
}

function schedUpdateDesc(cron) {
  var desc = schedFormatCron(cron);
  var next = schedEstimateNext(cron);
  var el = document.getElementById('sched-cron-desc');
  if (el) el.innerHTML = '⏰ <strong>' + desc + '</strong> — Next run: <span id="sched-cron-next">' + next + '</span>';
}

function schedEstimateNext(cron) {
  var parts = cron.split(' ');
  var minute = parts[0], hour = parts[1];
  var now = new Date();
  var h = hour === '*' ? now.getUTCHours() : parseInt(hour);
  var m = minute === '*' ? 0 : parseInt(minute);
  if (isNaN(h)) h = now.getUTCHours();
  if (isNaN(m)) m = 0;
  if (minute === '*' || minute.startsWith('*/')) { m = Math.ceil(now.getUTCMinutes() / 5) * 5; if (m >= 60) { m = 0; h = (h + 1) % 24; } }
  var next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), h, m, 0));
  if (next <= now) next = new Date(next.getTime() + 24 * 60 * 60 * 1000);
  var dowParts = parts[4];
  if (dowParts && dowParts !== '*') {
    var allowed = dowParts.split(',').map(Number);
    var attempts = 0;
    while (attempts < 14 && allowed.indexOf((next.getUTCDay() === 0 ? 6 : next.getUTCDay() - 1)) === -1) {
      next = new Date(next.getTime() + 24 * 60 * 60 * 1000);
      attempts++;
    }
  }
  return next.toUTCString().replace(' GMT', ' UTC');
}

/* ── PAYLOAD EDITOR ── */
function schedAddPayload() {
  var container = document.getElementById('sched-payload-rows');
  var row = document.createElement('div');
  row.className = 'payload-row';
  row.innerHTML = '<input class="key-input" placeholder="Key"><input placeholder="Value"><button class="remove-btn" onclick="schedRemovePayload(this)">×</button>';
  container.appendChild(row);
}

function schedRemovePayload(btn) {
  var row = btn.closest('.payload-row');
  if (document.querySelectorAll('.payload-row').length > 1) {
    row.remove();
  } else {
    schedToast('At least one parameter is required', 'error');
  }
}

function schedGetPayload() {
  var params = {};
  document.querySelectorAll('#sched-payload-rows .payload-row').forEach(function(row) {
    var key = row.querySelector('.key-input').value.trim();
    var val = row.querySelector('input:not(.key-input)').value.trim();
    if (key) params[key] = val;
  });
  return params;
}

/* ── SAVE ── */
function schedSave() {
  var name = document.getElementById('sched-input-name').value.trim();
  var description = document.getElementById('sched-input-desc').value.trim();
  var targetId = document.getElementById('sched-input-target').value;
  var targetName = '';
  for (var i = 0; i < SCHED_AGENTS.length; i++) {
    if (SCHED_AGENTS[i].id === targetId) { targetName = SCHED_AGENTS[i].name; break; }
  }
  var params = schedGetPayload();
  if (!name) { schedToast('Please enter a schedule name', 'error'); document.getElementById('sched-input-name').focus(); return; }
  if (!targetId) { schedToast('Please select an agent type', 'error'); return; }
  if (schedEditingId) {
    var s = schedData.find(function(x) { return x.id === schedEditingId; });
    if (s) {
      s.name = name; s.description = description; s.cron_expression = schedSelectedCron;
      s.target_id = targetId; s.target_name = targetName; s.input_params = params;
      schedToast('Schedule "' + name + '" updated', 'success');
    }
  } else {
    var newId = 'sch-' + String(schedNextId++).padStart(3, '0');
    schedData.unshift({ id: newId, name: name, description: description, cron_expression: schedSelectedCron, target_id: targetId, target_name: targetName, status: 'active', input_params: params, created_at: new Date().toISOString().split('T')[0] });
    schedToast('Schedule "' + name + '" created', 'success');
  }
  schedCloseDialog();
  schedRender();
}

/* ── EXECUTION HISTORY ── */
function schedShowHistory(scheduleId) {
  schedHistoryFilterId = scheduleId;
  var s = schedData.find(function(x) { return x.id === scheduleId; });
  document.getElementById('sched-history-name').textContent = s ? s.name : '—';
  document.getElementById('sched-history-title').textContent = 'Execution History — ' + (s ? s.name : '');
  document.getElementById('sched-history-filter').value = 'all';
  schedRenderHistory();
  document.getElementById('sched-history-dialog').classList.add('open');
}

function schedCloseHistory(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById('sched-history-dialog').classList.remove('open');
  schedHistoryFilterId = null;
}

function schedRenderHistory() {
  var tbody = document.getElementById('sched-history-body');
  if (!tbody) return;
  var filter = document.getElementById('sched-history-filter').value;
  var items = schedExecHistory.filter(function(e) { return e.schedule_id === schedHistoryFilterId; });
  if (filter !== 'all') items = items.filter(function(e) { return e.status === filter; });
  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-secondary)">No execution history found.</td></tr>';
    document.getElementById('sched-history-info').textContent = '0 of 0';
    return;
  }
  tbody.innerHTML = items.map(function(e) {
    var badge = '';
    if (e.status === 'success') badge = '<span class="exec-status-badge exec-success">Success</span>';
    else if (e.status === 'failure') badge = '<span class="exec-status-badge exec-failure">Failure</span>';
    else badge = '<span class="exec-status-badge exec-running">Running</span>';
    var sessionHtml = e.agent_session
      ? '<span class="session-chip session-' + e.agent_session.status + '">' + e.agent_session.status + '</span>'
      : '<span class="text-secondary text-sm">—</span>';
    var errHtml = e.error_message
      ? '<span style="color:var(--error);font-size:12px">' + e.error_message + '</span>'
      : '<span class="text-secondary text-sm">—</span>';
    var openBtn = e.agent_session
      ? '<button class="btn-icon-sm" title="View agent result" onclick="schedShowExecDetail(\'' + e.agent_session.id + '\')" style="color:var(--primary)">↗</button>'
      : '';
    return '<tr>' +
      '<td class="text-sm">' + (e.started_at || '—') + '</td>' +
      '<td class="text-sm">' + (e.finished_at || '—') + '</td>' +
      '<td>' + badge + '</td>' +
      '<td>' + sessionHtml + '</td>' +
      '<td>' + errHtml + '</td>' +
      '<td style="text-align:center">' + openBtn + '</td></tr>';
  }).join('');
  document.getElementById('sched-history-info').textContent = items.length + ' execution(s)';
}

/* ── EXECUTION DETAIL ── */
function schedShowExecDetail(sessionId) {
  var exec = null;
  for (var i = 0; i < schedExecHistory.length; i++) {
    if (schedExecHistory[i].agent_session && schedExecHistory[i].agent_session.id === sessionId) {
      exec = schedExecHistory[i]; break;
    }
  }
  var session = exec ? exec.agent_session : { id: sessionId, status: 'unknown' };
  document.getElementById('sched-exec-detail-body').innerHTML =
    '<div class="detail-section">' +
      '<div class="detail-row"><span class="detail-label">Session ID</span><span class="detail-value mono">' + session.id + '</span></div>' +
      '<div class="detail-row"><span class="detail-label">Status</span><span class="detail-value"><span class="chip chip-' + (session.status === 'completed' ? 'green' : (session.status === 'failed' || session.status === 'terminated' ? 'red' : 'blue')) + '">' + session.status + '</span></span></div>' +
      (exec ? '<div class="detail-row"><span class="detail-label">Schedule</span><span class="detail-value">' + exec.schedule_name + '</span></div>' : '') +
      (exec ? '<div class="detail-row"><span class="detail-label">Started</span><span class="detail-value mono">' + exec.started_at + '</span></div>' : '') +
      (exec ? '<div class="detail-row"><span class="detail-label">Finished</span><span class="detail-value mono">' + (exec.finished_at || '—') + '</span></div>' : '') +
      (exec ? '<div class="detail-row"><span class="detail-label">Error</span><span class="detail-value" style="color:' + (exec.error_message ? 'var(--error)' : 'var(--success)') + '">' + (exec.error_message || 'None') + '</span></div>' : '') +
    '</div>' +
    '<div class="detail-section">' +
      '<div style="font-size:13px;font-weight:600;margin-bottom:10px">Execution Logs</div>' +
      '<div style="background:#FAFBFC;border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;font-family:\'Courier New\',monospace;font-size:11px;line-height:1.8;color:var(--text-secondary);max-height:200px;overflow-y:auto">' +
        '<div>[' + (exec ? exec.started_at : '...') + '] Session started: ' + session.id + '</div>' +
        '<div>[2026-06-08 08:00:02] Target agent resolved</div>' +
        '<div>[2026-06-08 08:00:03] Instance allocated: inst-' + session.id + '</div>' +
        '<div>[2026-06-08 08:00:05] Input parameters validated</div>' +
        (exec && exec.status === 'success' ? '<div>[' + (exec.finished_at || '...') + '] Execution completed successfully</div>' : '') +
        (exec && exec.status === 'failure' ? '<div style="color:var(--error)">[' + (exec.finished_at || '...') + '] Execution failed: ' + exec.error_message + '</div>' : '') +
        (exec && exec.status === 'running' ? '<div>[2026-06-08 ...] Execution in progress...</div>' : '') +
      '</div>' +
    '</div>';
  document.getElementById('sched-exec-detail-dialog').classList.add('open');
}

function schedCloseExecDetail(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById('sched-exec-detail-dialog').classList.remove('open');
}

/* ── TOAST ── */
function schedToast(message, type) {
  var container = document.getElementById('sched-toast-container');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'sched-toast sched-' + (type || 'info');
  var icons = { success: '✓', error: '✕', info: 'ℹ' };
  toast.innerHTML = '<span>' + (icons[type] || 'ℹ') + '</span> ' + message;
  container.appendChild(toast);
  setTimeout(function() { if (toast.parentNode) toast.remove(); }, 3000);
}

/* ── SCHEDULE KEYBOARD & BACKDROP ── */
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    if (document.getElementById('sched-exec-detail-dialog').classList.contains('open')) schedCloseExecDetail();
    else if (document.getElementById('sched-history-dialog').classList.contains('open')) schedCloseHistory();
    else if (document.getElementById('modal-schedule').classList.contains('open')) schedCloseDialog();
  }
});

// ═══════════════════════════════ CHAT ═══════════════════════════════
var dvChatTimers = [];
var dvSnippetExpanded = false;
var dvExecutionStreamTimer = null;
var dvExecutionStreamIndex = 0;

function dvClearChatTimers() {
  for (var i = 0; i < dvChatTimers.length; i += 1) {
    window.clearTimeout(dvChatTimers[i]);
  }
  dvChatTimers = [];
}

function dvUpdateSnippetHeader() {
  var list = document.getElementById('dvSnippetList');
  var meta = document.getElementById('dvSnippetMeta');
  var preview = document.getElementById('dvSnippetPreview');
  if (!list || !meta || !preview) return;

  var lines = list.querySelectorAll('.snippet-line');
  meta.textContent = 'Folded by default - ' + lines.length + ' snippets';
  preview.textContent = lines.length > 0
    ? lines[lines.length - 1].textContent
    : 'No delegation snippets yet.';
}

function dvToggleSnippet(forceExpanded) {
  var body = document.getElementById('dvSnippetBody');
  var toggleText = document.getElementById('dvSnippetToggleText');
  if (!body || !toggleText) return;

  if (typeof forceExpanded === 'boolean') {
    dvSnippetExpanded = forceExpanded;
  } else {
    dvSnippetExpanded = !dvSnippetExpanded;
  }
  body.classList.toggle('open', dvSnippetExpanded);
  toggleText.textContent = dvSnippetExpanded ? 'Hide Details' : 'Show Details';
}

function dvAddSnippetLine(text) {
  var list = document.getElementById('dvSnippetList');
  if (!list) return;
  var line = document.createElement('div');
  line.className = 'snippet-line';
  line.textContent = text;
  list.appendChild(line);
  dvUpdateSnippetHeader();
}

function dvSetChatStatus(mode, text, dotted) {
  var status = document.getElementById('dvChatStatus');
  var statusText = document.getElementById('dvChatStatusText');
  var dots = document.getElementById('dvChatDots');
  if (!status || !statusText || !dots) return;
  status.className = 'status-pill show';
  status.classList.add('status-' + mode);
  statusText.textContent = text;
  dots.style.display = dotted ? 'inline-flex' : 'none';
}

function dvResetChatPrototype() {
  dvClearChatTimers();
  var status = document.getElementById('dvChatStatus');
  var list = document.getElementById('dvSnippetList');
  var viewLogsWrap = document.getElementById('dvViewLogsWrap');
  if (status) status.className = 'status-pill';
  if (list) list.innerHTML = '';
  if (viewLogsWrap) viewLogsWrap.style.display = 'none';
  dvToggleSnippet(false);
  dvUpdateSnippetHeader();
}

function dvPlayDelegationFlow(isTimeout) {
  dvResetChatPrototype();
  dvSetChatStatus('thinking', 'Thinking…', true);

  dvChatTimers.push(window.setTimeout(function() {
    dvSetChatStatus('delegating', 'Delegating to agent risk-auditor', false);
    dvAddSnippetLine('Delegating to agent risk-auditor');
  }, 900));

  dvChatTimers.push(window.setTimeout(function() {
    dvSetChatStatus('waiting', 'Waiting for delegated response…', true);
    dvAddSnippetLine('Waiting for delegated response…');
  }, 1900));

  dvChatTimers.push(window.setTimeout(function() {
    dvAddSnippetLine('Using tool evidence-scan…');
  }, 3000));

  dvChatTimers.push(window.setTimeout(function() {
    var viewLogsWrap = document.getElementById('dvViewLogsWrap');
    if (isTimeout) {
      dvSetChatStatus('fail', 'Delegated step timed out or failed. Please try again.', false);
      dvAddSnippetLine('[10:42:18] delegated execution timeout threshold reached');
      return;
    }
    dvSetChatStatus('done', 'Delegation completed by risk-auditor', false);
    dvAddSnippetLine('[10:42:18] delegated response merged into conversation output');
    if (viewLogsWrap) viewLogsWrap.style.display = 'block';
  }, 4300));
}

function dvSetStepState(index, state) {
  var step = document.getElementById('dvStep' + (index + 1));
  if (!step) return;
  step.classList.remove('active', 'done');
  if (state) step.classList.add(state);
}

function dvAppendLiveLogLine(level, text) {
  var log = document.getElementById('dvLiveLog');
  if (!log) return;
  var row = document.createElement('div');
  row.className = 'log-line log-' + level;
  row.innerHTML = "<span class='lvl'>[" + level.toUpperCase() + "]</span> " + text;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function dvResetExecutionStream() {
  if (dvExecutionStreamTimer) {
    window.clearInterval(dvExecutionStreamTimer);
  }
  dvExecutionStreamTimer = null;
  dvExecutionStreamIndex = 0;

  var log = document.getElementById('dvLiveLog');
  var state = document.getElementById('dvRunState');
  if (log) log.innerHTML = '';
  if (state) state.textContent = 'Idle';

  for (var i = 0; i < 4; i += 1) {
    dvSetStepState(i, null);
  }
}

function dvStartExecutionStream() {
  dvResetExecutionStream();
  var state = document.getElementById('dvRunState');
  if (state) state.textContent = 'Live stream: connected';
  dvSetStepState(0, 'active');

  var streamLines = [
    { level: 'info', text: '10:43:01 {"type":"log_entry","entry":{"event_type":"session_queued"}}' },
    { level: 'info', text: '10:43:02 {"type":"log_entry","entry":{"event_type":"planner_initialized"}}' },
    { level: 'info', text: '10:43:04 {"type":"log_entry","entry":{"event_type":"iteration_started"}}' },
    { level: 'warn', text: '10:43:07 {"type":"log_entry","entry":{"event_type":"external_latency_warning"}}' },
    { level: 'info', text: '10:43:09 {"type":"log_entry","entry":{"event_type":"tool_call","tool":"policy-index.fetch"}}' },
    { level: 'info', text: '10:43:12 {"type":"log_entry","entry":{"event_type":"tool_call","tool":"risk-correlation.compute"}}' },
    { level: 'info', text: '10:43:18 {"type":"stream_completed","session_status":"completed"}' },
  ];

  dvExecutionStreamTimer = window.setInterval(function() {
    if (dvExecutionStreamIndex >= streamLines.length) {
      window.clearInterval(dvExecutionStreamTimer);
      dvExecutionStreamTimer = null;
      if (state) state.textContent = 'Stream completed (session terminal)';
      dvSetStepState(3, 'done');
      return;
    }

    var next = streamLines[dvExecutionStreamIndex];
    dvAppendLiveLogLine(next.level, next.text);

    if (dvExecutionStreamIndex === 1) {
      dvSetStepState(0, 'done');
      dvSetStepState(1, 'active');
    }
    if (dvExecutionStreamIndex === 3) {
      dvSetStepState(1, 'done');
      dvSetStepState(2, 'active');
    }
    if (dvExecutionStreamIndex === 5) {
      dvSetStepState(2, 'done');
      dvSetStepState(3, 'active');
    }

    dvExecutionStreamIndex += 1;
  }, 700);
}

function dvStopExecutionStream() {
  if (dvExecutionStreamTimer) {
    window.clearInterval(dvExecutionStreamTimer);
    dvExecutionStreamTimer = null;
  }
  var state = document.getElementById('dvRunState');
  if (state) state.textContent = 'Stopped';
}

function sendChatMsg() {
  var input = document.getElementById('chat-input');
  var text = (input.value || '').trim();
  if (!text) return;
  var msgs = document.getElementById('chat-messages');

  // User bubble
  var userMsg = document.createElement('div');
  userMsg.className = 'msg msg-user';
  userMsg.innerHTML = '<div class="msg-bubble">' + escHtml(text) + '</div>';
  msgs.appendChild(userMsg);
  input.value = '';

  // Simulated agent response
  setTimeout(function() {
    var agentMsg = document.createElement('div');
    agentMsg.className = 'msg msg-agent';
    agentMsg.innerHTML = '<div style="width:28px;height:28px;border-radius:50%;background:#E0E7FF;color:#4338CA;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0">DA</div>' +
      '<div class="msg-bubble">I\'ve received your message and I\'m processing it. One moment...</div>';
    msgs.appendChild(agentMsg);
    msgs.scrollTop = msgs.scrollHeight;
  }, 800);

  msgs.scrollTop = msgs.scrollHeight;
}

function answerQuestion(answer) {
  var msgs = document.getElementById('chat-messages');
  // Remove the question card
  var qcard = document.querySelector('.msg-question');
  if (qcard) {
    var wrapper = qcard.closest('div[style]');
    if (wrapper) wrapper.remove();
  }
  // Add user answer
  var userMsg = document.createElement('div');
  userMsg.className = 'msg msg-user';
  userMsg.innerHTML = '<div class="msg-bubble">' + escHtml(answer) + '</div>';
  msgs.appendChild(userMsg);
  // Agent confirmation
  setTimeout(function() {
    var agentMsg = document.createElement('div');
    agentMsg.className = 'msg msg-agent';
    agentMsg.innerHTML = '<div style="width:28px;height:28px;border-radius:50%;background:#E0E7FF;color:#4338CA;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0">DA</div>' +
      '<div class="msg-bubble">Got it! I\'ll include the Year-over-Year comparison in the analysis. Generating the updated report...</div>';
    msgs.appendChild(agentMsg);
    msgs.scrollTop = msgs.scrollHeight;
  }, 600);
  msgs.scrollTop = msgs.scrollHeight;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ═══════════════════════════════ TOOL FILTER ═══════════════════════════════
function filterTools(q) {
  q = q.toLowerCase();
  document.querySelectorAll('#tool-groups tbody tr').forEach(function(row) {
    var text = row.textContent.toLowerCase();
    row.style.display = text.includes(q) ? '' : 'none';
  });
}
function filterToolsByServer(server) {
  document.querySelectorAll('.tool-group').forEach(function(grp) {
    var title = grp.querySelector('h4');
    if (!server || (title && title.textContent.trim() === server)) {
      grp.style.display = '';
    } else {
      grp.style.display = 'none';
    }
  });
}

function updateSecurityAuditWsUrl() {
  var sessionId = (document.getElementById('sec-audit-session-id')?.value || '').trim() || 'session-123';
  var convId = (document.getElementById('sec-audit-conv-id')?.value || '').trim();
  var token = (document.getElementById('sec-audit-token')?.value || '').trim();
  var wsUrl = '/ws/sessions/' + sessionId + '?token=' + encodeURIComponent(token);
  if (convId) wsUrl += '&conv_session_id=' + encodeURIComponent(convId);
  var output = document.getElementById('sec-audit-ws-url');
  if (output) output.textContent = wsUrl;
}

function runSecurityAuditProbe() {
  var status = document.getElementById('sec-audit-probe-status');
  var note = document.getElementById('sec-audit-probe-note');
  if (status) {
    status.className = 'chip chip-red';
    status.textContent = 'Probe Result: Denied (401/403)';
  }
  if (note) {
    note.textContent = 'Internal endpoint access without service certificate is denied under caller-scoped allowlist policy.';
  }
}

function setExecutionLogMode(mode) {
  var friendly = document.getElementById('execution-log-friendly');
  var raw = document.getElementById('execution-log-raw');
  if (!friendly || !raw) return;
  friendly.style.display = mode === 'raw' ? 'none' : 'block';
  raw.style.display = mode === 'raw' ? 'block' : 'none';
}

// ENHANCE-AGENT-OUTPUT-SYSTEM: exec log tab switching
function exSwitchTab(tab, btn) {
  document.querySelectorAll('#executionDetailsModal .exec-tab').forEach(function(t){ t.classList.remove('active'); });
  document.querySelectorAll('#executionDetailsModal .exec-tab-content').forEach(function(c){ c.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  var target = document.getElementById('exec-tab-' + tab);
  if (target) target.classList.add('active');
}
window.exSwitchTab = exSwitchTab;

        // Dynamic Policy Statement
        let statementCount = 1;
        function addStatement() {
            statementCount++;
            const list = document.getElementById('policy-list');
            const div = document.createElement('div');
            div.className = 'policy-statement';
            div.innerHTML = `
                <div class="policy-header">
                    <h4>Statement ${statementCount}</h4>
                    <button class="btn btn-danger" style="padding: 4px 8px;" onclick="this.parentElement.parentElement.remove()">Remove</button>
                </div>
                <div class="policy-row">
                    <div class="policy-col">
                        <label class="form-label">Module</label>
                        <select class="form-control">
                            <option value="agents">Agents</option>
                            <option value="mcp-hub">MCP Hub</option>
                            <option value="skills">Skills</option>
                            <option value="scheduling">Scheduling</option>
                        </select>
                    </div>
                    <div class="policy-col">
                        <label class="form-label">Resource Scope</label>
                        <select class="form-control" onchange="toggleResourceIds(this)">
                            <option value="all">All Resources</option>
                            <option value="specific">Specific IDs...</option>
                        </select>
                        <div class="resource-ids-section" style="display:none; margin-top:8px;">
                            <div style="display:flex; gap:8px; margin-bottom:6px;">
                                <input type="text" class="form-control resource-id-input" placeholder="e.g. agent_001 or support_*">
                                <button class="btn btn-primary" style="white-space:nowrap;" onclick="addResourceIdChip(this)">Add</button>
                            </div>
                            <div class="resource-id-chips" style="display:flex; flex-wrap:wrap; gap:6px; min-height:28px;"></div>
                            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">Wildcards supported (e.g. support_* matches all IDs starting with support_)</div>
                        </div>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Actions Allowed</label>
                    <div class="checkbox-group">
                        <label class="checkbox-label"><input type="checkbox"> View</label>
                        <label class="checkbox-label"><input type="checkbox"> Create</label>
                        <label class="checkbox-label"><input type="checkbox"> Edit</label>
                        <label class="checkbox-label"><input type="checkbox"> Delete</label>
                        <label class="checkbox-label"><input type="checkbox"> Execute</label>
                    </div>
                </div>
                <div class="form-group" style="margin-bottom:0;">
                    <label class="form-label">Tag Conditions (AND)</label>
                    <div class="empty-state" style="padding:10px;">No conditions applied.</div>
                    <button class="btn" style="margin-top: 8px;" onclick="alert('Add condition dialog')">+ Add Condition</button>
                </div>
            `;
            list.appendChild(div);
        }

        // Fix 1: Tag Value Chips
        function openTagModal() {
            const container = document.getElementById('tagValueChips');
            container.innerHTML = '';
            ['test', 'prod'].forEach(function(v) {
                const chip = document.createElement('span');
                chip.className = 'chip-tag';
                chip.innerHTML = v + ' <span class="chip-remove" onclick="this.parentElement.remove()">\u00d7</span>';
                container.appendChild(chip);
            });
            document.getElementById('newTagValue').value = '';
            openModal('modal-tag');
        }

        function addTagValueChip() {
            const input = document.getElementById('newTagValue');
            const val = input.value.trim();
            if (!val) return;
            const container = document.getElementById('tagValueChips');
            const chip = document.createElement('span');
            chip.className = 'chip-tag';
            chip.innerHTML = val + ' <span class="chip-remove" onclick="this.parentElement.remove()">\u00d7</span>';
            container.appendChild(chip);
            input.value = '';
            input.focus();
        }

        var newTagValueEl = document.getElementById('newTagValue');
        if (newTagValueEl) newTagValueEl.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); addTagValueChip(); }
        });

        // Fix 2a: Resource ID chips
        function toggleResourceIds(select) {
            const section = select.parentElement.querySelector('.resource-ids-section');
            if (section) section.style.display = select.value === 'specific' ? 'block' : 'none';
        }

        function addResourceIdChip(btn) {
            const section = btn.closest('.resource-ids-section');
            const input = section.querySelector('.resource-id-input');
            const val = input.value.trim();
            if (!val) return;
            const container = section.querySelector('.resource-id-chips');
            const chip = document.createElement('span');
            chip.className = 'chip-tag';
            chip.innerHTML = val + ' <span class="chip-remove" onclick="this.parentElement.remove()">\u00d7</span>';
            container.appendChild(chip);
            input.value = '';
            input.focus();
        }

        // Fix 2b: Tag value dropdown
        const TAG_VALUES = {
            'env': ['test', 'prod'],
            'agent_type': ['support', 'monitoring', 'reporting']
        };

        function updateTagValueDropdown(keySelect) {
            const row = keySelect.closest('.tag-condition');
            const valueSelect = row.querySelector('.tag-val-select');
            const key = keySelect.value;
            if (!key) {
                valueSelect.innerHTML = '<option value="" disabled selected>Select key first</option>';
                valueSelect.disabled = true;
            } else {
                valueSelect.disabled = false;
                const opts = TAG_VALUES[key] || [];
                valueSelect.innerHTML = opts.map(function(v) { return '<option value="' + v + '">' + v + '</option>'; }).join('');
            }
        }

        // Fix 3: Manage Access modal
        function openManageAccess(userName) {
            document.getElementById('manage-access-user-name').textContent = userName;
            switchManageTab('tab-direct-roles');
            openModal('modal-manage-access');
        }

        function switchManageTab(tabId) {
            document.querySelectorAll('.manage-tab-panel').forEach(function(p) { p.style.display = 'none'; });
            document.querySelectorAll('.manage-tab-btn').forEach(function(b) { b.classList.remove('active'); });
            document.getElementById(tabId).style.display = 'block';
            document.querySelector('[data-tab="' + tabId + '"]').classList.add('active');
        }

        function assignRole() {
            const sel = document.getElementById('assign-role-select');
            const val = sel.value;
            if (!val) return;
            const list = document.getElementById('direct-roles-list');
            const div = document.createElement('div');
            div.className = 'tag-condition';
            div.style.justifyContent = 'space-between';
            div.innerHTML = '<span>' + val + '</span><button class="btn btn-danger" style="padding:4px 8px;" onclick="this.parentElement.remove()">Remove</button>';
            list.appendChild(div);
            sel.value = '';
        }

        function assignGroup() {
            const sel = document.getElementById('assign-group-select');
            const val = sel.value;
            if (!val) return;
            const list = document.getElementById('group-memberships-list');
            const div = document.createElement('div');
            div.className = 'tag-condition';
            div.style.justifyContent = 'space-between';
            div.innerHTML = '<span>' + val + '</span><button class="btn btn-danger" style="padding:4px 8px;" onclick="this.parentElement.remove()">Remove</button>';
            list.appendChild(div);
            sel.value = '';
        }

        // Fix 4: Request form validation
        function updateRequestSubmit() {
            const anyChecked = Array.from(document.querySelectorAll('.request-group-cb')).some(function(cb) { return cb.checked; });
            const hasJustification = document.getElementById('requestJustification').value.trim().length > 0;
            document.getElementById('btn-submit-request').disabled = !(anyChecked && hasJustification);
        }

        // Fix 5: Reject reason validation
        function updateRejectConfirm() {
            const reason = document.getElementById('rejectReason').value.trim();
            document.getElementById('btn-confirm-reject').disabled = !reason;
        }
    
/* ── multi-tenant support (relocated) ── */
// ═══════════════════════════════ MULTI-TENANT SUPPORT (merged from docs/changes/multi-tenant-support) ═══════════════════════════════
/* Unified workspace-address login, root-tenant platform model, Tenant Admin group, quotas/licensing.
   Root workspace = the platform tenant; platform modules visible only to platform-role members there. */
var mtCurrentSlug = null;
var MT_WORKSPACES = {
  root:   {name:'Root'},
  acme:   {name:'Acme Corp'},
  globex: {name:'Globex Industries'}
};
var MT_TIERS = {
  free:       {label:'Free',       users:10},
  team:       {label:'Team',       users:50},
  enterprise: {label:'Enterprise', users:500}
};
var MT_TENANTS = [
  {slug:'root',    name:'Root',               tier:'enterprise', status:'Active',    users:3,  execs:0},
  {slug:'demo',    name:'Parthenon Demo Org', tier:'enterprise', status:'Active',    users:12, execs:3200},
  {slug:'acme',    name:'Acme Corp',          tier:'free',       status:'Active',    users:10, execs:42},
  {slug:'globex',  name:'Globex Industries',  tier:'team',       status:'Active',    users:9,  execs:1240},
  {slug:'northwind',name:'Northwind Ltd',     tier:'team',       status:'Suspended', users:15, execs:610}
];
var MT_MEMBERS = {
  acme: [
    {name:'Alex Rivera', email:'alex@acme.com',   role:'Tenant Admin', status:'Active',  root:true},
    {name:'Sam Chen',    email:'sam@example.com', role:'Member',       status:'Active',  root:false},
    {name:'Priya Patel', email:'priya@acme.com',  role:'Member',       status:'Invited', root:false}
  ]
};

/* ── Find-workspace step ── */
function mtFindClear() {
  document.getElementById('mt-find-slug').classList.remove('error');
  document.getElementById('mt-find-err').style.display = 'none';
}
function mtFindErr(msg) {
  var e = document.getElementById('mt-find-err');
  e.textContent = msg; e.style.display = 'block';
  document.getElementById('mt-find-slug').classList.add('error');
}
function mtQuick(slug) {
  document.getElementById('mt-find-slug').value = slug;
  mtFindSubmit();
}
function mtFindSubmit() {
  mtFindClear();
  var slug = (document.getElementById('mt-find-slug').value || '').trim().toLowerCase();
  if (!slug) { mtFindErr('Enter your workspace address.'); return; }
  if (!MT_WORKSPACES[slug]) { mtFindErr('No workspace found at this address.'); return; }
  mtPickWorkspace(slug);
}
function mtPickWorkspace(slug) {
  mtCurrentSlug = slug;
  var name = MT_WORKSPACES[slug].name;
  document.getElementById('mt-ws-line').innerHTML = 'Signing in to <strong>' + name + '</strong> (<span class="font-mono">' + slug + '.parthenon.app</span>)';
  /* Break-glass entry: only at the root workspace card (or with no workspace bound) */
  document.getElementById('mt-breakglass-link').style.display = (slug === 'root') ? 'block' : 'none';
  document.getElementById('mt-breakglass-form').style.display = 'none';
  oidcSetState('both');
}
function mtToggleBreakglass() {
  var f = document.getElementById('mt-breakglass-form');
  f.style.display = f.style.display === 'none' ? 'block' : 'none';
}

/* ── Workspace binding after sign-in: topbar chip + nav gating ── */
function mtBindWorkspace(slug, isPlatform) {
  mtCurrentSlug = slug;
  var t = MT_TENANTS.find(function(x){return x.slug===slug;});
  var name = (t && t.name) || (MT_WORKSPACES[slug] && MT_WORKSPACES[slug].name) || slug;
  var chip = document.getElementById('tenant-ctx-chip');
  chip.style.display = 'inline-flex';
  document.getElementById('tenant-ctx-name').textContent = name + (slug==='root' && isPlatform ? ' · Platform Admin' : '');
  /* Platform = root tenant: Platform group only at root for platform-role members */
  document.getElementById('nav-platform').style.display = (slug === 'root' && isPlatform) ? 'block' : 'none';
  document.getElementById('nav-tenant-admin').style.display = 'block';
  /* Break-glass button on the workspace sign-in card: root only */
  var saBtn = document.getElementById('oidc-sa-btn-both');
  if (saBtn) saBtn.style.display = (slug === 'root') ? 'block' : 'none';
  mtRenderMembers(slug, name);
  mtRenderTenants();
  var alias = document.getElementById('mt-alias-input'); if (alias) alias.value = name;
  var addr = document.getElementById('mt-addr-fixed'); if (addr) addr.value = slug;
  var mw = document.getElementById('mt-members-ws'); if (mw) mw.textContent = name;
  var mi = document.getElementById('mt-idp-ws'); if (mi) mi.textContent = name;
}

/* ── Tenant members + quota ── */
function mtTenant(slug) { return MT_TENANTS.find(function(x){return x.slug===(slug||mtCurrentSlug);}); }
function mtRenderMembers(slug, name) {
  var rows = document.getElementById('mt-member-rows'); if (!rows) return;
  slug = slug || mtCurrentSlug;
  if (!MT_MEMBERS[slug]) MT_MEMBERS[slug] = [{name:'Workload Owner', email:'owner@' + slug + '.com', role:'Tenant Admin', status:'Active', root:true}];
  var t = mtTenant(slug), tier = MT_TIERS[t ? t.tier : 'free'];
  var full = t && t.users >= tier.users;
  var chip = document.getElementById('mt-quota-chip');
  chip.textContent = t.users + '/' + tier.users + ' users · ' + tier.label + ' tier';
  chip.className = 'chip ' + (full ? 'chip-red' : 'chip-gray');
  document.getElementById('mt-quota-blocked').style.display = 'none';
  rows.innerHTML = MT_MEMBERS[slug].map(function(m) {
    var role = '<span class="chip chip-blue">' + m.role + '</span>' + (m.root ? ' <span class="chip chip-gray">🌱 Root</span>' : '');
    var actions = m.root
      ? '<span class="text-secondary" style="font-size:11px">🔒 Locked</span>'
      : '<button class="btn btn-sm btn-secondary" onclick="toast(\'Member actions (demo)\',\'info\')">Manage</button>';
    var status = m.status === 'Active' ? '<span class="chip chip-green">Active</span>' : '<span class="chip chip-yellow">Invited</span>';
    return '<tr><td style="font-weight:500">' + m.name + '</td><td class="font-mono" style="font-size:12px">' + m.email + '</td><td>' + role + '</td><td>' + status + '</td><td style="text-align:right">' + actions + '</td></tr>';
  }).join('');
}
function mtInvite() {
  var t = mtTenant(); if (!t) return;
  var tier = MT_TIERS[t.tier];
  if (t.users >= tier.users) {
    document.getElementById('mt-quota-blocked').style.display = 'flex';
    toast('Invitation blocked — user quota reached (' + tier.label + ' tier)', 'error');
    return;
  }
  t.users++;
  mtRenderMembers(); mtRenderTenants();
  toast('Invitation sent (demo) — now ' + t.users + ' / ' + tier.users + ' users on ' + tier.label + ' tier', 'success');
}

/* ── Tenant settings ── */
function mtSaveAlias() {
  var v = (document.getElementById('mt-alias-input').value || '').trim();
  if (!v) { toast('Alias cannot be empty', 'error'); return; }
  var t = mtTenant(); if (t) t.name = v;
  document.getElementById('tenant-ctx-name').textContent = v;
  document.getElementById('mt-members-ws').textContent = v;
  document.getElementById('mt-idp-ws').textContent = v;
  mtRenderTenants();
  toast('Alias updated — workspace renamed to "' + v + '" everywhere instantly (address unchanged)', 'success');
}

/* ── Platform tenants registry ── */
function mtRenderTenants() {
  var rows = document.getElementById('mt-tenant-rows'); if (!rows) return;
  rows.innerHTML = MT_TENANTS.map(function(t) {
    var tierCls = t.tier === 'team' ? 'chip-blue' : t.tier === 'enterprise' ? 'chip-purple' : 'chip-gray';
    var nameHtml = '<strong>' + t.name + '</strong>' + (t.slug === 'root' ? ' <span class="chip chip-gray">Root tenant</span>' : '');
    var status = t.status === 'Active' ? '<span class="chip chip-green">Active</span>' : '<span class="chip chip-red">Suspended</span>';
    return '<tr><td>' + nameHtml + '</td>' +
      '<td class="font-mono" style="font-size:12px">' + t.slug + '.parthenon.app</td>' +
      '<td><span class="chip ' + tierCls + '">' + MT_TIERS[t.tier].label + '</span></td>' +
      '<td>' + status + '</td><td>' + t.users + '</td><td>' + t.execs.toLocaleString() + '</td>' +
      '<td><div style="display:flex;gap:4px;justify-content:flex-end">' +
      '<button class="btn btn-sm btn-secondary" onclick="toast(\'Suspend / resume (demo)\',\'info\')">Suspend</button>' +
      '<button class="btn btn-sm btn-secondary" onclick="mtAssignLicense(\'' + t.slug + '\')">License</button>' +
      '</div></td></tr>';
  }).join('');
}
function mtAssignLicense(slug) {
  var t = MT_TENANTS.find(function(x){return x.slug===slug;}); if (!t) return;
  t.tier = t.tier === 'free' ? 'team' : t.tier === 'team' ? 'enterprise' : 'free';
  mtRenderTenants();
  toast(MT_TIERS[t.tier].label + ' tier applied to "' + t.name + '" — usage meters update immediately (demo cycles tiers)', 'success');
}

/* ── Toast (relocated from the runtime-monitor script so every page has one) ── */
function showToast(msg,type){
  var wrap=document.getElementById('rm-toast-wrap');
  if(!wrap){ window.toast(msg,type); return; }
  var t=document.createElement('div');
  t.className='toast '+(type||'info');
  t.textContent=msg;
  wrap.appendChild(t);
  setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); },3200);
}

/* ── Escape closes the modal-style pickers (relocated) ── */
document.addEventListener('keydown',function(e){
if(e.key==='Escape'){['tenantPickerModal','dctDialog','soDialog'].forEach(function(id){var el=document.getElementById(id);if(el)el.style.display='none';});}
});

/* ═══════════════════════════════════════════════════════════════════════════
   MULTI-PAGE BOOTSTRAP (added when the single-file prototype was modularised)
   The prototype used to be one document with 38 `view-*` panels switched by
   nav(el, viewId). It is now a hub + module pages. This block keeps every old
   handler working:
     • showView('x') for a view that lives on another page navigates there
     • the sidebar uses real <a href="page.html#view-x"> links
     • #view-x in the URL selects the view on load and on hashchange
   ═══════════════════════════════════════════════════════════════════════════ */
var PAGE_OF_VIEW = {"dashboard": "index","project-showcase": "index","setup-wizard": "index","agents": "agents","agent-roles": "agents","agent-identities": "agents","agent-management-panel": "agent-panel","agent-executions": "executions","runtime-monitor": "executions","agent-trails": "executions","agent-logs": "executions","skills": "skills-sops","sops": "skills-sops","data-types": "data-results","agent-outputs": "data-results","results": "data-results","schedules": "schedules","mcp-hub": "integrations","notifications": "integrations","api-keys": "integrations","agent-clients": "integrations","gateway": "integrations","system-config": "system","model-configs": "system","permissions": "system","observability": "system","security-audit": "system","decision-tools": "decision","sysone-providers": "decision","tenant-settings": "tenancy","tenant-members": "tenancy","tenant-identity-providers": "tenancy","platform-settings": "tenancy","platform-tenants": "tenancy","platform-audit": "tenancy","chat": "chat","conversational-intervention": "chat","intervene-requests": "chat"};
var PAGE_FILES = {"index": "index.html","agents": "modules/agents.html","agent-panel": "modules/agent-panel.html","executions": "modules/executions.html","skills-sops": "modules/skills-sops.html","data-results": "modules/data-results.html","schedules": "modules/schedules.html","integrations": "modules/integrations.html","system": "modules/system.html","decision": "modules/decision.html","tenancy": "modules/tenancy.html","chat": "modules/chat.html"};
var MODAL_PAGE = {"dash-demo-panel": "index","dash-toast-container": "index","tenantPickerModal": "index","modal-role": "agents","modal-agent-role": "agents","modal-agent-type": "agents","agentTypeDetailsModal": "agents","roleViewModal": "agents","identityViewModal": "agents","planModal": "agents","modal-optimized-plan": "agents","modal-opt-script": "agents","amp-modal-overlay": "agent-panel","amp-picker-overlay": "agent-panel","amp-fs-overlay": "agent-panel","amp-toasts": "agent-panel","executionDetailsModal": "executions","skill-tool-modal": "skills-sops","modal-wf-skill-editor": "skills-sops","modal-wf-sop-editor": "skills-sops","modal-wf-preview": "skills-sops","dtDialog": "data-results","dtDeleteDialog": "data-results","aoDrawerOverlay": "data-results","aoDrawer": "data-results","maxDialogOverlay": "data-results","drawer-result-overlay": "data-results","drawer-result": "data-results","modal-schedule": "schedules","sched-history-dialog": "schedules","sched-exec-detail-dialog": "schedules","sched-toast-container": "schedules","modal-mcp-server": "integrations","modal-notif": "integrations","modal-sessions": "integrations","modal-session-form": "integrations","modal-mcp-server-form": "integrations","modal-test-tool": "integrations","modal-assign-sessions": "integrations","acCreateModal": "integrations","acEditModal": "integrations","acCredModal": "integrations","akCreateDialog": "integrations","akRevokeDialog": "integrations","modal-model-config": "system","modal-model-config-delete": "system","modal-model-config-error": "system","modal-model-config-cascade": "system","oidc-modal-test-config": "system","oidc-modal-test-login": "system","dctDialog": "decision","soDialog": "decision","drawer-overlay": "chat","drawer-sessions": "chat","drawer-conv-overlay": "chat","drawer-conv": "chat"};
var CURRENT_PAGE = document.body.getAttribute('data-page') || 'index';

function protoBase() { return CURRENT_PAGE === 'index' ? '' : '../'; }
function protoPageUrl(pageKey) { return protoBase() + PAGE_FILES[pageKey]; }
function protoGoToView(viewId) {
  var page = PAGE_OF_VIEW[viewId];
  if (!page) return false;
  location.href = protoPageUrl(page) + '#view-' + viewId;
  return true;
}

/* Any view id that is not in this document is a cross-page jump. */
var __showViewLocal = showView;
showView = function (viewId) {
  if (document.getElementById('view-' + viewId)) { __showViewLocal(viewId); return; }
  if (!protoGoToView(viewId)) __showViewLocal(viewId);
};
window.showView = showView;

/* A dialog that lives on another module page is opened by navigating there.
   (Legacy screens in System Config / Permissions still point at the Agent Type
   and Agent Role dialogs, which belong to the Agents page.) */
var __openModalLocal = openModal;
openModal = function (modalId) {
  if (document.getElementById(modalId)) { __openModalLocal(modalId); return; }
  var page = MODAL_PAGE[modalId];
  if (!page) { __openModalLocal(modalId); return; }
  location.href = protoPageUrl(page) + '?modal=' + modalId;
};
window.openModal = openModal;

function protoActivate(viewId) {
  if (!viewId) return;
  var el = document.getElementById('view-' + viewId);
  if (!el) { protoGoToView(viewId); return; }
  showView(viewId);
  document.querySelectorAll('.nav-item').forEach(function (i) { i.classList.remove('active'); });
  document.querySelectorAll('.nav-parent-group').forEach(function (g) { g.classList.remove('active'); });
  var nav = document.querySelector('.nav-item[data-view="' + viewId + '"]');
  if (nav) {
    nav.classList.add('active');
    var grp = nav.closest('.nav-parent-group');
    if (grp) grp.classList.add('active');
  }
  var title = document.getElementById('topbar-title');
  if (title && viewTitles[viewId]) title.textContent = viewTitles[viewId];
}

/* Fallback toast: some legacy handlers call toast() but its owner lives on
   another module page. Pages that define their own toast() override this. */
window.toast = window.toast || function (msg, type) {
  var box = document.getElementById('proto-toast-box');
  if (!box) {
    box = document.createElement('div');
    box.id = 'proto-toast-box';
    box.className = 'proto-toast-box';
    document.body.appendChild(box);
  }
  var t = document.createElement('div');
  t.className = 'proto-toast proto-toast-' + (type || 'info');
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(function () { t.classList.add('out'); }, 2600);
  setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 3100);
};
window.mcFlashToast = window.mcFlashToast || function (msg) { window.toast(msg, 'info'); };

/* Restore the mocked tenant context so the Platform group keeps working on
   every page (the login page itself lives on the hub). */
function protoRestoreTenant() {
  try {
    var slug = localStorage.getItem('ph_tenant_slug') || 'root';
    var platform = localStorage.getItem('ph_tenant_platform') !== '0';
    if (typeof mtBindWorkspace === 'function') mtBindWorkspace(slug, slug === 'root' ? platform : false);
  } catch (e) { /* tenant chrome is cosmetic in the prototype */ }
}

function protoBoot() {
  protoRestoreTenant();
  var hash = (location.hash || '').replace(/^#/, '');
  var view = hash.indexOf('view-') === 0 ? hash.slice(5) : document.body.getAttribute('data-default-view');
  protoActivate(view);
  /* a dialog requested by another page (?modal=modal-agent-type) */
  var m = /[?&]modal=([\w-]+)/.exec(location.search || '');
  if (m && document.getElementById(m[1])) setTimeout(function () { __openModalLocal(m[1]); }, 0);
  document.querySelectorAll('.nav-parent-group.locked-open').forEach(function (g) { g.classList.remove('collapsed'); });
  /* page-local initialisers — each view that owns one is only on its own page */
  try { if (typeof schedRender === 'function' && document.getElementById('sched-rows')) schedRender(); } catch (e) {}
  try { if (typeof dvResetChatPrototype === 'function' && document.getElementById('chat-messages')) dvResetChatPrototype(); } catch (e) {}
  try { if (typeof dvResetExecutionStream === 'function' && document.getElementById('chat-messages')) dvResetExecutionStream(); } catch (e) {}
  try { if (typeof toggleAgentTypeFields === 'function' && document.getElementById('agent-input-type')) toggleAgentTypeFields(); } catch (e) {}
  try { if (typeof toggleAgentOutputTypeFields === 'function' && document.getElementById('agent-input-type')) toggleAgentOutputTypeFields(); } catch (e) {}
  try { if (typeof mcRenderTable === 'function' && document.getElementById('mc-table-body')) mcRenderTable(); } catch (e) {}
  try { if (typeof updateSecurityAuditWsUrl === 'function' && document.getElementById('sa-ws-url')) updateSecurityAuditWsUrl(); } catch (e) {}
}
window.addEventListener('hashchange', function () {
  var hash = (location.hash || '').replace(/^#/, '');
  if (hash.indexOf('view-') === 0) protoActivate(hash.slice(5));
});
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', protoBoot);
else protoBoot();
