import {beforeEach, expect, it} from "vitest";
import {emptyRequirements} from "./conversation";
import {applySelectedContent, consumeTransfer, readTransfer, transferUrl, undoSelectedContent} from "./contentTransfer";

beforeEach(() => localStorage.clear());
it("routes tags by type, deduplicates canonical spellings, and undoes only this transfer", () => {
  const original = emptyRequirements();
  original.layers.subject = {text: "保留未发送描述", locked: true, character_tags: ["hatsune miku"]};
  original.layers.style.artists = ["existing_artist"];
  const result = applySelectedContent(original, [
    {name: "hatsune_miku", category: "character"}, {name: "vocaloid", category: "copyright"},
    {name: "@existing artist", category: "artist"}, {name: "new_artist", category: "artist"},
    {name: "blue_sky", category: "general"},
  ]);
  expect(result.added).toHaveLength(3);
  expect(result.requirements.layers.subject).toMatchObject({text: "保留未发送描述", locked: true, character_tags: ["hatsune miku"], series_tags: ["vocaloid"], general_tags: ["blue sky"]});
  result.requirements.layers.lighting.text = "后来追加的光线";
  const undone = undoSelectedContent(result.requirements, result.added);
  expect(undone.layers.subject).toEqual(original.layers.subject);
  expect(undone.layers.lighting.text).toBe("后来追加的光线");
  expect(undone.layers.style.artists).toEqual(["existing artist"]);
});
it("keeps transfers out of URL text and consumes them only once", () => {
  const url = transferUrl([{name: "private_tag", category: "general"}], "new");
  expect(url).not.toContain("private_tag");
  const id = new URL(url, "http://localhost").searchParams.get("transfer")!;
  expect(readTransfer(id)?.destination).toBe("new");
  consumeTransfer(id); expect(readTransfer(id)).toBeNull();
});
it("rejects malformed and over-limit selections without changing the original draft", () => {
  expect(() => transferUrl([{name: "bad,tag", category: "general"}])).toThrow();
  expect(() => transferUrl([{name: "@bad@artist", category: "artist"}])).toThrow();
  expect(() => transferUrl([{name: "@@valid_artist", category: "artist"}])).not.toThrow();
  const original = emptyRequirements(); original.layers.subject.character_tags = Array.from({length: 32}, (_, i) => `hero ${i}`);
  expect(() => applySelectedContent(original, [{name: "one_more", category: "character"}])).toThrow("上限");
  expect(original.layers.subject.character_tags).toHaveLength(32);
});
it("honors the shared general/meta limit and the full 192-tag compilation capacity", () => {
  const original = emptyRequirements();
  original.layers.subject.character_tags = Array.from({length: 32}, (_, i) => `hero ${i}`);
  original.layers.subject.series_tags = Array.from({length: 32}, (_, i) => `series ${i}`);
  original.layers.subject.general_tags = Array.from({length: 63}, (_, i) => `general ${i}`);
  original.layers.style.artists = Array.from({length: 32}, (_, i) => `artist ${i}`);
  original.layers.style.manual_artist_tags = Array.from({length: 32}, (_, i) => `manual ${i}`);
  const full = applySelectedContent(original, [{name: "meta_tag", category: "meta"}]);
  expect(full.requirements.layers.subject.general_tags).toHaveLength(64);
  expect(() => applySelectedContent(full.requirements, [{name: "another", category: "general"}])).toThrow("上限");
  expect(undoSelectedContent(full.requirements, full.added)).toEqual(original);
  expect(original.layers.subject.general_tags).toHaveLength(63);
});
