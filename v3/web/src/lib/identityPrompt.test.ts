import {expect,it} from "vitest";
import {emptyRequirements} from "./conversation";
import type {ArtistPresetSnapshot} from "./artistPresetApplication";
import {overlayIdentityTags} from "./identityPrompt";

it("adds explicit character, series and artist tags without rewriting the existing prompt",()=>{
  const before=emptyRequirements(),after=emptyRequirements();
  after.layers.subject.character_tags=["Shana"];
  after.layers.subject.series_tags=["Shakugan_No_Shana"];
  after.layers.style.manual_artist_tags=["@Some_Artist"];
  expect(overlayIdentityTags("An adult woman holds a book.\nKeep this exact wording.",after,before)).toBe("shana, shakugan no shana, @some artist, An adult woman holds a book.\nKeep this exact wording.");
});
it("keeps selected weighted tags and preserves an unchanged prompt byte for byte",()=>{
  const before=emptyRequirements(),after=emptyRequirements();after.layers.subject.character_tags=["shana"];
  const text="((Shana:1.2)),  blue eyes\nstanding by a window";
  expect(overlayIdentityTags(text,after,before)).toBe(text);
  expect(overlayIdentityTags(text,after,after)).toBe(text);
});
it("removes complete old identity tokens but keeps names embedded in prose",()=>{
  const before=emptyRequirements(),after=emptyRequirements();before.layers.subject.character_tags=["shana"];
  expect(overlayIdentityTags("(Shana:1.2), blue coat\nA poster says Shana beside her.",after,before)).toBe("blue coat\nA poster says Shana beside her.");
  expect(overlayIdentityTags("blue coat, [shana]",after,before)).toBe("blue coat");
});
it("keeps a literal artist preset intact while removing the same tag outside it",()=>{
  const before=emptyRequirements(),after=emptyRequirements();
  const preset={positive:"(@same:0.8), blue lines\n  literal detail",negative:""} as ArtistPresetSnapshot;
  before.layers.style.artist_preset=preset;after.layers.style.artist_preset=preset;
  before.layers.style.manual_artist_tags=["same"];
  const text="@same, adult woman\n\n"+preset.positive;
  const changed=overlayIdentityTags(text,after,before);
  expect(changed).toBe("adult woman\n\n"+preset.positive);
});
it("clears the prompt when its only content was an explicitly removed managed tag",()=>{
  const before=emptyRequirements(),after=emptyRequirements();before.layers.subject.character_tags=["shana"];
  expect(overlayIdentityTags("((shana)),\n",after,before)).toBe("");
});
it("keeps literal parentheses and exact manually written text when no identity selection changes",()=>{
  const before=emptyRequirements(),after=emptyRequirements();before.layers.subject.character_tags=["hero_(game)"];after.layers.subject.character_tags=["hero (game)"];
  const text="  User explicitly removed the tag.\nDo not silently restore it.  ";
  expect(overlayIdentityTags(text,after,before)).toBe(text);
});
it("prefers one existing weighted occurrence over a duplicate bare tag",()=>{
  const before=emptyRequirements(),after=emptyRequirements();after.layers.subject.character_tags=["shana"];
  expect(overlayIdentityTags("(shana:1.2), shana, adult woman",after,before)).toBe("(shana:1.2), adult woman");
});
it("removes a trailing run of managed tags and separators without leaving dangling commas",()=>{
  const before=emptyRequirements(),after=emptyRequirements();before.layers.subject.character_tags=["shana"];before.layers.style.manual_artist_tags=["some_artist"];
  expect(overlayIdentityTags("adult woman,\nshana,\n@some_artist,\n",after,before)).toBe("adult woman");
});
it("does not restore a manually removed selected tag when another identity is added",()=>{
  const before=emptyRequirements(),after=emptyRequirements();
  before.layers.subject.character_tags=["shana"];
  after.layers.subject.character_tags=["shana"];
  after.layers.style.manual_artist_tags=["new artist"];
  expect(overlayIdentityTags("adult woman, garden",after,before)).toBe("@new artist, adult woman, garden");
});
it("does not restore a manually removed selected artist when another identity is removed",()=>{
  const before=emptyRequirements(),after=emptyRequirements();
  before.layers.subject.character_tags=["shana"];
  before.layers.style.manual_artist_tags=["old artist"];
  after.layers.style.manual_artist_tags=["old artist"];
  expect(overlayIdentityTags("shana, adult woman",after,before)).toBe("adult woman");
});
