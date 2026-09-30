# receipt.py — SPEC

## Input
One or more Claude Code transcript JSONL files (positional args; shell globs like `*.jsonl` are expanded,
duplicates removed). All files merge into the same day/project buckets; `message.id` dedupe is global across
files. Unreadable files are warned and skipped (`unread_files` in stats); the run fails only if none are readable.
One JSON object per line. Used types (others ignored):

| type | fields used |
|---|---|
| `user` | `timestamp`, `sessionId`, `cwd`, `message.content` (string or `[{type:text,text}]`; `tool_result` blocks ignored; `isMeta` lines and `<...>` wrapper texts skipped) |
| `assistant` | `timestamp`, `sessionId`, `cwd`, `model` (fallback `message.model`), `message.id`, `message.usage.{input_tokens,output_tokens,cache_creation_input_tokens,cache_read_input_tokens}`, `message.content[]` (`text` / `tool_use{name,input}`) |
| `summary` | `timestamp`, `sessionId`, `cwd`, `summary`; missing timestamp/cwd falls back to the session's last seen day/project |

Blank lines skipped; malformed JSON counted (`bad_json_lines`), not fatal. `user`/`assistant` lines without timestamp or cwd are counted and skipped.

## Output (`--out DIR`)
- `receipt-YYYY-MM-DD.md` per day (day = first 10 chars of `timestamp`), grouped by project (`cwd`):
  sessions count, token/cost line, **Tasks** (first sentence of each user message, ≤120 chars),
  **Key actions** (`[ToolName] file/command hint` or assistant text, ≤120 chars each), session summaries.
- `costs.md`: Totals, By day, By project, By model, Detail (day × project × model) tables with
  input / output / cache_read / cache_create tokens and USD cost, plus the price table used.

## Dedupe rule
Claude Code writes one line per assistant content block and repeats the full `usage` on each.
Usage is counted **once per `message.id`** (per-field max across its lines, which equals the value when lines agree).
Day/project/model of a message = its first line. Lines with no `message.id` cannot be deduped and are counted per line.
Actions are deduped by (`message.id`, action text).

## Prices (USD per 1M tokens)
| model | input | output | cache_creation | cache_read |
|---|--:|--:|--:|--:|
| claude-sonnet-4-5 | 3 | 15 | 3.75 | 0.3 |
| claude-opus-4-1 | 15 | 75 | 18.75 | 1.5 |

Built in; `--prices file.json` (same shape) is merged over defaults. Lookup: exact model id, else longest key `K`
with model = `K-<suffix>` (e.g. `claude-sonnet-4-5-20250929`). Unknown model → cost `n/a`; mixed groups show `$x + n/a`.

## Task intent heuristic
One line per user message: take the first sentence; if it ends in `?` but a later sentence states something
concrete, take the first statement instead (the question was a preamble, e.g. "Quick question: does X expire?
Add TTL support." → "Add TTL support."). Leading filler ("hey", "quick one", "so") is stripped; abbreviations
("e.g.", "i.e.", "etc.", "vs.", "Mr/Ms/Dr/St") are protected from sentence splitting. Clipped to 120 chars.

## Known gaps
- Day buckets use the timestamp's own date (Claude Code writes UTC), not local time; a session crossing midnight appears on both days.
- Intent is a heuristic: multi-part prompts collapse to one line; question-that-IS-the-task stays as-is only when no statement follows.
- No long-context (>200k) premium pricing, no batch/discount pricing, no 1h vs 5m cache-write distinction.
- Real `summary` lines often carry only `leafUuid` (no sessionId/cwd) → counted as `summaries_unplaced`.
- Old receipts in `--out` are not deleted; stale day files from an older run survive re-runs over fewer days.
