"""Clipboard file copy contracts; tests never touch the real system clipboard."""

from io import BytesIO
from pathlib import Path
import struct

from PIL import Image
import pytest

from anima_prompt_studio_v3.runtime import image_clipboard


def test_windows_copy_prepares_unicode_hdrop_and_original_png_before_publish(tmp_path, monkeypatch):
    path = tmp_path / "原图🌟.png"
    image = Image.new("RGBA", (17, 9), (10, 20, 30, 128))
    image.save(path, format="PNG", pnginfo=None)
    source_bytes = path.read_bytes()
    published = []
    monkeypatch.setattr(image_clipboard, "_is_windows", lambda: True)
    monkeypatch.setattr(image_clipboard, "_publish", published.append)

    assert image_clipboard.copy_image_file(path) is None

    assert len(published) == 1
    payload = published[0]
    assert payload.path == path.resolve()
    assert payload.png == source_bytes
    assert path.read_bytes() == source_bytes
    offset, x, y, nonclient, wide = struct.unpack("<IiiII", payload.dropfiles[:20])
    assert (offset, x, y, nonclient, wide) == (20, 0, 0, 0, 1)
    assert payload.dropfiles[20:] == (str(path.resolve()) + "\0\0").encode("utf-16-le")


def test_non_png_first_frame_stays_full_size_in_png_and_dib(tmp_path, monkeypatch):
    path = tmp_path / "animated.gif"
    red = Image.new("RGB", (31, 23), "red")
    blue = Image.new("RGB", (31, 23), "blue")
    red.save(path, save_all=True, append_images=[blue], duration=100, loop=0)
    original = path.read_bytes()
    published = []
    monkeypatch.setattr(image_clipboard, "_is_windows", lambda: True)
    monkeypatch.setattr(image_clipboard, "_publish", published.append)

    image_clipboard.copy_image_file(path)

    payload = published[0]
    with Image.open(BytesIO(payload.png)) as pasted:
        assert pasted.size == (31, 23)
        assert pasted.getpixel((0, 0))[:3] == (255, 0, 0)
    size, width, height, planes, bits, compression, image_size, *_ = struct.unpack("<IiiHHIIiiII", payload.dib[:40])
    assert (size, width, height, planes, bits, compression, image_size) == (40, 31, 23, 1, 32, 0, 31 * 23 * 4)
    assert len(payload.dib) == 40 + 31 * 23 * 4
    assert path.read_bytes() == original


def test_exif_oriented_jpeg_rotates_png_and_dib_without_changing_source(tmp_path, monkeypatch):
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (40, 20), "red")
    for x in range(20, 40):
        for y in range(20):
            image.putpixel((x, y), (0, 0, 255))
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise when displayed.
    image.save(path, format="JPEG", quality=100, exif=exif)
    original = path.read_bytes()
    published = []
    monkeypatch.setattr(image_clipboard, "_is_windows", lambda: True)
    monkeypatch.setattr(image_clipboard, "_publish", published.append)

    image_clipboard.copy_image_file(path)

    payload = published[0]
    with Image.open(BytesIO(payload.png)) as pasted:
        assert pasted.size == (20, 40)
        rgba = pasted.convert("RGBA")
        top = rgba.getpixel((10, 5))
        bottom = rgba.getpixel((10, 35))
        assert top[0] > top[2]  # Original left red half is now above.
        assert bottom[2] > bottom[0]
        assert payload.dib[40:] == rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
    _, width, height, *_ = struct.unpack("<IiiHHIIiiII", payload.dib[:40])
    assert (width, height) == (20, 40)
    assert path.read_bytes() == original
    assert payload.dropfiles[20:] == (str(path.resolve()) + "\0\0").encode("utf-16-le")


def test_bad_source_does_not_call_clipboard_publisher(tmp_path, monkeypatch):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    published = []
    monkeypatch.setattr(image_clipboard, "_is_windows", lambda: True)
    monkeypatch.setattr(image_clipboard, "_publish", published.append)

    with pytest.raises(image_clipboard.ClipboardWriteError):
        image_clipboard.copy_image_file(path)
    assert published == []


def test_non_windows_is_explicitly_unsupported_before_reading_file(tmp_path, monkeypatch):
    published = []
    monkeypatch.setattr(image_clipboard, "_is_windows", lambda: False)
    monkeypatch.setattr(image_clipboard, "_publish", published.append)

    with pytest.raises(image_clipboard.ClipboardUnsupportedError, match="Windows"):
        image_clipboard.copy_image_file(tmp_path / "missing.png")
    assert published == []


