"""Bounded live smoke test. Read temporary credential from stdin, never persist it."""
import asyncio
import contextlib
import io
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

CASES = [
    ("ink_crane", "水墨画，一只白鹤站在浅水中，黑色飞羽，细长的红色腿，背景是宣纸留白。", "文字、水印", "faithful"),
    ("pixel_succulents", "像素游戏场景，一个黄色小机器人在温室里给三盆多肉植物浇水，有限调色板，等距视角。", "人物、照片质感", "faithful"),
    ("woodcut_parcel", "双色木刻版画，恰好两个成年男人。左边男人穿白围裙，右边男人穿黑外套，两人正在交接一个红色包裹，米色纸张，粗线条。", "第三个人、文字", "faithful"),
    ("glass_perfume", "商业产品摄影，方形透明玻璃香水瓶，琥珀色液体，银色瓶盖，瓶身有清晰水滴。背景虚化形成圆形光斑，棱镜折射带来彩色边缘。", "标签、文字、人物", "faithful"),
    ("charcoal_detective", "黑白炭笔画，黑色电影风格，一个成年女性侦探的半身像，短发，穿风衣。她右手拿着一封信，左侧有台灯，右侧桌上有杯子。", "枪、水印", "faithful"),
    ("scoped_hat", "两个成年男人并排站立。左边男人不戴帽子，右边男人戴红色帽子。背景为空白。", "文字", "faithful"),
    ("empty_negative", "水彩画，一只橘猫睡在蓝色窗台上。", "", "faithful"),
    ("expanded_cat", "水彩画，一只橘猫睡在蓝色窗台上。", "文字", "expand"),
]


async def main(key, output):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    from anima_prompt_studio_v3.api.llm_workbench import generate_prompt, test_connection
    from anima_prompt_studio_v3.api.models import PromptGenerateRequest

    # Credentials remain in process memory. Production config/settings untouched.
    LLMService._get_config = staticmethod(lambda: {
        "provider": "opencode_go", "model": "mimo-v2.5", "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": key, "temperature": 0.7, "top_p": 0.9, "max_tokens": 2000,
    })
    records = []
    async def run(name, source="", excluded="", mode="faithful"):
        start = time.monotonic()
        try:
            # Third-party diagnostics can echo headers/errors: don't persist them.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = await test_connection() if name == "connection" else await generate_prompt(PromptGenerateRequest(source_text=source, excluded_text=excluded, mode=mode))
            record = {"case": name, "ok": True, "seconds": round(time.monotonic()-start, 2), "source": source, "excluded": excluded, "mode": mode, "result": result}
        except Exception as exc:
            record = {"case": name, "ok": False, "seconds": round(time.monotonic()-start, 2), "error_type": type(exc).__name__}
        records.append(record)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"model": "mimo-v2.5", "base_url": "https://opencode.ai/zen/go/v1", "identity_headers_added_by_probe": False, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return record["ok"]
    try:
        if await run("connection"):
            for case in CASES:
                if not await run(*case):
                    break  # no automatic paid retry/fallback after failure
    finally:
        await HTTPClientPool.close_all()


if __name__ == "__main__":
    print("Waiting for temporary credential on stdin (not echoed).", flush=True)
    key = (getpass.getpass("Temporary key: ") if sys.stdin.isatty() else sys.stdin.readline()).strip()
    if not key:
        raise SystemExit("No credential received.")
    with tempfile.TemporaryDirectory(prefix="anima-go-probe-") as temp:
        os.environ["ANIMA_PROMPT_ASSISTANT_DIR"] = temp
        asyncio.run(main(key, Path("reports/opencode-go-live/results.json")))
