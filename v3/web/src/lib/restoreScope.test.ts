import {expect,it} from "vitest";
import {restoreContent} from "./restoreScope";
import {emptyRequirements,type LocalConversation} from "./conversation";
import {defaultGenerationSettings} from "./generationSettings";
import {applyArtistPreset,removeArtistPreset,type ArtistPresetSnapshot} from "./artistPresetApplication";
it("restores historical artist ownership independently of the current text offsets",()=>{
 const base:LocalConversation={baseRevision:7,delta:"unsent",positive:"scene",negative:"",mode:"expand",requirements:emptyRequirements(),model:"anima",settings:defaultGenerationSettings()};
 const preset:ArtistPresetSnapshot={id:"p",revision:1,name:"one",positive:"@a, @b",negative:"",model_family:"anima",model_label:"Anima",syntax:"comfy",source_url:"",content_hash:"a".repeat(64)};
 const historical=applyArtistPreset(base,preset);
 const current=applyArtistPreset({...base,positive:"much longer scene"},{...preset,id:"p2",positive:"@c, @d"});
 const restored=restoreContent(current,historical,"V1");
 expect(restored.requirements.layers.style.artist_preset!.id).toBe("p");
 expect(removeArtistPreset(restored).positive.trim()).toBe("scene");
 expect(restored.delta).toBe("unsent");
});
it("continues historical content and locks without rebinding model, LoRA or environment",()=>{
 const requirements=emptyRequirements();requirements.layers.subject.text="old subject";requirements.prompt_locks=[{target:"positive",text:"blue"}];
 const now:LocalConversation={baseRevision:7,delta:"unsent",positive:"new",negative:"",mode:"expand",requirements:emptyRequirements(),model:"current",settings:defaultGenerationSettings(),workflowSnapshotRunId:"run"};
 const old={...now,positive:"old",mode:"faithful" as const,requirements,model:"old",settings:{...now.settings,steps:35}};
 const result=restoreContent(now,old,"V2");expect(result.positive).toBe("old");expect(result.requirements.layers.subject.text).toBe("old subject");expect(result.model).toBe("current");expect(result.settings).toEqual(now.settings);expect(result.delta).toBe("unsent");expect(result.requirements.loras).toEqual(now.requirements.loras);
});
