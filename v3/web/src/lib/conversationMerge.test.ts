import {describe, expect, it} from "vitest";
import {changeGenerationModel,defaultGenerationSettings} from "./generationSettings";
import {emptyRequirements, type LocalConversation} from "./conversation";
import {conflictValueLabel,mergeConversation,resolveConversationConflicts} from "./conversationMerge";
import {applyArtistPreset, type ArtistPresetSnapshot} from "./artistPresetApplication";
import {configurationToGenerationPayload,setParameter,settingsFromConfiguration} from "./creationConfiguration";
import {basicWorkflowSchema} from "./workflowParameterSchema";
import type {GenerationTarget} from "./types";

function draft(): LocalConversation {
  const requirements = emptyRequirements();
  requirements.layers.subject.text = "蓝色外套";
  requirements.layers.lighting.text = "傍晚";
  return {baseRevision: 3, delta: "", mode: "faithful", requirements, positive: "blue coat", negative: "", model: "anima_base_v1", settings: defaultGenerationSettings()};
}

function switchToTurbo() {
  const base=draft();
  const target=(model:string,steps:number,cfg:number)=>({
    workflow_profile_id:model+"-flow",compatible_model_profiles:[model],template_revision:"v1",
    parameter_schema:basicWorkflowSchema(model+"-flow","v1"),default_recipe_id:"baseline",
    generation_recipes:[{id:"baseline",parameters:{steps,cfg,sampler:"euler",scheduler:"normal"}}],
  }) as GenerationTarget;
  base.settings=changeGenerationModel(base.settings,target(base.model,35,4.5),base.model);
  const turbo=structuredClone(base);
  turbo.model="anima_turbo_v1_1";
  turbo.settings=changeGenerationModel(turbo.settings,target(turbo.model,10,1),turbo.model,base.model);
  return {base,turbo};
}

