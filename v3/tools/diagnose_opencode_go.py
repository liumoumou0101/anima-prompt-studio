"""Small real-provider diagnostic. Never saves credentials or raw headers."""
import asyncio
import getpass
import json
import time
import httpx
import uuid


async def main(key):
    started = time.monotonic()
    headers = {"Authorization": "Bearer " + key, "User-Agent": "AnimaPromptStudio/0.1 LLMPrototypeTest", "x-opencode-session": str(uuid.uuid4())}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as client:
            async with client.stream("POST", "https://opencode.ai/zen/go/v1/chat/completions", headers=headers,
                                     json={"model": "mimo-v2.5", "messages": [{"role": "user", "content": "Reply with OK only."}], "max_tokens": 64, "stream": True}) as response:
                print(json.dumps({"status": response.status_code, "seconds_to_headers": round(time.monotonic()-started,2)}), flush=True)
                if response.status_code != 200:
                    raw = (await response.aread()).decode(errors="replace").replace(key, "[REDACTED]")
                    print(raw[:1000], flush=True)
                    return
                chunks = 0
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    for choice in event.get("choices", []):
                        delta = choice.get("delta", {})
                        chunks += 1
                        print(json.dumps({"seconds": round(time.monotonic()-started,2), "delta_fields": list(delta), "content": str(delta.get("content", ""))[:100], "finish_reason": choice.get("finish_reason")}), flush=True)
                print(json.dumps({"chunks": chunks, "total_seconds": round(time.monotonic()-started,2)}), flush=True)
    except Exception as exc:
        print(json.dumps({"exception": type(exc).__name__, "seconds": round(time.monotonic()-started,2)}), flush=True)


if __name__ == "__main__":
    asyncio.run(main(getpass.getpass("Temporary key: ")))
