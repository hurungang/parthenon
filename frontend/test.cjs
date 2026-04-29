const fs = require('fs');
const str = fs.readFileSync('../docs/changes/user-permission-management/prototype/index.html', 'utf8');
const views = str.match(/<div class="view" id="[^"]+">/g);
console.log(views);
