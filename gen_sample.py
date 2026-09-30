#!/usr/bin/env python3
"""Generate a realistic synthetic Claude Code transcript -> sample_transcript.jsonl (deterministic seed).

Mirrors real quirks: one line per assistant content block with the usage repeated on each line,
tool_result user lines, string vs list user content, a session crossing midnight, an unpriced model.
"""
import json
import random
import string
import uuid
from datetime import datetime, timedelta

rng = random.Random(20260925)
SHOP, API = "/home/user/shop-site", "/home/user/api-server"
S45, O41, H45 = "claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"


def T(text):
    return {"type": "text", "text": text}


def U(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


# (project, start, model, turns, summary); turn = (user text, gap minutes, model override, [message = [blocks]])
SESSIONS = [
    (SHOP, "2026-09-25 09:12", S45, [
        ("The cart total is off by one cent when a discount code is applied. Can you find out why and fix it?", 0, None, [
            [T("Let me look at how the cart computes totals first."), U("Grep", pattern="applyDiscount", path=SHOP + "/src")],
            [U("Read", file_path=SHOP + "/src/cart/total.ts")],
            [T("Found it: the discount is applied per line item and rounded on each line, so rounding errors accumulate. "
               "I'll compute totals in integer cents and apply the discount once on the subtotal."),
             U("Edit", file_path=SHOP + "/src/cart/total.ts", old_string="lineTotal * (1 - pct)", new_string="applyPct(subtotalCents, pct)")],
            [U("Bash", command="npm test -- cart", description="Run cart tests")],
            [T("Fixed. Totals are now computed in integer cents and the discount is applied once on the subtotal. "
               "All 18 cart tests pass, and I added a regression test for 3 x $19.99 with 10% off.")],
        ]),
        ("Nice. Also add a test for a 100% discount code so the total never goes negative.", 3, None, [
            [U("Edit", file_path=SHOP + "/src/cart/total.test.ts", old_string="});", new_string="it('clamps 100% off to zero', ...)")],
            [U("Bash", command="npm test -- cart", description="Run cart tests")],
            [T("Added a 100%-off case; the total clamps at 0.00. Tests pass (19/19).")],
        ]),
    ], "Fix cart discount rounding (integer cents) and add regression tests"),

    (API, "2026-09-25 16:40", O41, [
        ("Our /orders endpoint times out under load. Profile it and find the bottleneck.", 0, None, [
            [T("I'll run the orders benchmark with a CPU profile."),
             U("Bash", command="go test ./internal/orders -bench=. -cpuprofile cpu.out", description="Benchmark orders")],
            [U("Bash", command="go tool pprof -top cpu.out", description="Show profile hot spots")],
            [T("The bottleneck is an N+1 query: ListOrders loads line items with one SELECT per order. "
               "For a page of 200 orders that's 201 round-trips to Postgres, which dominates the 2.8s p95.")],
        ]),
        ("Fix the N+1 query with a single join and add an index if needed.", 4, None, [
            [U("Read", file_path=API + "/internal/orders/repo.go")],
            [T("Replacing the per-order lookup with one JOIN and adding an index on line_items(order_id)."),
             U("Edit", file_path=API + "/internal/orders/repo.go", old_string="for _, o := range orders {", new_string="rows, err := r.db.Query(listWithItemsSQL, ids)"),
             U("Write", file_path=API + "/migrations/0042_line_items_order_id_idx.sql", content="CREATE INDEX CONCURRENTLY ...")],
            [U("Bash", command="go test ./...", description="Run all tests")],
            [T("Done. ListOrders now issues a single query; benchmark p95 dropped from 2.8s to 140ms. Migration 0042 adds the index "
               "concurrently so it is safe to run on production.")],
        ]),
    ], "Profile /orders, fix N+1 query with JOIN and add line_items index"),

    (SHOP, "2026-09-26 14:05", S45, [
        ("Product images load slowly on mobile. Set up responsive images with srcset for the product grid.", 0, None, [
            [U("Read", file_path=SHOP + "/src/components/ProductGrid.tsx")],
            [T("The grid serves the 2000px original to every device. I'll switch to next/image with sizes so the browser picks a smaller variant."),
             U("Edit", file_path=SHOP + "/src/components/ProductGrid.tsx", old_string="<img src={p.image}", new_string="<Image src={p.image} sizes=\"(max-width: 640px) 50vw, 25vw\"")],
            [U("Bash", command="npm run build", description="Production build")],
            [T("Build is green. The grid now serves 320-640px variants on phones instead of the 2000px original.")],
        ]),
        ("Run Lighthouse on the product page and tell me the mobile score.", 6, None, [
            [U("Bash", command="npx lighthouse http://localhost:3000/products/42 --form-factor=mobile --only-categories=performance --quiet",
               description="Lighthouse mobile audit")],
            [T("Mobile performance score went from 61 to 88; LCP dropped from 4.1s to 2.2s. Remaining warning: unused JS from the reviews widget.")],
        ]),
    ], "Responsive product images with srcset; Lighthouse mobile 61 -> 88"),

    (API, "2026-09-26 23:35", S45, [
        ("Add rate limiting to the public API: 100 requests per minute per API key, and return 429 with Retry-After.", 0, None, [
            [T("I'll check the existing middleware chain before adding a limiter."), U("Read", file_path=API + "/internal/http/middleware.go")],
            [U("Write", file_path=API + "/internal/http/ratelimit.go", content="package http // token bucket per API key ..."),
             U("Edit", file_path=API + "/internal/http/router.go", old_string="r.Use(auth)", new_string="r.Use(auth, rateLimit(100, time.Minute))")],
            [U("Bash", command="go test ./internal/http/...", description="Run HTTP tests")],
            [T("Rate limiting is in: a token bucket keyed by API key, 100 req/min, returning 429 with a Retry-After header in seconds. "
               "Buckets live in memory, so limits are per instance until we move them to Redis.")],
        ]),
        ("Write a short CHANGELOG entry for the rate limiter.", 30, H45, [
            [U("Edit", file_path=API + "/CHANGELOG.md", old_string="## Unreleased", new_string="## Unreleased\n- Public API rate limit: 100 req/min per key (429 + Retry-After)")],
            [T("Added the entry under Unreleased.")],
        ]),
    ], "Per-key rate limiting (100 req/min, 429 + Retry-After) and CHANGELOG entry"),

    (SHOP, "2026-09-27 10:30", S45, [
        ("Add Stripe checkout for the cart. Use Checkout Sessions, not the legacy Charges API.", 0, None, [
            [T("Plan: server route creates a Checkout Session from the cart, client redirects, webhook marks the order paid."),
             U("Write", file_path=SHOP + "/src/api/checkout.ts", content="export async function createCheckoutSession(cart) { ... }")],
            [U("Edit", file_path=SHOP + "/.env.example", old_string="# payments", new_string="# payments\nSTRIPE_SECRET_KEY=\nSTRIPE_WEBHOOK_SECRET=")],
            [U("Bash", command="npm test -- checkout", description="Run checkout tests")],
            [T("Checkout Sessions are wired up: POST /api/checkout returns the session URL and line items are built from cart prices in cents. "
               "Add STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET to your env.")],
        ]),
        ("What happens if the webhook arrives before the redirect? Make order creation idempotent.", 5, None, [
            [U("Read", file_path=SHOP + "/src/api/webhooks/stripe.ts")],
            [T("Today both the redirect handler and the webhook insert an order, so a fast webhook creates a duplicate. "
               "I'll upsert on the Checkout Session id instead."),
             U("Edit", file_path=SHOP + "/src/api/webhooks/stripe.ts", old_string="db.orders.insert(", new_string="db.orders.upsert({ key: session.id }, ")],
            [T("Order creation is now idempotent: both paths upsert on the session id, so order and arrival do not matter.")],
        ]),
    ], "Stripe Checkout Sessions integration with idempotent order creation"),
]


def rid(prefix, n=22):
    return prefix + "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(n))


def new_uuid():
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def session(project, start, model, turns, summary):
    sid, rows = new_uuid(), []
    state = {"now": datetime.strptime(start, "%Y-%m-%d %H:%M"), "parent": None}

    def line(kind, **extra):
        state["now"] += timedelta(seconds=rng.randint(2, 40), milliseconds=rng.randint(0, 999))
        u = new_uuid()
        rows.append(dict(type=kind, uuid=u, parentUuid=state["parent"], timestamp=ts(state["now"]), sessionId=sid,
                         cwd=project, version="2.0.14", gitBranch="main", **extra))
        state["parent"] = u

    ctx = 0
    for i, (text, gap, override, messages) in enumerate(turns):
        state["now"] += timedelta(minutes=gap)
        line("user", message={"role": "user", "content": text if i % 2 == 0 else [T(text)]})
        for blocks in messages:
            m = override or model
            create = rng.randint(9000, 16000) if ctx == 0 else rng.randint(300, 4000)
            usage = {"input_tokens": rng.randint(3, 40), "cache_creation_input_tokens": create,
                     "cache_read_input_tokens": ctx, "output_tokens": rng.randint(60, 1500)}
            ctx += create
            mid, tool_ids = rid("msg_01"), []
            for b in blocks:
                if b["type"] == "tool_use":
                    b = dict(b, id=rid("toolu_01"))
                    tool_ids.append(b["id"])
                line("assistant", model=m, message={"id": mid, "type": "message", "role": "assistant", "model": m,
                                                    "content": [b], "stop_reason": None, "usage": usage})
            for tid in tool_ids:
                line("user", message={"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]})
    state["now"] += timedelta(seconds=5)
    rows.append({"type": "summary", "timestamp": ts(state["now"]), "sessionId": sid, "cwd": project,
                 "summary": summary, "leafUuid": state["parent"]})
    return rows


if __name__ == "__main__":
    rows = sorted((r for s in SESSIONS for r in session(*s)), key=lambda r: r["timestamp"])
    with open("sample_transcript.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote sample_transcript.jsonl: %d lines, %d sessions" % (len(rows), len(SESSIONS)))
