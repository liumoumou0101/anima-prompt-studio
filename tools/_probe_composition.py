"""Probe auto composition and alternative cycling without launching the UI."""
from __future__ import annotations

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import TranslationService


class EchoEngine:
    name = "echo"

    def zh_to_en(self, text):
        return text

    def en_to_zh(self, text):
        return text


CASES = [
    "一个短发女孩看向镜头微笑，半身",
    "一个长发女孩站在窗边，全身",
    "一个女孩向右奔跑，全身",
    "两个女孩并肩站着说话",
    "三个女孩站在广场上",
    "一个女孩在森林里采蘑菇",
    "一名天使从天而降，长着巨大的白色羽翼",
    "一个女孩将头伸出列车外",
    "一个女孩坐在房间里看书",
    "夜晚霓虹灯下的短发女孩，半身",
    "远山、古塔和石桥，没有人物",
    "一个裸体女孩躺在床上",
    "一个女孩从背后看，背影",
    "一个女孩低机位仰拍全身",
]


def summarize(job: PromptJob) -> dict:
    c = job.composition
    p = job.generation_params
    return {
        "shot": c.shot,
        "camera": c.camera_height,
        "angle": c.angle,
        "gaze": c.gaze,
        "aspect": c.aspect,
        "pos": c.subject_position,
        "people": c.people_count,
        "mode": c.mode,
        "size": f"{p.width}x{p.height}",
        "w_state": p.state("width").value,
        "h_state": p.state("height").value,
        "reasons": {field: c.decision(field).reason for field in (
            "shot", "camera_height", "angle", "gaze", "aspect", "subject_position"
        )},
    }


def main() -> None:
    pipe = PromptPipeline(translation=TranslationService(EchoEngine()))
    for zh in CASES:
        job = PromptJob(original_zh=zh, normalized_zh=zh, translated_en=zh)
        pipe.compiler.apply_model_defaults(job)
        pipe.recommend_composition(job)
        best = summarize(job)
        print(f"\n== {zh}")
        print(
            f"  best  {best['shot']}/{best['camera']}/{best['angle']}/{best['gaze']}"
            f"/{best['aspect']}/{best['pos']} people={best['people']} {best['size']} "
            f"w={best['w_state']} h={best['h_state']}"
        )
        alts = []
        for index in range(1, 5):
            alt_job = PromptJob(original_zh=zh, normalized_zh=zh, translated_en=zh)
            pipe.compiler.apply_model_defaults(alt_job)
            pipe.recommend_composition(alt_job, alternative_index=index)
            alt = summarize(alt_job)
            key = (alt["shot"], alt["camera"], alt["angle"], alt["gaze"], alt["aspect"], alt["pos"])
            best_key = (best["shot"], best["camera"], best["angle"], best["gaze"], best["aspect"], best["pos"])
            if key != best_key and key not in alts:
                alts.append(key)
                print(f"  alt{index} {'/'.join(key)}")
        if not alts:
            print("  alt   (no different alternative)")


if __name__ == "__main__":
    main()
