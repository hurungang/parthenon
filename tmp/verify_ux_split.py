#!/usr/bin/env python3
"""Verification for the modularised UX prototype."""
import os, re, sys, collections

ROOT = sys.argv[1] if len(sys.argv) > 1 else "tmp/ux_split"
files = []
for dirpath, _, names in os.walk(ROOT):
    for n in names:
        if n.endswith((".html", ".js", ".css")):
            files.append(os.path.join(dirpath, n))
files.sort()

print("=== files")
for f in files:
    txt = open(f, encoding="utf-8").read()
    print(f"{len(txt.splitlines()):6d} lines {len(txt.encode()):8d} bytes  {os.path.relpath(f, ROOT)}")

html_files = [f for f in files if f.endswith(".html")]

print("\n=== 1. view ids")
ids = collections.Counter()
per_page = collections.defaultdict(list)
for f in html_files:
    txt = open(f, encoding="utf-8").read()
    for m in re.finditer(r'id="(view-[a-z0-9-]+)"', txt):
        ids[m.group(1)] += 1
        per_page[m.group(1)].append(os.path.relpath(f, ROOT))
print("distinct view ids:", len(ids))
dups = {k: v for k, v in ids.items() if v > 1}
print("duplicates:", dups if dups else "none")

print("\n=== 2. forbidden patterns")
bad = collections.defaultdict(list)
for f in files:
    txt = open(f, encoding="utf-8").read()
    for pat in ["fetch(", 'type="module"', "http://", "https://", "import "]:
        if pat in txt:
            for i, line in enumerate(txt.splitlines(), 1):
                if pat in line:
                    bad[pat].append((os.path.relpath(f, ROOT), i, line.strip()[:120]))
for pat in ["fetch(", 'type="module"', "http://", "https://"]:
    hits = bad.get(pat, [])
    print(f"{pat!r}: {len(hits)}")
    for h in hits[:40]:
        print("   ", h)

print("\n=== 3. relative href/src resolution")
broken = []
for f in html_files:
    base = os.path.dirname(f)
    txt = open(f, encoding="utf-8").read()
    for m in re.finditer(r'(?:href|src)="([^"]+)"', txt):
        u = m.group(1)
        if u.startswith("#") or u.startswith("javascript:") or u.startswith("data:") or u.startswith("mailto:"):
            continue
        if re.match(r'^[a-z]+:', u):
            broken.append((f, u, "absolute scheme"))
            continue
        target = u.split("#")[0]
        if not target:
            continue
        p = os.path.normpath(os.path.join(base, target))
        if not os.path.exists(p):
            broken.append((os.path.relpath(f, ROOT), u, p))
print("broken:", len(broken))
for b in broken:
    print("   ", b)

print("\n=== 4. page links")
index_txt = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
for f in html_files:
    rel = os.path.relpath(f, ROOT)
    txt = open(f, encoding="utf-8").read()
    if rel != "index.html":
        back = "href=\"../index.html" in txt
        print(f"  {rel:34s} links back to index: {back}")
print("  index -> module pages:")
for m in sorted(set(re.findall(r'href="(modules/[a-z-]+\.html)', index_txt))):
    print("   ", m, "OK" if os.path.exists(os.path.join(ROOT, m)) else "MISSING")

print("\n=== 5. inline handler identifiers vs defined functions (rough)")
missing_all = {}
for f in html_files:
    txt = open(f, encoding="utf-8").read()
    defined = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)', txt))
    defined |= set(re.findall(r'window\.([A-Za-z_$][\w$]*)\s*=', txt))
    defined |= set(re.findall(r'(?:var|const|let)\s+([A-Za-z_$][\w$]*)\s*=', txt))
    jsfiles = [os.path.join(ROOT, "shared", f) for f in
               ["app.js", "assistant.js", "page-init.js", "max-dialog.js", "oidc.js", "workflow.js"]]
    if "index.html" in os.path.basename(f):
        jsfiles.append(os.path.join(ROOT, "shared", "login.js"))
    for j in jsfiles:
        jt = open(j, encoding="utf-8").read()
        defined |= set(re.findall(r'function\s+([A-Za-z_$][\w$]*)', jt))
        defined |= set(re.findall(r'window\.([A-Za-z_$][\w$]*)\s*=', jt))
        defined |= set(re.findall(r'var\s+([A-Za-z_$][\w$]*)\s*=', jt))
    used = set()
    for m in re.finditer(r'on(?:click|change|input|keydown|submit)="([^"]+)"', txt):
        for name in re.findall(r'([A-Za-z_$][\w$]*)\s*\(', m.group(1)):
            used.add(name)
    builtin = {"if", "return", "event", "location", "alert", "confirm", "document", "window",
               "setTimeout", "parseInt", "parseFloat", "String", "Number", "encodeURIComponent",
               "console", "this", "typeof", "new", "Date", "Math", "JSON", "Object", "Array"}
    miss = sorted(n for n in used - defined - builtin)
    if miss:
        missing_all[os.path.relpath(f, ROOT)] = miss
for k, v in missing_all.items():
    print(f"  {k}: {', '.join(v)}")
