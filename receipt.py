#!/usr/bin/env python3
"""receipt.py - turn Claude Code transcripts (JSONL) into daily Markdown receipts + a token cost report.

Usage: python3 receipt.py transcript.jsonl [more.jsonl ...] --out out/ [--prices prices.json]
Standard library only, Python 3.8+, Windows/Linux.
"""
import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_PRICES = {  # USD per 1M tokens
    "claude-sonnet-4-5": {"input": 3, "output": 15, "cache_creation": 3.75, "cache_read": 0.3},
    "claude-opus-4-1": {"input": 15, "output": 75, "cache_creation": 18.75, "cache_read": 1.5},
}
# (usage field, price key), in report column order
COLS = [("input_tokens", "input"), ("output_tokens", "output"),
        ("cache_read_input_tokens", "cache_read"), ("cache_creation_input_tokens", "cache_creation")]
MAX_LEN = 120


def clip(text, n=MAX_LEN):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


# placeholder-protected abbreviations so sentence splitting doesn't break on "e.g."
_ABBR = {"e.g.": "EGPROTECT", "i.e.": "IEPROTECT", "etc.": "ETCPROTECT", "vs.": "VSPROTECT",
         "Mr.": "MRPROTECT", "Ms.": "MSPROTECT", "Mrs.": "MRSPROTECT", "Dr.": "DRPROTECT", "St.": "STPROTECT"}
_FILLER = re.compile(r"^(?:hi|hey|hello|yo|ok|okay|so|yeah|yes|btw|pls|please|"
                     r"quick(?:\s+(?:one|question))?|just|um|uh|well)\b[\s,:\-–—]*", re.I)


def split_sentences(text):
    p = text
    for a, b in _ABBR.items():
        p = p.replace(a, b)
    parts = re.split(r"(?<=[.!?…])\s+|\n+", p)
    out = []
    for x in parts:
        for a, b in _ABBR.items():
            x = x.replace(b, a)
        out.append(x)
    return out


def intent(text):
    """One task line from a user message.

    Rules (heuristic): take the first sentence; if it is a question but a later
    sentence states something concrete, take the first statement instead (the
    question was just a preamble, e.g. "Quick question: does X expire? Add TTL
    support."). Abbreviations like "e.g." are protected from sentence splitting,
    and leading filler ("hey", "quick one") is stripped.
    """
    text = " ".join(text.split())
    sents = [s.strip(" \t,;:—-") for s in split_sentences(text)]
    sents = [s for s in sents if s]
    if not sents:
        return ""
    sents = [_FILLER.sub("", s) or s for s in sents]
    first = sents[0]
    if first.endswith("?") and len(sents) > 1:
        for s in sents[1:]:
            if s and not s.endswith("?"):
                return clip(s)
    return clip(first)


