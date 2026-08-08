from __future__ import annotations

from pathlib import Path
import re

from anima_prompt_studio.domain.models import LoRAProfile, LoRASelection


class LoRAResolver:
    def __init__(self, profiles: list[LoRAProfile] | None = None) -> None:
        self.profiles = profiles or []

    def set_profiles(self, profiles: list[LoRAProfile]) -> None:
        self.profiles = list(profiles)

    def mentions_in_text(self, text: str) -> list[str]:
        mentions: list[str] = []
        for profile in self.profiles:
            candidates = (profile.id, profile.display_name, profile.file_name, Path(profile.file_name).stem)
            if any(value and re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, flags=re.I) for value in candidates):
                mentions.append(profile.id)
        return list(dict.fromkeys(mentions))

    @staticmethod
    def _keys(profile: LoRAProfile) -> set[str]:
        return {
            profile.id.casefold(), profile.display_name.casefold(), profile.file_name.casefold(),
            Path(profile.file_name).stem.casefold(),
        }

    def resolve(self, mentions: list[str], existing: list[LoRASelection]) -> tuple[list[LoRASelection], list[str]]:
        result = [item for item in existing if item.source != "text_derived"]
        selected = {x.logical_id.casefold() for x in result}
        unresolved: list[str] = []
        for mention in mentions:
            key = mention.casefold()
            profile = next((item for item in self.profiles if key in self._keys(item)), None)
            if profile is None:
                unresolved.append(mention)
                continue
            if profile.id.casefold() in selected:
                continue
            result.append(LoRASelection(
                logical_id=profile.id, file_name=profile.file_name,
                weight=profile.default_weight, trigger_words=profile.trigger_words, source="text_derived",
            ))
            selected.add(profile.id.casefold())
        return result, unresolved
