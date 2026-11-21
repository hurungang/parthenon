/* Parthenon UX prototype — OIDC provider configuration tabs (System Config → Identity
   Providers). Relocated from the single-file prototype; loaded by the hub (login screen)
   and by the System page (identity-provider tabs). */
/* ── OIDC Config Tabs ── */
function oidcSwitchConfigTab(tabEl, panelId) {
  tabEl.parentElement.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});
  tabEl.classList.add('active');
  document.querySelectorAll('#view-system-config .tab-panel').forEach(function(p){p.classList.remove('active');});
  document.getElementById(panelId).classList.add('active');
}

/* ── OIDC Advanced Toggle ── */
function oidcToggleAdvanced(id) {
  var p = document.getElementById(id);
  var t = document.getElementById(id.replace('advanced','advanced-toggle'));
  if (p.classList.contains('open')) { p.classList.remove('open'); if(t) t.innerHTML='▶ Advanced Options'; }
  else { p.classList.add('open'); if(t) t.innerHTML='▼ Advanced Options'; }
}

/* ── Password Toggle ── */
function oidcTogglePw(fieldId, btn) {
  var f = document.getElementById(fieldId);
  if (f.type==='password') { f.type='text'; btn.textContent='🙈'; }
  else { f.type='password'; btn.textContent='👁️'; }
}

/* ── Badge Updates ── */
function oidcUpdateBadges() {
  var t = document.getElementById('oidc-user-type').value;
  var b = document.getElementById('oidc-user-badge');
  if (t) { b.textContent = t.replace(/_/g,' '); b.className='config-badge configured'; }
  else { b.textContent='Not Configured'; b.className='config-badge not-configured'; }
}
function oidcUpdateAgentBadge() {
  var t = document.getElementById('oidc-agent-type').value;
  var b = document.getElementById('oidc-agent-badge');
  if (t) { b.textContent = t.replace(/_/g,' '); b.className='config-badge configured'; }
  else { b.textContent='Not Configured'; b.className='config-badge not-configured'; }
}

/* ── Sync Agent from User ── */
function oidcSyncAgent() {
  var c = document.getElementById('oidc-agent-same').checked;
  var fields = ['type','name','issuer','ui-client','client-id','secret','scopes','claims'];
  fields.forEach(function(f){
    var a = document.getElementById('oidc-agent-'+f);
    var u = document.getElementById('oidc-user-'+f);
    if (a&&u) { if(c){ a.value=u.value; a.disabled=true; a.style.background='#F5F5F5'; } else { a.disabled=false; a.style.background=''; } }
  });
  if (c) oidcUpdateAgentBadge();
}

/* ── Save Provider ── */
function oidcSaveProvider(scope) {
  mcFlashToast(scope==='user'?'User identity provider saved.':'Agent identity provider saved.');
  if (scope==='user') oidcUpdateBadges(); else oidcUpdateAgentBadge();
}

/* ── Super Admin Toggle ── */
function oidcToggleSA() {
  var t = document.getElementById('oidc-toggle-sa');
  if (!t.checked) {
    oidcSuperAdminEnabled = false;
    document.getElementById('oidc-sa-warn-disabled').style.display='block';
    document.getElementById('oidc-sa-warn-enabled').style.display='none';
    document.getElementById('oidc-sa-indicator').style.display='none';
    document.getElementById('oidc-sa-chip').textContent='Disabled';
    document.getElementById('oidc-sa-chip').className='chip chip-red';
    mcFlashToast('Super admin login disabled.');
  } else {
    oidcSuperAdminEnabled = true;
    document.getElementById('oidc-sa-warn-disabled').style.display='none';
    document.getElementById('oidc-sa-warn-enabled').style.display='block';
    document.getElementById('oidc-sa-indicator').style.display=oidcLoggedInSA?'inline-flex':'none';
    document.getElementById('oidc-sa-chip').textContent='Enabled';
    document.getElementById('oidc-sa-chip').className='chip chip-green';
    mcFlashToast('Super admin login enabled.');
  }
}

/* ── Test Config Modal ── */
function oidcTestConfig(target) {
  oidcTestTarget = target;
  var pre=document.getElementById('oidc-test-config-pre'), run=document.getElementById('oidc-test-config-running'), res=document.getElementById('oidc-test-config-result');
  pre.style.display='block';run.style.display='none';res.style.display='none';
  document.getElementById('oidc-btn-retry-test').style.display='none';
  for (var i=1;i<=4;i++){ var s=document.getElementById('oidc-step-'+i); s.className='test-step'; s.querySelector('.step-icon').textContent='○'; }
  document.getElementById('oidc-test-config-target').textContent = target==='user'?'User Identity Provider':'Agent Identity Provider';
  document.getElementById('oidc-test-config-title').innerHTML = '🔍 Test OIDC Config &mdash; '+(target==='user'?'User':'Agent')+' Provider';
  var p=target==='user'?'user':'agent';
  document.getElementById('oidc-test-issuer').textContent=document.getElementById('oidc-'+p+'-issuer').value||'https://auth.example.com/realms/my-realm';
  document.getElementById('oidc-test-client-id').textContent=document.getElementById('oidc-'+p+'-ui-client').value||'parthenon-api-ui';
  openModal('oidc-modal-test-config');
}

