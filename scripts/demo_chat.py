#!/usr/bin/env python3
"""Live end-to-end demo of the Engram /chat tutor + memory observability.

Prereqs:
  1. Docker Postgres up:   docker compose up -d
  2. Real keys in .env:    cp .env.example .env   # then add DASHSCOPE_API_KEY
Run:
  .venv/bin/python scripts/demo_chat.py

It boots uvicorn, then for one fresh learner:
  1. streams a /chat turn live — printing the recalled memory (context frame),
     the tutor's reply (delta frames), and the raw events saved (saved frame);
  2. consolidates (the Keeper turns raw events into graph memory) and prints the
     audit log of what it did;
  3. chats again, so you can watch the context frame now carry recalled memory.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import uuid

import httpx

PORT = 8011
BASE = f"http://localhost:{PORT}"
LEARNER = f"demo-{uuid.uuid4().hex[:8]}"
LOG = "/tmp/engram_demo_uvicorn.log"

DIM, BOLD, RED, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[0m"


async def chat_turn(client: httpx.AsyncClient, content: str) -> None:
    print(f"\n{BOLD}🧑 You:{RESET} {content}")
    event = None
    started = False
    async with client.stream(
        "POST", "/chat",
        json={"learner_id": LEARNER, "messages": [{"role": "user", "content": content}]},
    ) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                if event == "context":
                    mem = data.get("text_block") or "(nothing recalled yet)"
                    print(f"{DIM}🧠 recalled memory:\n   " + mem.replace("\n", "\n   ") + RESET)
                elif event == "delta":
                    if not started:
                        print(f"{BOLD}🤖 Tutor:{RESET} ", end="")
                        started = True
                    sys.stdout.write(data["text"])
                    sys.stdout.flush()
                elif event == "saved":
                    print(f"\n{DIM}💾 saved events: {[e['type'] for e in data['events']]}{RESET}")
                elif event == "error":
                    print(f"\n{RED}⚠️  error: {data['detail']}{RESET}")


async def drive() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as client:
        print(f"health: {(await client.get('/health')).json()}")

        # 1) cold start — no graph memory yet, so the context frame is empty
        await chat_turn(client, "What is a limit in calculus? Keep it to two sentences.")

        # 2) consolidate — the Keeper turns the raw events into graph memory
        print(f"\n{BOLD}⚙️  Consolidating (Keeper: events → graph memory)...{RESET}")
        rep = (await client.post("/consolidate", json={"learner_id": LEARNER})).json()
        print(f"   nodes_created={rep['nodes_created']} edges_created={rep['edges_created']} "
              f"processed_events={rep['processed_events']}")
        aud = (await client.get("/audit", params={"learner_id": LEARNER})).json()
        print(f"{BOLD}📋 audit (what the Keeper did):{RESET}")
        for row in aud["rows"]:
            print(f"   • {row['op']:<14} {row.get('rationale') or ''}")

        # 3) warm — chat again; the context frame should now carry recalled memory
        await chat_turn(client, "Remind me — what did we just cover about limits?")


def _healthy() -> bool:
    try:
        return httpx.get(f"{BASE}/health", timeout=2).status_code == 200
    except Exception:
        return False


def main() -> int:
    print(f"Booting uvicorn on :{PORT}  (learner={LEARNER})")
    with open(LOG, "w") as log:
        proc = subprocess.Popen(
            [".venv/bin/uvicorn", "engram.app.main:app", "--port", str(PORT)],
            stdout=log, stderr=subprocess.STDOUT, text=True,
        )
    try:
        ok = False
        for _ in range(30):
            if proc.poll() is not None:
                break
            if _healthy():
                ok = True
                break
            time.sleep(1)
        if not ok:
            tail = "\n".join(open(LOG).read().splitlines()[-12:])
            print(
                f"{RED}Server didn't start — most likely .env is missing or incomplete.{RESET}\n"
                "Need: DASHSCOPE_API_KEY and DATABASE_URL (models default to Qwen).\n"
                "Fix:  cp .env.example .env  # then add your real keys\n"
                f"{DIM}--- uvicorn log tail ---\n{tail}{RESET}"
            )
            return 1
        asyncio.run(drive())
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