class FakeWin32:
    def __init__(self, *, open_failures=0, failed_format=None):
        self.events = []
        self.next_handle = 100
        self.open_failures = open_failures
        self.failed_format = failed_format

    def register_format(self, name):
        self.events.append(("register", name))
        return {"Preferred DropEffect": 700, "PNG": 701}[name]

    def alloc(self, data):
        handle = self.next_handle
        self.next_handle += 1
        self.events.append(("alloc", handle, bytes(data)))
        return handle

    def free(self, handle):
        self.events.append(("free", handle))

    def create_owner(self):
        self.events.append(("owner",))
        return 55

    def open(self, owner):
        self.events.append(("open", owner))
        if self.open_failures:
            self.open_failures -= 1
            return False
        return True

    def empty(self):
        self.events.append(("empty",))
        return True

    def set(self, format_id, handle):
        self.events.append(("set", format_id, handle))
        return format_id != self.failed_format

    def close(self):
        self.events.append(("close",))

    def destroy_owner(self, owner):
        self.events.append(("destroy", owner))


def payload(tmp_path):
    return image_clipboard._PreparedImage(tmp_path / "original.png", b"drop", b"png", b"dib")


def test_native_publish_preallocates_then_writes_copy_effect_file_png_and_dib(tmp_path, monkeypatch):
    native = FakeWin32(open_failures=2)
    monkeypatch.setattr(image_clipboard, "_windows_api", lambda: native)
    monkeypatch.setattr(image_clipboard.time, "sleep", lambda _: None)

    image_clipboard._publish(payload(tmp_path))

    events = native.events
    assert max(i for i, event in enumerate(events) if event[0] == "alloc") < events.index(("empty",))
    assert [event for event in events if event[0] == "open"] == [("open", 55)] * 3
    assert [event[:2] for event in events if event[0] == "set"] == [
        ("set", 700), ("set", 15), ("set", 701), ("set", 8),
    ]
    effect_handle = next(event[2] for event in events if event[:2] == ("set", 700))
    assert next(event[2] for event in events if event[:2] == ("alloc", effect_handle)) == struct.pack("<I", 1)
    assert not [event for event in events if event[0] == "free"]
    assert events[-2:] == [("close",), ("destroy", 55)]


def test_native_busy_clipboard_keeps_prior_contents_and_frees_all_allocations(tmp_path, monkeypatch):
    native = FakeWin32(open_failures=999)
    monkeypatch.setattr(image_clipboard, "_windows_api", lambda: native)
    monkeypatch.setattr(image_clipboard.time, "sleep", lambda _: None)

    with pytest.raises(image_clipboard.ClipboardWriteError):
        image_clipboard._publish(payload(tmp_path))

    assert ("empty",) not in native.events
    assert len([event for event in native.events if event[0] == "open"]) <= 8
    assert {event[1] for event in native.events if event[0] == "free"} == {
        event[1] for event in native.events if event[0] == "alloc"
    }
    assert native.events[-1] == ("destroy", 55)


def test_optional_bitmap_failure_keeps_file_copy_and_frees_untransferred_memory(tmp_path, monkeypatch):
    native = FakeWin32(failed_format=8)
    monkeypatch.setattr(image_clipboard, "_windows_api", lambda: native)

    image_clipboard._publish(payload(tmp_path))

    drop_handle = next(event[2] for event in native.events if event[:2] == ("set", 15))
    dib_handle = next(event[2] for event in native.events if event[:2] == ("set", 8))
    assert ("free", dib_handle) in native.events
    assert ("free", drop_handle) not in native.events


def test_copy_effect_failure_never_publishes_a_file_that_could_move(tmp_path, monkeypatch):
    native = FakeWin32(failed_format=700)
    monkeypatch.setattr(image_clipboard, "_windows_api", lambda: native)

    with pytest.raises(image_clipboard.ClipboardWriteError):
        image_clipboard._publish(payload(tmp_path))

    assert not [event for event in native.events if event[:2] == ("set", 15)]
    assert {event[1] for event in native.events if event[0] == "free"} == {
        event[1] for event in native.events if event[0] == "alloc"
    }
