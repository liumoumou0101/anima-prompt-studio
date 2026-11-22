from io import BytesIO

from PIL import Image
import pytest

from anima_prompt_studio_v3.storage.reference_thumbnails import ReferenceThumbnailCache
from anima_prompt_studio_v3.storage.reference_examples import ExampleStore, ExampleMetadata
from anima_prompt_studio_v3.core.requirements import WorkbenchError
from test_reference_examples import picture


def test_cache_survives_restart_without_decoding_original(tmp_path, monkeypatch):
    cache = ReferenceThumbnailCache(tmp_path / "cache")
    first = cache.get("ex_one", picture(), 320)
    reopened = ReferenceThumbnailCache(cache.root)
    monkeypatch.setattr(reopened, "render", lambda *_: pytest.fail("cache hit must not re-render original"))
    assert reopened.get("ex_one", picture(), 320) == first


def test_cache_separates_image_content_size_and_example(tmp_path):
    cache = ReferenceThumbnailCache(tmp_path / "cache")
    for example_id, data, size in [("ex_one",picture(),320),("ex_one",picture(),640),
                                  ("ex_one",picture("JPEG"),320),("ex_two",picture(),320)]:
        cache.get(example_id,data,size)
    assert len(list(cache.root.glob("*.jpg"))) == 4


def test_corrupt_cache_rebuilt_and_small_budget_evicts_only_cache_files(tmp_path):
    cache = ReferenceThumbnailCache(tmp_path / "cache")
    expected = cache.get("ex_one",picture(),320)
    next(cache.root.glob("*.jpg")).write_bytes(b"broken")
    assert cache.get("ex_one",picture(),320) == expected
    unrelated = cache.root / "user-notes.txt"
    unrelated.write_text("keep")
    cache.max_bytes = 1
    cache.get("ex_two",picture(),640)
    assert not list(cache.root.glob("*.jpg"))
    assert unrelated.read_text() == "keep"


def test_deleted_or_missing_original_never_resurrected_by_cache(tmp_path):
    store = ExampleStore(tmp_path / "examples.db")
    example = store.create(picture(),"test",ExampleMetadata())
    store.thumbnail(example["id"])
    store.delete(example["id"],1)
    with pytest.raises(ValueError):
        store.thumbnail(example["id"])
    second = store.create(picture(),"test",ExampleMetadata())
    store.thumbnail(second["id"])
    store.content(second["id"])[0].unlink()
    with pytest.raises(ValueError):
        store.thumbnail(second["id"])


def test_exif_rotation_applies_before_resize(tmp_path):
    image = Image.new("RGB",(200,100),"red")
    exif = Image.Exif()
    exif[274] = 6
    data = BytesIO()
    image.save(data,"JPEG",exif=exif)
    result = ReferenceThumbnailCache(tmp_path).get("ex_one",data.getvalue(),100)
    with Image.open(BytesIO(result)) as thumbnail:
        assert thumbnail.size == (50,100)


def test_original_corrupted_after_cache_creation_returns_domain_error(tmp_path):
    store = ExampleStore(tmp_path / "examples.db")
    example = store.create(picture(), "test", ExampleMetadata())
    store.thumbnail(example["id"])
    store.content(example["id"])[0].write_bytes(b"corrupted original")
    with pytest.raises(WorkbenchError) as error:
        store.thumbnail(example["id"])
    assert error.value.code == "invalid_reference_image"


def test_unwritable_cache_still_returns_thumbnail(tmp_path):
    root = tmp_path / "cache"
    root.write_text("a file prevents cache directory creation")
    result = ReferenceThumbnailCache(root).get("ex_one", picture(), 320)
    with Image.open(BytesIO(result)) as thumbnail:
        thumbnail.load()
        assert thumbnail.format == "JPEG"
    assert root.read_text() == "a file prevents cache directory creation"


def test_oversized_original_rejected_before_decoding(tmp_path, monkeypatch):
    class OversizedImage:
        format = "PNG"
        n_frames = 1
        width = 10000
        height = 10000

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def load(self):
            pytest.fail("oversized image must not be decoded")

    monkeypatch.setattr(Image, "open", lambda *_: OversizedImage())
    with pytest.raises(ValueError, match="Invalid reference image"):
        ReferenceThumbnailCache(tmp_path).get("ex_one", b"image header", 320)
