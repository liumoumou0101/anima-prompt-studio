import {useEffect, useRef, useState} from "react";
import {useOutletContext} from "react-router-dom";
import {isAnimaModel, MOSS_IMAGE_MODEL} from "./modelProfiles";
import type {ModelProfileOption, WorkspaceRecord} from "./types";

export {isAnimaModel, MOSS_IMAGE_MODEL};

export function workbenchPathForModel(model: string, profiles?: ModelProfileOption[]): "/workbench" | "/moss" {
  if (!model) throw new Error("缺少来源模型，无法确定应打开的工作台。");
  if (model === MOSS_IMAGE_MODEL) return "/moss";
  if (isAnimaModel(model, profiles)) return "/workbench";
  throw new Error(`模型 ${model} 暂无对应工作台。`);
}

export function workspaceUrl(record: Pick<WorkspaceRecord,"id"|"draft">, profiles?: ModelProfileOption[]): string {
  if (!record?.id || !record.draft?.model_profile) throw new Error("创作记录缺少会话或来源模型，无法打开工作台。");
  return `${workbenchPathForModel(record.draft.model_profile, profiles)}?workspace=${encodeURIComponent(record.id)}`;
}

export function useOpenWorkspace() {
  const profiles = useOutletContext<ModelProfileOption[] | undefined>();
  const [destination,setDestination] = useState("");
  const mounted = useRef(true);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
  function openWorkspace(record: Pick<WorkspaceRecord,"id"|"draft">) {
    if (!mounted.current) return false;
    setDestination(workspaceUrl(record, profiles));
    return true;
  }
  return {destination,openWorkspace};
}
