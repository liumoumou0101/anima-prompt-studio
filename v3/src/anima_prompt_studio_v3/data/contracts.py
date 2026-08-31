from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


DATA_CONTRACT = "anima-v3-data/1"


class DataContractError(ValueError):
    """Raised when an input or installed data pack violates the V3 contract."""


class DataPackSnapshot(BaseModel):
    target_cutoff: date
    cutoff_mode: Literal["exact", "approximate"]
    source_observed_at: date
    corpus_size: int = Field(ge=0)
    corpus_size_mode: Literal["exact", "estimated"]

    @model_validator(mode="after")
    def exact_cutoff_requires_exact_corpus(self) -> "DataPackSnapshot":
        if self.cutoff_mode == "exact" and self.corpus_size_mode != "exact":
            raise ValueError("精确截止数据包必须使用精确 corpus_size。")
        return self


class UpstreamSource(BaseModel):
    name: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str = Field(min_length=1)

    @field_validator("repository")
    @classmethod
    def repository_must_be_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("上游仓库必须使用 HTTPS URL。")
        return value.rstrip("/")


class DataPackCounts(BaseModel):
    tags: int = Field(ge=0)
    artists: int = Field(ge=0)
    aliases: int = Field(ge=0)
    tag_edges: int = Field(ge=0)
    artist_edges: int = Field(ge=0)


class DataPackDiagnostics(BaseModel):
    duplicate_tags_merged: int = Field(default=0, ge=0)
    aliases_skipped_inactive: int = Field(default=0, ge=0)
    aliases_skipped_missing_target: int = Field(default=0, ge=0)
    aliases_skipped_canonical_collision: int = Field(default=0, ge=0)
    tag_edges_skipped_unknown_tag: int = Field(default=0, ge=0)
    tag_edges_margin_mismatch: int = Field(default=0, ge=0)
    artist_edges_skipped_unknown_tag: int = Field(default=0, ge=0)
    artist_edges_margin_mismatch: int = Field(default=0, ge=0)


class DataPackFile(BaseModel):
    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if candidate.is_absolute() or ".." in candidate.parts or normalized in {"", "."}:
            raise ValueError("数据包文件路径必须是包内安全相对路径。")
        return normalized


class DataPackManifest(BaseModel):
    contract: Literal[DATA_CONTRACT] = DATA_CONTRACT
    pack_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    generated_at: datetime
    snapshot: DataPackSnapshot
    sources: list[UpstreamSource]
    algorithms: dict[str, str]
    counts: DataPackCounts
    diagnostics: DataPackDiagnostics = Field(default_factory=DataPackDiagnostics)
    files: list[DataPackFile] = Field(min_length=1)

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at 必须包含时区。")
        return value

    @field_validator("algorithms")
    @classmethod
    def algorithms_must_be_versioned(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not key.strip() or not version.strip() for key, version in value.items()):
            raise ValueError("algorithms 必须包含非空的算法名称和版本。")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def files_must_be_unique(self) -> "DataPackManifest":
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("数据包 manifest 包含重复文件路径。")
        return self

    @classmethod
    def load(cls, path: Path) -> "DataPackManifest":
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DataContractError(f"无法读取数据包 manifest：{exc}") from exc

    def write(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    def verify_files(self, root: Path) -> None:
        resolved_root = root.resolve()
        for item in self.files:
            target = (resolved_root / item.path).resolve()
            if resolved_root not in target.parents:
                raise DataContractError(f"数据包文件越界：{item.path}")
            if not target.is_file():
                raise DataContractError(f"数据包缺少文件：{item.path}")
            if target.stat().st_size != item.size:
                raise DataContractError(f"数据包文件大小不匹配：{item.path}")
            if sha256_file(target) != item.sha256:
                raise DataContractError(f"数据包文件校验失败：{item.path}")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
