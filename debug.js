const { JSDOM } = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync('/Users/minglijiang/source/parthenon/docs/master/ux/prototype/index.html','utf8');
const dom = new JSDOM(html, { runScripts:'dangerously', pretendToBeVisual:true });
const { window } = dom;
const { document } = window;
setTimeout(()=>{
  window.nav(null,'agent-management-panel');
  console.log('agent items:', document.querySelectorAll('.amp-agent-item').length);
  console.log('agent list html len:', document.getElementById('amp-agent-list').innerHTML.length);
  console.log('list snippet:', document.getElementById('amp-agent-list').innerHTML.slice(0,200));
  // create agent flow
  window.AMP.openCreateAgent();
  document.getElementById('f-ag-name').value='master-test-agent';
  document.getElementById('f-ag-si').value='instruction';
  const btns = document.querySelectorAll('#amp-modal-footer .btn-primary');
  console.log('primary btns:', btns.length);
  btns[btns.length-1].click();
  const names = Array.from(document.querySelectorAll('.amp-agent-item-name')).map(e=>e.textContent);
  console.log('names after create:', JSON.stringify(names));
  console.log('modal still open:', document.getElementById('amp-modal-overlay').classList.contains('open'));
  console.log('name err visible:', document.getElementById('f-ag-name-err').textContent);
  process.exit(0);
}, 500);