describe("mergeConversation", () => {
  it("keeps a model's complete conditions together when the other window edits the departing model",()=>{
    const {base,turbo}=switchToTurbo();
    const remote=structuredClone(base);
    remote.baseRevision++;
    remote.requirements.loras=[{logical_id:"base-lora",file_name:"base.safetensors",weight:0.8,trigger_words:[],required:true,source:{kind:"user"}}];
    const baseConfig=setParameter(setParameter(base.settings.creation_configuration!,"width",1344),"cfg",8);
    remote.settings=settingsFromConfiguration({...baseConfig,resourceRequirements:remote.requirements.loras},base.settings,base.settings.parameter_schema!);
    remote.workflowSnapshotRunId="base-run";
    remote.requirements.layers.subject.character_tags=["remote character"];
    turbo.positive="local prompt";
    const result=mergeConversation(base,turbo,remote);
    expect(result.conflicts.map(item=>item.path)).toEqual(["generationConditions"]);
    expect(conflictValueLabel(result.conflicts[0],"local")).toContain("10 步");
    expect(conflictValueLabel(result.conflicts[0],"remote")).toContain("CFG 8");
    expect(conflictValueLabel(result.conflicts[0],"local")).not.toContain("parameterOverrides");
    for(const [side,expected] of [["local",turbo],["remote",remote]] as const){
      const resolved=resolveConversationConflicts(result,{generationConditions:side});
      expect(resolved.settings).toEqual(expected.settings);
      expect(resolved.model).toBe(expected.model);
      expect(resolved.workflowSnapshotRunId??null).toBe(expected.workflowSnapshotRunId??null);
      expect(resolved.requirements.loras).toEqual(expected.requirements.loras);
      expect(resolved.positive).toBe("local prompt");
      expect(resolved.requirements.layers.subject.character_tags).toEqual(["remote character"]);
      const payload=configurationToGenerationPayload(resolved.settings.creation_configuration!,resolved.settings.parameter_schema!);
      expect(payload).toMatchObject(side==="local"?{steps:10,width:896,cfg:1}:{steps:35,width:1344,cfg:8});
    }
  });

  it.each(["local","remote"])("merges a switch on the %s side with independent prompt edits",side=>{
    const {base,turbo}=switchToTurbo();
    const text=structuredClone(base);
    text.negative="remote negative";
    // Saving through the server may reorder keys without editing any parameter.
    text.settings=Object.fromEntries(Object.entries(text.settings).reverse()) as typeof text.settings;
    const result=side==="local"?mergeConversation(base,turbo,text):mergeConversation(base,text,turbo);
    expect(result.conflicts).toEqual([]);
    expect(result.merged.model).toBe(turbo.model);
    expect(result.merged.settings).toEqual(turbo.settings);
    expect(result.merged.negative).toBe(text.negative);
  });
  it("keeps artist preset versions atomic when two windows change different fields", () => {
    const preset:ArtistPresetSnapshot={id:"p",revision:1,name:"one",positive:"@a",negative:"",model_family:"anima",model_label:"Anima",syntax:"comfy",source_url:"",content_hash:"a".repeat(64)};
    const base=applyArtistPreset(draft(),preset),local=structuredClone(base),remote=structuredClone(base);
    local.requirements.layers.style.artist_preset!.name="local name";
    remote.requirements.layers.style.artist_preset!.positive="@b";
    const result=mergeConversation(base,local,remote);
    expect(result.conflicts).toHaveLength(1);
    expect(result.conflicts[0].path).toBe("requirements.layers.style.artist_preset");
    expect(result.merged.requirements.layers.style.artist_preset).toEqual(remote.requirements.layers.style.artist_preset);
    expect(resolveConversationConflicts(result,{"requirements.layers.style.artist_preset":"local"}).requirements.layers.style.artist_preset).toEqual(local.requirements.layers.style.artist_preset);
  });
  it("preserves unrelated remote and local leaf edits", () => {
    const base = draft();
    const local = structuredClone(base); local.requirements.layers.composition.text = "居中构图";
    const remote = structuredClone(base); remote.baseRevision = 4; remote.requirements.layers.lighting.text = "清晨";
    const result = mergeConversation(base, local, remote);
    expect(result.conflicts).toEqual([]);
    expect(result.merged.baseRevision).toBe(4);
    expect(result.merged.requirements.layers.lighting.text).toBe("清晨");
    expect(result.merged.requirements.layers.composition.text).toBe("居中构图");
  });

  it("reports same-field edits and defaults unresolved values to remote", () => {
    const base = draft();
    const local = structuredClone(base); local.requirements.layers.subject.text = "红色外套";
    const remote = structuredClone(base); remote.baseRevision = 4; remote.requirements.layers.subject.text = "绿色外套";
    const result = mergeConversation(base, local, remote);
    expect(result.merged.requirements.layers.subject.text).toBe("绿色外套");
    expect(result.conflicts).toEqual([{path: "requirements.layers.subject.text", label: "主体要求", base: "蓝色外套", local: "红色外套", remote: "绿色外套"}]);
    expect(resolveConversationConflicts(result, {"requirements.layers.subject.text": "local"}).requirements.layers.subject.text).toBe("红色外套");
  });

  it("treats arrays as atomic values", () => {
    const base = draft(); base.requirements.layers.subject.general_tags = ["coat"];
    const local = structuredClone(base); local.requirements.layers.subject.general_tags = ["coat", "red"];
    const remote = structuredClone(base); remote.requirements.layers.subject.general_tags = ["coat", "green"];
    const result = mergeConversation(base, local, remote);
    expect(result.conflicts[0]?.path).toBe("requirements.layers.subject.general_tags");
    expect(result.merged.requirements.layers.subject.general_tags).toEqual(["coat", "green"]);
  });

  it("provides readable labels for generation-setting conflicts", () => {
    const base = draft();
    const local = structuredClone(base); local.settings.width = 768;
    const remote = structuredClone(base); remote.settings.width = 1024;
    expect(mergeConversation(base, local, remote).conflicts[0]?.label).toBe("生成设置 · 宽度");
  });

  it("takes remote changes without conflict when the saved local draft was untouched", () => {
    const base = draft();
    const local = structuredClone(base);
    const remote = structuredClone(base); remote.baseRevision = 5; remote.requirements.layers.lighting.text = "清晨";
    const result = mergeConversation(base, local, remote);
    expect(result.conflicts).toEqual([]);
    expect(result.merged.requirements.layers.lighting.text).toBe("清晨");
  });
});
