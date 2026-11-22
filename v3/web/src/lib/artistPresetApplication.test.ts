import {describe, expect, it} from "vitest";
import {emptyRequirements, type LocalConversation} from "./conversation";
import {defaultGenerationSettings} from "./generationSettings";
import {applyArtistPreset, removeArtistPreset, reconcileArtistPresetEdit, reconcileArtistPresetCompiled,
  type ArtistPresetSnapshot} from "./artistPresetApplication";

const local = (): LocalConversation => ({baseRevision: 1, delta: "", mode: "faithful", requirements: emptyRequirements(),
  positive: "girl, garden", negative: "blur", model: "anima", settings: defaultGenerationSettings()});
const preset = (positive = "(@a:1.2), @b", id = "one"): ArtistPresetSnapshot => ({id, revision: 1, name: id, positive,
  negative: "bad style", model_family: "anima", model_label: "Anima base", syntax: "comfy", source_url: "", content_hash: "a".repeat(64)});

describe("managed artist preset text", () => {
  it("applies and replaces a single literal block without accumulating old text", () => {
    const original = local(), first = applyArtistPreset(original, preset("  (@a:1.2), @b  "));
    expect(first.positive).toBe(original.positive + "\n\n  (@a:1.2), @b  ");
    const second = applyArtistPreset(first, preset("@c, @d", "two"));
    expect(second.positive).toBe(original.positive + "\n\n@c, @d");
    expect(removeArtistPreset(second)).toEqual(original);
    expect(first.requirements.layers.style.artist_preset?.positive).toBe("  (@a:1.2), @b  ");
  });
  it("does not remove identical text authored outside the managed block", () => {
    const original = {...local(), positive: "(@a:1.2), @b\n\ngirl"};
    const first = applyArtistPreset(original, preset());
    expect(removeArtistPreset(first).positive).toBe(original.positive);
  });
  it("maps insertions and deletions outside managed ranges", () => {
    const first = applyArtistPreset(local(), preset());
    const prepend = reconcileArtistPresetEdit(first, {...first, positive: "1girl, " + first.positive});
    const append = reconcileArtistPresetEdit(prepend, {...prepend, positive: prepend.positive + ", sunset"});
    expect(removeArtistPreset(append).positive).toBe("1girl, girl, garden, sunset");
    const shorten = reconcileArtistPresetEdit(first, {...first, positive: first.positive.replace("girl, garden", "girl")});
    expect(removeArtistPreset(shorten).positive).toBe("girl");
  });
  it("detaches both targets on editing one raw block and preserves all text", () => {
    const first = applyArtistPreset(local(), preset());
    const edited = {...first, negative: first.negative.replace("bad style", "my style")};
    const after = reconcileArtistPresetEdit(first, edited);
    expect(after.requirements.layers.style.artist_preset).toBeUndefined();
    expect(after.artistPresetPlacement).toBeUndefined();
    expect(after.artistPresetCustomized).toBe("one");
    expect(after.positive).toBe(edited.positive);
    expect(after.negative).toBe(edited.negative);
  });
  it("reconstructs unique raw ranges after an AI result without claiming surrounding text", () => {
    const value = applyArtistPreset(local(), preset());
    delete value.artistPresetPlacement;
    value.positive = "new scene, " + preset().positive + ", painting";
    const after = reconcileArtistPresetCompiled(value);
    expect(removeArtistPreset(after).positive).toBe("new scene, , painting");
  });
  it("detaches ambiguous or missing compiled blocks rather than deleting guessed content", () => {
    const value = applyArtistPreset(local(), preset());
    delete value.artistPresetPlacement;
    value.positive += "\n" + preset().positive;
    const after = reconcileArtistPresetCompiled(value);
    expect(after.requirements.layers.style.artist_preset).toBeUndefined();
    expect(removeArtistPreset(after).positive).toBe(value.positive);
  });
  it("supports negative-only presets and clearing them", () => {
    const value = applyArtistPreset(local(), preset(""));
    expect(value.positive).toBe(local().positive);
    expect(removeArtistPreset(value)).toEqual(local());
  });
  it("keeps unknown models and copied frozen data without retaining mutable input", () => {
    const source = preset(); source.model_family = "unknown";
    const value = applyArtistPreset(local(), source);
    source.positive = "changed";
    expect(value.requirements.layers.style.artist_preset?.positive).not.toBe("changed");
    expect(value.requirements.layers.style.artist_preset?.model_family).toBe("unknown");
  });
  it("rejects oversize combined prompts before changing state", () => {
    const original = {...local(), positive: "x".repeat(20000)};
    expect(() => applyArtistPreset(original, preset())).toThrow("20000");
    expect(original.requirements.layers.style.artist_preset).toBeUndefined();
  });
  it("does not accumulate separators when replacing after repeated server reloads", () => {
    let value = applyArtistPreset(local(), preset());
    for (let index = 0; index < 4; index++) {
      delete value.artistPresetPlacement;
      value = applyArtistPreset(reconcileArtistPresetCompiled(value), preset("@c, @d", "two"));
    }
    expect(value.positive).toBe(local().positive + "\n\n@c, @d");
  });
  it("detaches malformed historical snapshots without touching or guessing prompt text", () => {
    const value = applyArtistPreset(local(), preset());
    Object.assign(value.requirements.layers.style.artist_preset!, {positive: ["@a"]});
    const after = reconcileArtistPresetCompiled(value);
    expect(after.requirements.layers.style.artist_preset).toBeUndefined();
    expect(after.positive).toBe(value.positive);
  });
});
