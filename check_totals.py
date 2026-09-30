import json, os, re, subprocess, tempfile  # independent cross-check + multi-file merge regression
K = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"); rows = [r for r in map(json.loads, open("sample_transcript.jsonl", encoding="utf-8")) if r.get("type") == "assistant"]
uniq = {r["message"]["id"]: r["message"]["usage"] for r in rows}; mine = [sum(u.get(k, 0) for u in uniq.values()) for k in K]; naive = [sum(r["message"]["usage"].get(k, 0) for r in rows) for k in K]
theirs = [int(x.replace(",", "")) for x in re.search(r"\| all \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|", open("out/costs.md", encoding="utf-8").read()).groups()]
print("assistant lines=%d unique msgs=%d  [input, output, cache_read, cache_create]\nnaive (no dedupe) = %s\nindependent dedup = %s\ncosts.md totals   = %s\n%s" % (len(rows), len(uniq), naive, mine, theirs, "MATCH" if mine == theirs else "MISMATCH")); assert mine == theirs

# multi-file: split the sample in half, parse both parts together, outputs must equal the single-file run
raw = open("sample_transcript.jsonl", encoding="utf-8").read().splitlines(); half = len(raw) // 2
with tempfile.TemporaryDirectory() as td:
    p1, p2 = os.path.join(td, "a.jsonl"), os.path.join(td, "b.jsonl")
    open(p1, "w", encoding="utf-8").write("\n".join(raw[:half])); open(p2, "w", encoding="utf-8").write("\n".join(raw[half:]))
    od = os.path.join(td, "out")
    r = subprocess.run(["python3", "receipt.py", p1, p2, "--out", od], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    norm = lambda p: [l for l in open(p, encoding="utf-8").read().splitlines() if not l.startswith("Source:")]
    assert norm(os.path.join(od, "costs.md")) == norm("out/costs.md"), "multi-file costs.md differs"
    for f in ("receipt-2026-09-25.md", "receipt-2026-09-26.md", "receipt-2026-09-27.md"):
        assert open(os.path.join(od, f), encoding="utf-8").read() == open(os.path.join("out", f), encoding="utf-8").read(), f + " differs"
print("multi-file merge: IDENTICAL")
