import {layerLabels,type ConversationRecord} from "./conversation";
import {sceneChoice,sceneFields,sceneLabels} from "./sceneDesign";

export function mossWorkspacePrompt(workspace?: ConversationRecord) {
  const draft=workspace?.draft;
  const compiled=draft?.compiled;
  const source=draft?.natural_text || draft?.positive_text || "";
  const negative=draft?.excluded_text || "";
  const requirements=draft?.requirements;
  if(compiled || source || !draft?.reference_pin || !requirements) {
    return {source:compiled?.positive ?? source,negative:compiled?.negative ?? negative,borrowedReference:false};
  }

  // A reference workspace contains only the layers that were actually borrowed.
  const {subject,style,lighting,composition,exclusions}=requirements.layers;
  const positive:string[]=[];
  function line(label:string,...items:(string|undefined)[]) {
    const content=items.filter(item=>item?.trim()).join("、");
    if(content)positive.push(`${label}：${content}`);
  }
  line(layerLabels.subject,subject.text);
  line("角色",...(subject.character_tags || []));
  line("作品",...(subject.series_tags || []));
  line("画面标签",...(subject.general_tags || []));
  line(layerLabels.style,style.text,style.medium);
  line("画师",...new Set([...style.artists,...(style.manual_artist_tags || [])]));
  line("画师串",style.artist_preset?.positive);
  line(layerLabels.lighting,lighting.text);
  line(layerLabels.composition,composition.text);
  if(composition.shot!==composition.design?.shot?.value)line(sceneLabels.shot,composition.shot);
  for(const field of sceneFields) {
    const choice=sceneChoice(requirements,field);
    if(choice?.value)line(sceneLabels[field],choice.target?`${choice.target}：${choice.value}`:choice.value);
  }
  line("资源触发词",...new Set(requirements.loras.filter(item=>item.enabled!==false).flatMap(item=>item.trigger_words)));
  const exclusionsText=[negative,...exclusions.global,...exclusions.scoped.map(item=>`${item.target}：${item.concept}`),style.artist_preset?.negative]
    .filter(item=>item?.trim()) as string[];
  for(const lock of requirements.prompt_locks || []) {
    const lines=lock.target==="positive"?positive:exclusionsText;
    if(lock.text && !lines.some(item=>item.includes(lock.text)))lines.push(lock.text);
  }
  return {source:positive.join("\n"),negative:exclusionsText.join("\n"),borrowedReference:true};
}
