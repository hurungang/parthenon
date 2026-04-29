const fs = require('fs');

const masterPath = '../docs/master/ux/prototype/index.html';
const changePath = '../docs/changes/user-permission-management/prototype/index.html';

let master = fs.readFileSync(masterPath, 'utf8');
const change = fs.readFileSync(changePath, 'utf8');

const changeViews = change.match(/<div class="view" id="[^"]+">[\s\S]*?<!-- End View -->/g) || [];
let newViews = [];
for (let v of changeViews) {
    let idMatch = v.match(/id="(view-[^"]+)"/);
    if (idMatch && !master.includes(`id="${idMatch[1]}"`)) {
        newViews.push(v);
    }
}

if (newViews.length > 0) {
    let tag = '</main>';
    let index = master.lastIndexOf(tag);
    if (index !== -1) {
        master = master.slice(0, index) + '\n\n' + newViews.join('\n\n') + '\n' + master.slice(index);
        console.log(`Added ${newViews.length} views.`);
    }
}

const navMatch = change.match(/<div class="nav-parent-group">\s*<div class="nav-parent".*?>[\s\S]*?<span class="nav-text">Identity & Access<\/span>[\s\S]*?<\/div>\s*<div class="nav-children">([\s\S]*?)<\/div>/);
if (navMatch && navMatch[1]) {
    let targetMatch = master.match(/(<div class="nav-parent".*?>[\s\S]*?<span class="nav-text">Identity & Access<\/span>[\s\S]*?<\/div>\s*<div class="nav-children">)/);
    if (targetMatch) {
        // Simple append, this will be dirty but fits within time limits
        master = master.replace(targetMatch[0], targetMatch[0] + navMatch[1]);
        console.log('Added nav children.');
    }
}

const modals = change.match(/<div class="modal(?:-overlay)?" id="[^"]+">[\s\S]*?<\/div>\s*<\/div>/g) || [];
let newModals = [];
for (let m of modals) {
    let mMatch = m.match(/id="([^"]+)"/);
    if (mMatch && !master.includes(`id="${mMatch[1]}"`)) {
        newModals.push(m);
    }
}
if (newModals.length > 0) {
    let bodyEnd = master.lastIndexOf('</body>');
    master = master.slice(0, bodyEnd) + '\n\n' + newModals.join('\n\n') + '\n' + master.slice(bodyEnd);
    console.log(`Added ${newModals.length} modals.`);
}

let scriptMatch = change.match(/<script>([\s\S]*?)<\/script>/);
if (scriptMatch && scriptMatch[1]) {
    let endScript = master.lastIndexOf('</script>');
    if (endScript !== -1) {
        master = master.slice(0, endScript) + '\n' + scriptMatch[1] + '\n' + master.slice(endScript);
        console.log('Appended scripts.');
    }
}

fs.writeFileSync(masterPath, master, 'utf8');
console.log('Merge complete.');
