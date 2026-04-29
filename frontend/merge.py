import re
import os

master_path = r'../docs/master/ux/prototype/index.html'
change_path = r'../docs/changes/user-permission-management/prototype/index.html'

with open(master_path, 'r', encoding='utf-8') as f:
    master = f.read()

with open(change_path, 'r', encoding='utf-8') as f:
    change = f.read()

# Find the views in change
import bs4 # wait, bs4 might not be installed

# Let's extract between <!-- VIEWS START --> and <!-- VIEWS END --> if they exist, or just use regex.
change_views = re.findall(r'<div class="view".*?id="view-.*?</div>\s*(?=<!--|$|<div class="view")', change, re.DOTALL)
master_views_container_end = master.find('</main>')

new_views = []
for v in change_views:
    # check if view ID is already in master
    match = re.search(r'id="(view-[^"]+)"', v)
    if match:
        vid = match.group(1)
        if vid not in master:
            new_views.append(v)

# Also extract nav items
nav_block = re.search(r'<div class="nav-parent-group.*?>.*?<span class="nav-text">Identity & Access</span>.*?</div>\s*</div>', change, re.DOTALL)
if nav_block and nav_block.group(0) not in master:
    # try to append to sidebar
    sidebar_end = master.find('</nav>')
    if sidebar_end != -1:
        master = master[:sidebar_end] + "\n" + nav_block.group(0) + "\n" + master[sidebar_end:]

if master_views_container_end != -1:
    master = master[:master_views_container_end] + "\n\n" + "\n\n".join(new_views) + "\n" + master[master_views_container_end:]

with open(master_path, 'w', encoding='utf-8') as f:
    f.write(master)

print(f"Added {len(new_views)} views.")
