import re

master_file = '../docs/master/ux/prototype/index.html'
change_file = '../docs/changes/user-permission-management/prototype/index.html'

with open(master_file, 'r', encoding='utf-8') as f:
    master = f.read()

with open(change_file, 'r', encoding='utf-8') as f:
    change = f.read()

# EXTRACT VIEWS
views_to_add = []
views = re.findall(r'<div class="view" id="([^"]+)".*?<!-- End View -->', change, re.DOTALL)
for raw_view in re.finditer(r'<div class="view" id="([^"]+)".*?<!-- End View -->', change, re.DOTALL):
    vid = raw_view.group(1)
    if f'id="{vid}"' not in master:
        views_to_add.append(raw_view.group(0))

if views_to_add:
    main_end = master.rfind('</main>')
    master = master[:main_end] + '\n\n' + '\n\n'.join(views_to_add) + '\n' + master[main_end:]

# EXTRACT NAV
nav_group = re.search(r'<div class="nav-parent-group.*?>\s*<div class="nav-parent.*?Identity & Access.*?</div>\s*<div class="nav-children">(.*?)</div>\s*</div>', change, re.DOTALL)
if nav_group:
    navs = nav_group.group(1)
    # inject into master's Identity & Access 
    master = re.sub(r'(<div class="nav-parent".*?Identity & Access.*?</div>\s*<div class="nav-children">)', r'\1' + '\n' + navs, master, flags=re.DOTALL)

# EXTRACT MODALS
modals_to_add = []
for modal in re.finditer(r'<div class="modal(?:-overlay)?" id="([^"]+)".*?</div>\s*</div>', change, re.DOTALL):
    mid = modal.group(1)
    if f'id="{mid}"' not in master:
        modals_to_add.append(modal.group(0))

if modals_to_add:
    body_end = master.rfind('</body>')
    master = master[:body_end] + '\n\n' + '\n\n'.join(modals_to_add) + '\n' + master[body_end:]

# EXTRACT JS
scripts = re.search(r'<script>(.*?)</script>', change, re.DOTALL)
if scripts:
    master_script_end = master.rfind('</script>')
    master = master[:master_script_end] + '\n' + scripts.group(1) + '\n' + master[master_script_end:]

with open(master_file, 'w', encoding='utf-8') as f:
    f.write(master)

print(f"Added {len(views_to_add)} views.")
print(f"Added {len(modals_to_add)} modals.")