function oidcRunTestConfig() {
  document.getElementById('oidc-test-config-pre').style.display='none';
  document.getElementById('oidc-test-config-running').style.display='block';
  document.getElementById('oidc-test-config-result').style.display='none';
  document.getElementById('oidc-btn-retry-test').style.display='none';
  var rid=++oidcLoginTestRun;
  var steps=[
    {id:'oidc-step-1',d:800,t:'Discovery document fetched — issuer: https://auth.example.com/.well-known/openid-configuration',i:'✓',c:'done'},
    {id:'oidc-step-2',d:1600,t:'Issuer URL matches discovery document — validation passed',i:'✓',c:'done'},
    {id:'oidc-step-3',d:2400,t:'JWKS endpoint reachable — 3 keys found (RS256 x2, ES256 x1)',i:'✓',c:'done'},
    {id:'oidc-step-4',d:3200,t:'Client credentials valid — token endpoint returned 200 OK',i:'✓',c:'done'}
  ];
  steps.forEach(function(s){setTimeout(function(){if(rid!==oidcLoginTestRun)return;var st=document.getElementById(s.id);st.className='test-step '+s.c;st.querySelector('.step-icon').textContent=s.i;st.querySelector('span:last-child').textContent=s.t;},s.d);});
  setTimeout(function(){if(rid!==oidcLoginTestRun)return;
    document.getElementById('oidc-test-config-running').style.display='none';
    document.getElementById('oidc-test-config-result').style.display='block';
    document.getElementById('oidc-btn-retry-test').style.display='inline-flex';
    document.getElementById('oidc-test-config-result-content').innerHTML='<div class="alert alert-success" style="margin-bottom:16px"><div><strong style="display:block;margin-bottom:4px">✅ Configuration Valid</strong><p class="text-sm">All checks passed. The OIDC provider is reachable and correctly configured.</p></div></div><div class="section-title">Discovery Document</div><div class="test-result"><pre>{"issuer":"https://auth.example.com/realms/my-realm","authorization_endpoint":"https://auth.example.com/.../auth","token_endpoint":"https://auth.example.com/.../token","jwks_uri":"https://auth.example.com/.../certs"}</pre></div><div class="section-title">JWKS Status</div><div class="alert alert-info" style="margin-bottom:0"><div><p class="text-sm">JWKS endpoint returned 3 valid keys. All keys are not expired.</p></div></div>';
  },3800);
}

/* ── Test Login Modal ── */
function oidcTestLogin(target) {
  oidcTestLoginTarget = target;
  var pre=document.getElementById('oidc-test-login-pre'), run=document.getElementById('oidc-test-login-running'), res=document.getElementById('oidc-test-login-result');
  pre.style.display='block';run.style.display='none';res.style.display='none';
  document.getElementById('oidc-btn-retry-login').style.display='none';
  for (var i=1;i<=4;i++){ var s=document.getElementById('oidc-login-step-'+i); s.className='test-step'; s.querySelector('.step-icon').textContent='○'; }
  document.getElementById('oidc-test-login-target').textContent = target==='user'?'User Identity Provider':'Agent Identity Provider';
  document.getElementById('oidc-test-login-title').innerHTML = '🔑 Test OIDC Login &mdash; '+(target==='user'?'User':'Agent')+' Provider';
  openModal('oidc-modal-test-login');
}

function oidcRunTestLogin() {
  document.getElementById('oidc-test-login-pre').style.display='none';
  document.getElementById('oidc-test-login-running').style.display='block';
  document.getElementById('oidc-test-login-result').style.display='none';
  document.getElementById('oidc-btn-retry-login').style.display='none';
  var rid=++oidcLoginTestRun;
  var steps=[
    {id:'oidc-login-step-1',d:1000,t:'Authorization code flow initiated — redirect to https://auth.example.com/...',i:'✓',c:'done'},
    {id:'oidc-login-step-2',d:2000,t:'Callback completed — authorization code exchanged for tokens',i:'✓',c:'done'},
    {id:'oidc-login-step-3',d:3000,t:'ID token validated — signature OK, not expired, audience matches',i:'✓',c:'done'},
    {id:'oidc-login-step-4',d:4000,t:'User identity resolved — claims: preferred_username=jdoe, email=jdoe@example.com, roles=[admin,user]',i:'✓',c:'done'}
  ];
  steps.forEach(function(s){setTimeout(function(){if(rid!==oidcLoginTestRun)return;var st=document.getElementById(s.id);st.className='test-step '+s.c;st.querySelector('.step-icon').textContent=s.i;st.querySelector('span:last-child').textContent=s.t;},s.d);});
  setTimeout(function(){if(rid!==oidcLoginTestRun)return;
    document.getElementById('oidc-test-login-running').style.display='none';
    document.getElementById('oidc-test-login-result').style.display='block';
    document.getElementById('oidc-btn-retry-login').style.display='inline-flex';
    document.getElementById('oidc-test-login-result-content').innerHTML='<div class="alert alert-success" style="margin-bottom:16px"><div><strong style="display:block;margin-bottom:4px">✅ Login Successful</strong><p class="text-sm">Full OIDC authorization code flow completed. User identity returned with valid claims.</p></div></div><div class="section-title">Token Response</div><div class="test-result"><pre>{"access_token":"eyJhbGciOiJSUzI1NiIs...","token_type":"Bearer","expires_in":3600,"id_token":"eyJhbGciOiJSUzI1NiIs..."}</pre></div><div class="section-title">ID Token Claims</div><div class="test-result"><pre>{"iss":"https://auth.example.com/realms/my-realm","sub":"a1b2c3d4-...","aud":"parthenon-api-ui","preferred_username":"jdoe","email":"jdoe@example.com","groups":["admin","user"]}</pre></div>';
  },4600);
}