def text_blocks(content):
    if isinstance(content, str):
        return [content]
    return [b.get("text") or "" for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def tool_hint(inp, project):
    hint = ""
    if isinstance(inp, dict):
        hint = next((str(inp[k]) for k in ("file_path", "command", "pattern", "path", "url", "query", "description")
                     if inp.get(k)), "")
    p = project.rstrip("/\\")
    if hint[:len(p)] == p and hint[len(p):len(p) + 1] in ("/", "\\"):
        hint = hint[len(p) + 1:]
    return hint


def price_for(model, prices):
    """Exact match, else the longest key K where model == K-<suffix> (e.g. claude-sonnet-4-5-20250929)."""
    if model in prices:
        return prices[model]
    keys = [k for k in prices if model.startswith(k + "-")]
    return prices[max(keys, key=len)] if keys else None


def load_prices(path):
    prices = dict(DEFAULT_PRICES)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                extra = json.load(f)
        except (OSError, ValueError) as e:
            sys.exit("cannot read prices file %s: %s" % (path, e))
        if not isinstance(extra, dict):
            sys.exit("prices file must be a JSON object {model: {...}}")
        for model, p in extra.items():
            if not isinstance(p, dict) or not all(isinstance(p.get(k), (int, float)) for _, k in COLS):
                sys.exit("bad price entry for %r: need numeric input/output/cache_read/cache_creation" % model)
        prices.update(extra)
    return prices


def parse(paths):
    """Parse one or more transcript files, merging into shared day/project buckets."""
    days = defaultdict(lambda: defaultdict(lambda: {"tasks": [], "actions": [], "summaries": [], "sessions": set()}))
    usage = {}   # message.id -> {"key": (day, project, model), usage field: tokens}
    where = {}   # sessionId -> (day, project) of its latest line, for summaries lacking timestamp/cwd
    summaries, seen, stats = [], set(), defaultdict(int)

    def line(rec, n):
        kind, sid = rec.get("type"), rec.get("sessionId")
        ts, project = str(rec.get("timestamp") or ""), rec.get("cwd")
        if kind == "summary":
            summaries.append(rec)
            return
        if kind not in ("user", "assistant"):
            return
        if len(ts) < 16 or not project:
            stats["skipped_no_timestamp_or_cwd"] += 1
            return
        day, hhmm = ts[:10], ts[11:16]
        where[sid] = (day, project)
        group = days[day][project]
        group["sessions"].add(sid)
        msg = rec.get("message") or {}

        if kind == "user":
            if rec.get("isMeta"):
                return
            for t in text_blocks(msg.get("content")):
                if t.strip() and not t.lstrip().startswith("<"):  # skip <command-name>/<system-reminder> wrappers
                    group["tasks"].append((hhmm, intent(t)))
                    break
            return

        stats["assistant_lines"] += 1
        mid = msg.get("id") or "no-id-line-%d" % n
        model = rec.get("model") or msg.get("model") or "unknown"
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                act = clip("[%s] %s" % (b.get("name", "?"), tool_hint(b.get("input"), project)))
            elif b.get("type") == "text" and (b.get("text") or "").strip():
                act = clip(b["text"])
            else:
                continue
            if (mid, act) not in seen:
                seen.add((mid, act))
                group["actions"].append((hhmm, act))
        u = msg.get("usage")
        if isinstance(u, dict):
            # same message.id repeats on every content-block line; keep one copy (max guards partial streams)
            entry = usage.setdefault(mid, {"key": (day, project, model)})
            for field, _ in COLS:
                entry[field] = max(entry.get(field, 0), int(u.get(field) or 0))

    for path in paths:
        try:
            f = open(path, encoding="utf-8")
        except OSError as e:
            print("warning: skipping unreadable file %s: %s" % (path, e), file=sys.stderr)
            stats["unread_files"] += 1
            continue
        with f:
            for n, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    rec = None
                if not isinstance(rec, dict):
                    stats["bad_json_lines"] += 1
                    continue
                line(rec, n)
        stats["files_read"] += 1

    for rec in summaries:
        day, project = str(rec.get("timestamp") or "")[:10], rec.get("cwd")
        fb_day, fb_project = where.get(rec.get("sessionId"), (None, None))
        day, project, text = day or fb_day, project or fb_project, rec.get("summary")
        if not (day and project and text):
            stats["summaries_unplaced"] += 1
            continue
        days[day][project]["summaries"].append(clip(text))
    stats["unique_messages"] = len(usage)
    return days, usage, stats


def rollup(usage, prices, keyfn):
    rows = defaultdict(lambda: dict({f: 0 for f, _ in COLS}, cost=0.0, priced=0, unpriced=0))
    for e in usage.values():
        r = rows[keyfn(e["key"])]
        for f, _ in COLS:
            r[f] += e[f]
        price = price_for(e["key"][2], prices)
        if price is None:
            r["unpriced"] += 1
        else:
            r["priced"] += 1
            r["cost"] += sum(e[f] * price[p] for f, p in COLS) / 1e6
    return rows


def money(r):
    if not r["priced"]:
        return "n/a"
    return "$%.4f" % r["cost"] + (" + n/a" if r["unpriced"] else "")


def table(title, head, rows):
    cols = head.count("|") + 1
    out = ["## " + title, "",
           "| %s | input | output | cache_read | cache_create | cost_usd |" % head,
           "|" + "---|" * cols + "--:|" * 5]
    for k in sorted(rows):
        r = rows[k]
        label = " | ".join(k) if isinstance(k, tuple) else k
        out.append("| %s | %s | %s |" % (label, " | ".join("{:,}".format(r[f]) for f, _ in COLS), money(r)))
    return out + [""]


def write_receipts(days, usage, prices, out):
    per_group = rollup(usage, prices, lambda k: (k[0], k[1]))
    files = []
    for day in sorted(days):
        lines = ["# Receipt %s" % day, ""]
        for project in sorted(days[day]):
            g, r = days[day][project], per_group.get((day, project))
            lines += ["## %s" % project, "", "Sessions: %d" % len(g["sessions"])]
            if r:
                lines.append("Tokens: in %s / out %s / cache read %s / cache create %s - cost %s" % (
                    tuple("{:,}".format(r[f]) for f, _ in COLS) + (money(r),)))
            lines += ["", "### Tasks", ""]
            lines += ["- %s %s" % t for t in sorted(g["tasks"], key=lambda t: t[0])] or ["- (none)"]
            lines += ["", "### Key actions", ""]
            lines += ["- %s %s" % a for a in sorted(g["actions"], key=lambda a: a[0])] or ["- (none)"]
            if g["summaries"]:
                lines += ["", "### Session summaries", ""] + ["- " + s for s in g["summaries"]]
            lines.append("")
        path = out / ("receipt-%s.md" % day)
        path.write_text("\n".join(lines), encoding="utf-8")
        files.append(path)
    return files


def write_costs(usage, prices, stats, source, out):
    lines = ["# Token costs", "",
             "Source: `%s` (%d file(s)) - %d assistant lines -> %d unique messages (usage deduped by message.id)." % (
                 source, stats["files_read"], stats["assistant_lines"], stats["unique_messages"]),
             "Cost = tokens x price / 1M. Unknown models show `n/a` (not guessed); `$x + n/a` = priced part only.", ""]
    lines += table("Totals", "scope", rollup(usage, prices, lambda k: "all"))
    lines += table("By day", "day", rollup(usage, prices, lambda k: k[0]))
    lines += table("By project", "project", rollup(usage, prices, lambda k: k[1]))
    lines += table("By model", "model", rollup(usage, prices, lambda k: k[2]))
    lines += table("Detail", "day | project | model", rollup(usage, prices, lambda k: k))
    lines += ["## Prices used (USD per 1M tokens)", "",
              "| model | input | output | cache_read | cache_creation |", "|---|--:|--:|--:|--:|"]
    lines += ["| %s | %s |" % (m, " | ".join(str(p[k]) for _, k in COLS)) for m, p in sorted(prices.items())]
    path = out / "costs.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code transcript JSONL -> daily Markdown receipts + costs.md")
    ap.add_argument("transcripts", nargs="+",
                    help="one or more transcript .jsonl files (shell globs like *.jsonl are expanded)")
    ap.add_argument("--out", default="out", help="output directory (default: out)")
    ap.add_argument("--prices", help="JSON {model: {input, output, cache_creation, cache_read}} in USD per 1M "
                                     "tokens; merged over the built-in defaults")
    a = ap.parse_args(argv)
    prices = load_prices(a.prices)
    paths, seen_path = [], set()
    for p in a.transcripts:
        for m in sorted(glob.glob(p)) or [p]:  # unmatched pattern stays literal -> parse() warns and skips
            if m not in seen_path:
                seen_path.add(m)
                paths.append(m)
    days, usage, stats = parse(paths)
    if not stats["files_read"]:
        sys.exit("no readable transcript files")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    source = " + ".join(Path(p).name for p in paths)
    files = write_receipts(days, usage, prices, out) + [write_costs(usage, prices, stats, source, out)]
    for p in files:
        print("wrote", p)
    print("stats:", ", ".join("%s=%d" % kv for kv in sorted(stats.items())))


if __name__ == "__main__":
    main()
