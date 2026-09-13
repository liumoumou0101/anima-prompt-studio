"""Import an explicitly selected local research collection without guessing provenance."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from .reference_examples import ExampleMetadata, ExampleNotes, ExampleStore, MAX_IMAGE_BYTES, inspect_image, now

MODEL_PROFILES = {
    "anima-base-v1.0": "anima_base_v1",
    "anima-aesthetic-v1.0": "anima_aesthetic_v1_0",
    "anima-aesthetic-v1.1": "anima_aesthetic_v1_1",
    "anima-turbo-v1.0": "anima_turbo_v1",
    "anima-turbo-v1.1": "anima_turbo_v1_1",
    "anima-2.9b-preview-v1": "anima_2_9b_preview_v1",
}


def source_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("图片路径必须为集合内的相对路径。")
    raw = Path(relative)
    resolved = (root / raw).resolve()
    if raw.is_absolute() or ".." in raw.parts or ":" in relative or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("图片路径越界或文件不存在：" + relative)
    return resolved


def prepare_collection(root: Path):
    root = Path(root).resolve(strict=True)
    batches = root / "batches"
    if not batches.is_dir() or not batches.resolve().is_relative_to(root):
        raise ValueError("集合缺少有效的 batches 目录。")
    prepared, seen, batch_receipts = [], set(), []
    for batch in sorted(batches.glob("*.json")):
        if not batch.resolve().is_relative_to(root):
            raise ValueError("批次文件越出集合目录。")
        raw = batch.read_bytes()
        entries = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(entries, list):
            raise ValueError("批次必须是 JSON 数组。")
        batch_receipts.append({"file": batch.relative_to(root).as_posix(), "sha256": sha256(raw).hexdigest(), "count": len(entries)})
        for row in entries:
            if not isinstance(row, dict) or re.fullmatch(r"civitai:[0-9]{1,20}", str(row.get("id", ""))) is None:
                raise ValueError("案例必须携带有效且稳定的 civitai:<数字> 来源 ID。")
            source_id = row["id"]
            if source_id in seen:
                raise ValueError("集合中存在重复来源 ID：" + source_id)
            seen.add(source_id)
            if not isinstance(row.get("title"), str) or not 1 <= len(row["title"].strip()) <= 200:
                raise ValueError("案例标题必须为 1～200 字。")
            for key in ("prompt", "negative", "checkpoint", "artist_tag", "lora", "source_url"):
                if not isinstance(row.get(key, ""), str):
                    raise ValueError(f"{source_id} 的 {key} 必须是字符串。")
            if len(row.get("prompt", "")) > 20000 or len(row.get("negative", "")) > 20000:
                raise ValueError("案例提示词超过长度上限。")
            for key in ("nsfw", "unet_pure", "prompt_unknown"):
                if key in row and type(row[key]) is not bool:
                    raise ValueError(f"{source_id} 的 {key} 必须是布尔值。")
            image = source_path(root, row.get("image_file"))
            with image.open("rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
            media = inspect_image(data)
            artists = list(dict.fromkeys(part.strip().lstrip("@").casefold().replace(" ", "_")
                for part in row.get("artist_tag", "").split(",") if part.strip()))
            lora = row.get("lora", "").strip()
            dependency = "lora" if lora else "none" if row.get("unet_pure") is True else "unknown"
            level = row.get("nsfw_level")
            if level not in {"safe", "sensitive", "nsfw", "explicit"}:
                level = "nsfw" if row.get("nsfw") is True else "safe" if row.get("nsfw") is False else "unknown"
            settings = {key: row.get(key) for key in ("sampler", "scheduler", "steps", "cfg", "seed")}
            dimensions = re.fullmatch(r"([0-9]+)[x×]([0-9]+)", str(row.get("size", "")))
            settings.update(width=int(dimensions[1]) if dimensions else None, height=int(dimensions[2]) if dimensions else None)
            known_prompt = not row.get("prompt_unknown", False)
            provenance = {
                "source": "local_research_collection", "source_id": source_id,
                "source_record_sha256": sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                "source_image_sha256": media["sha256"],
                "positive": row.get("prompt", "") if known_prompt else None,
                "negative": row.get("negative") if known_prompt else None,
                "model_profile": MODEL_PROFILES.get(row.get("checkpoint", "")),
                "settings": settings, "workflow_snapshot_ref": None, "reproducibility": "partial",
                "unknown_fields": [key for key, value in settings.items() if value is None] + ["workflow"],
                "reference_metadata": {
                    "checkpoint": row.get("checkpoint", ""), "artists": artists,
                    "artist_tag": row.get("artist_tag", ""), "lora": row.get("lora", ""),
                    "lora_url": row.get("lora_url", ""), "lora_dependency": dependency,
                    "content_level": level, "unet_pure": row.get("unet_pure"),
                    "style_axis": row.get("style_axis", ""), "why": row.get("why", ""),
                    "copy_tip": row.get("copy_tip", ""), "stats": row.get("stats", ""),
                    "source_url": row.get("source_url", ""), "source_batch": batch.relative_to(root).as_posix(),
                    "image_file": row["image_file"], "source_record": row,
                },
            }
            # The ID depends on source identity, not file location or editable metadata.
            example_id = "ex_" + sha256(("anima-ref:" + source_id).encode()).hexdigest()[:32]
            notes = ExampleNotes(external_prompt=("正向：" + row.get("prompt", "") + "\n负向：" + row.get("negative", ""))[:20000],
                source_url=row.get("source_url", ""))
            prepared.append({"id": example_id, "source_id": source_id, "title": row["title"].strip(),
                "data": data, "provenance": provenance, "metadata": ExampleMetadata(notes=notes)})
    if not prepared:
        raise ValueError("集合中没有可导入案例。")
    return prepared, batch_receipts


def import_collection(store: ExampleStore, root: Path, *, dry_run=False):
    """Preflight every source before writing; unchanged imports never edit personal data."""
    prepared, batches = prepare_collection(root)
    actions = []
    with store.connect() as db:
        for item in prepared:
            old = db.execute("SELECT * FROM examples WHERE id=?", (item["id"],)).fetchone()
            action = "created"
            if old is not None:
                value = json.loads(old["payload_json"])
                previous = value.get("provenance") or {}
                if value.get("origin") != "research_import" or value.get("origin_ref") != item["source_id"]:
                    raise ValueError("来源 ID 与现存参考冲突：" + item["source_id"])
                if previous.get("source_image_sha256") != item["provenance"]["source_image_sha256"]:
                    raise ValueError("来源图片内容已变化，请作为新的案例处理：" + item["source_id"])
                if not old["deleted_at"]:
                    path, _ = store.content(item["id"])
                    with path.open("rb") as stream:
                        stored_hash = sha256(stream.read(MAX_IMAGE_BYTES + 1)).hexdigest()
                    if stored_hash != item["provenance"]["source_image_sha256"]:
                        raise ValueError("已导入图片校验不一致，请检查参考库文件：" + item["source_id"])
                action = "deleted_preserved" if old["deleted_at"] else "unchanged" if previous == item["provenance"] else "updated"
            actions.append((action, item))
    receipt = {"schema": "anima-reference-import/1", "dry_run": dry_run, "created_at": now(),
        "source_root": str(Path(root).resolve()), "database": str(store.path.resolve()), "batches": batches,
        "counts": {key: sum(action == key for action, _ in actions) for key in ("created", "updated", "unchanged", "deleted_preserved")},
        "items": []}
    for action, item in actions:
        if not dry_run and action == "created":
            profile = item["provenance"]["model_profile"]
            store.create(item["data"], item["title"], item["metadata"], example_id=item["id"],
                origin="research_import", origin_ref=item["source_id"], provenance=item["provenance"],
                compat={"model_profiles": [profile] if profile else []})
        elif not dry_run and action == "updated":
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT * FROM examples WHERE id=? AND deleted_at IS NULL", (item["id"],)).fetchone()
                if old is None:
                    raise ValueError("案例在导入过程中被删除，请重新执行导入。")
                value = json.loads(old["payload_json"])
                # Title, every note, structured requirements, and user-declared compatibility are user-owned.
                value["provenance"] = item["provenance"]
                db.execute("UPDATE examples SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?",
                    (json.dumps(value, ensure_ascii=False), now(), item["id"]))
                store.changed(db)
        receipt["items"].append({"id": item["id"], "source_id": item["source_id"], "action": action,
            "image_sha256": item["provenance"]["source_image_sha256"],
            "record_sha256": item["provenance"]["source_record_sha256"]})
    return receipt
