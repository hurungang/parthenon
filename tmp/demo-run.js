process.chdir('C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\e2e');
process.env.DEMO_SPEED = 'normal';
const patterns = [
  "Permission Denied: Snackbar.*403 on agent create triggers permission-denied snackbar",
  "Permission Denied: Request Access Flow.*user can submit access request with justification and sees confirmation",
  "AccessDeniedPage.*renders at /access-denied with lock icon and action buttons"
];
const grep = patterns.join('|');
process.argv = ['node', 'pw', 'test', '--headed', '--config', 'playwright.demo.config.ts', '--grep', grep, '--project=chromium'];
require('C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\e2e\\node_modules\\@playwright\\test\\cli.js');
