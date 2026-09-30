# agent-receipt

i kept losing track of how much my claude code subagents were actually costing me, so i wrote this. it reads your transcript `.jsonl` files and spits out a daily receipt: what you asked for, what the agent did, and the token/cost breakdown per model.

one file, stdlib only. windows and linux.

## quickstart

```bash
python3 gen_sample.py                               # makes a fake transcript so you don't need your real ones
python3 receipt.py sample_transcript.jsonl --out out/
```

real usage:

```bash
python3 receipt.py ~/.claude/projects/*/*.jsonl --out out/
```

multiple files (or a glob) merge into the same report. overlap between files is fine, usage is deduped by message id.

## what you get

- `out/receipt-YYYY-MM-DD.md` — per day, per project: your prompts (one line each), key actions, tokens and cost
- `out/costs.md` — tokens and USD cost by day, project, model

## notes

- claude code repeats the same usage block on every content line, so naive summing over-counts. this dedupes by `message.id`.
- prices are baked in for sonnet/opus; add your own with `--prices my.json`. unknown models show `n/a`, never guessed.
- day buckets are UTC, intent detection is a dumb first-sentence heuristic. honest list of gaps in `SPEC.md`.

still early. issues and PRs welcome.
