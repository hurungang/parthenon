#!/usr/bin/env python3
"""Syntax-check every inline <script> block of the modularised prototype."""
import os, re, subprocess, sys, tempfile

ROOT = sys.argv[1] if len(sys.argv) > 1 else "tmp/ux_split"
fail = 0
for dirpath, _, names in os.walk(ROOT):
    for n in sorted(names):
        if not n.endswith(".html"):
            continue
        p = os.path.join(dirpath, n)
        txt = open(p, encoding="utf-8").read()
        for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', txt, re.S), 1):
            body = m.group(1)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write(body)
                tmp = f.name
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                fail += 1
                line = txt[:m.start()].count("\n") + 1
                print(f"FAIL {p} block#{i} (html line {line})")
                print(r.stderr.splitlines()[:6])
            os.unlink(tmp)
print("inline blocks failing:", fail)
