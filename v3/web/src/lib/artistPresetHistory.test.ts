import {expect, it} from "vitest";
import {emptyRequirements, type LocalConversation} from "./conversation";
import {defaultGenerationSettings} from "./generationSettings";
import {applyArtistPreset, removeArtistPreset, reconcileArtistPresetCompiled, type ArtistPresetSnapshot} from "./artistPresetApplication";
import {operationBetween, replayOperation} from "./editorHistory";

const local = (): LocalConversation => ({baseRevision: 1, delta: "", positive: "girl", negative: "", mode: "faithful",
  requirements: emptyRequirements(), model: "anima", settings: defaultGenerationSettings()});
const preset = (name: string, positive: string): ArtistPresetSnapshot => ({id: name, revision: 1, name, positive, negative: "",
  model_family: "anima", model_label: "Anima base", syntax: "comfy", source_url: "", content_hash: "a".repeat(64)});

it("undoes replacement, AI rewrite, original apply and redoes without losing ownership", () => {
  const initial = local(), first = applyArtistPreset(initial, preset("first", "(@a:1.1), @b"));
  const apply = operationBetween(initial, first, "import", "调用画师串", 1)!;
  const ai = reconcileArtistPresetCompiled({...first, artistPresetPlacement: undefined, positive: "girl, sunset\n\n(@a:1.1), @b"});
  const rewrite = operationBetween(first, ai, "ai", "日落", 1)!;
  const replaced = applyArtistPreset(ai, preset("second", "@c, @d"));
  const replace = operationBetween(ai, replaced, "import", "替换画师串", 1)!;
  const undoReplacement = replayOperation(replaced, replace, "undo");
  expect(undoReplacement).toEqual(ai);
  expect(removeArtistPreset(undoReplacement).positive.trim()).toBe("girl, sunset");
  const undoAi = replayOperation(undoReplacement, rewrite, "undo");
  expect(undoAi).toEqual(first);
  expect(replayOperation(undoAi, apply, "undo")).toEqual(initial);
  expect(replayOperation(undoAi, rewrite, "redo")).toEqual(ai);
});
