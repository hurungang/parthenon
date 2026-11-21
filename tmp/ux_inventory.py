#!/usr/bin/env python3
"""Inventory top-level blocks of the master UX prototype (read-only)."""
import re, json, sys

SRC = "docs/master/ux/prototype/index.html"
lines = open(SRC, encoding="utf-8").read().split("\n")

blocks = []
i = 0
N = len(lines)
while i < N:
    ln = lines[i]
    if ln.startswith("<script>") or ln.startswith("<script "):
        j = i + 1
        while j < N and not lines[j].startswith("</script>"):
            j += 1
        blocks.append({"kind": "script", "start": i + 1, "end": j + 1, "lines": j + 1 - i})
        i = j + 1
        continue
    if ln.startswith("<style>"):
        j = i + 1
        while j < N and not lines[j].startswith("</style>"):
            j += 1
        blocks.append({"kind": "style", "start": i + 1, "end": j + 1, "lines": j + 1 - i})
        i = j + 1
        continue
    if ln.startswith("<div"):
        if "</div>" in ln:
            blocks.append({"kind": "one-line-div", "start": i + 1, "end": i + 1, "lines": 1,
                           "text": ln[:120]})
            i += 1
            continue
        j = i + 1
        while j < N and lines[j].rstrip() != "</div>" and not lines[j].startswith("</div><!--"):
            j += 1
        seg = "\n".join(lines[i:j + 1])
        m = re.search(r'id="([^"]+)"', lines[i])
        blocks.append({"kind": "div", "start": i + 1, "end": j + 1, "lines": j + 1 - i,
                       "id": m.group(1) if m else None,
                       "text": lines[i][:130]})
        i = j + 1
        continue
    if ln.startswith("<nav"):
        j = i + 1
        while j < N and not lines[j].startswith("</nav>"):
            j += 1
        blocks.append({"kind": "nav", "start": i + 1, "end": j + 1, "lines": j + 1 - i})
        i = j + 1
        continue
    i += 1

total = 0
for b in blocks:
    total += b["lines"]
    print(f'{b["start"]:6d}-{b["end"]:6d} {b["lines"]:5d}  {b["kind"]:12s} {b.get("id") or b.get("text","")}')
print("TOTAL blocks", len(blocks), "lines", total)
