// Temporary script to run notification demo with grep patterns
// Windows shell can't handle | in --grep argument, so we use Node.js

process.chdir('C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\e2e');
process.env.DEMO_SPEED = 'normal';

const grepPatterns = [
  'Notification Channel Management > create channel updates list without page reload',
  'Recipient Group Management > create group updates list without page reload',
  'Notification Log Page > clicking a log row opens the detail view',
  'Real Backend Integration - Notifications > notification channels endpoint returns 200'
];

const grep = grepPatterns.join('|');

process.argv = [
  'node',
  'playwright',
  'test',
  '--headed',
  '--config',
  'playwright.demo.config.ts',
  '--grep',
  grep,
  '--project=chromium'
];

require('C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\e2e\\node_modules\\@playwright\\test\\cli.js');
