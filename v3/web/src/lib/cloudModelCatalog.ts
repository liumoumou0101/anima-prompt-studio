import type {CreationConfiguration, WorkflowParameterSchema} from "./types";
import {applyRecipe, resolveConfiguration} from "./creationConfiguration";
import {validateParameter} from "./workflowParameterSchema";

export type CloudCatalogStatus = "unchecked" | "ready" | "stale" | "unavailable" | "unsupported";
export interface CloudCatalogAsset {path:string; category:string; filename:string; ready:boolean}
export interface CloudCatalogDefaults {steps?:number; cfg?:number; sampler?:string; scheduler?:string}
export interface CloudWorkflowMapping {workflow_profile_id:string; revision:string; mapping:Record<string,string>; errors:string[]}
export interface CloudCatalogItem {
  id:string; display_name:string; family:string; supported:boolean; ready:boolean; selected_for_startup:boolean;
  suggested_defaults:CloudCatalogDefaults; assets:CloudCatalogAsset[]; workflow_mappings:CloudWorkflowMapping[];
}
export interface CloudCatalogResponse {
  remote_profile_id:string; session_id:string; environment_epoch:number; status:CloudCatalogStatus;
  checked_at:number|null; message:string; runtime_id:string|null; items:CloudCatalogItem[];
}
export interface ApplyCloudMappingRequest {model_id:string; workflow_profile_id:string; session_id:string; environment_epoch:number}

// A catalog can suggest only these four parameters. All other creative state stays in the workbench.
const suggestedKeys = ["steps","cfg","sampler","scheduler"] as const;
export function cloudSuggestionPreview(defaults:CloudCatalogDefaults, configuration:CreationConfiguration, schema:WorkflowParameterSchema) {
  const current=resolveConfiguration(configuration,schema).values;
  const changes:{key:string;label:string;from:number|string;to:number|string}[]=[];
  const errors:string[]=[];
  const overrides:Record<string,number|string>={};
  if(!configuration.workflow.id || schema.workflowId!==configuration.workflow.id || schema.templateRevision!==configuration.workflow.revision) {
    return {changes,errors:["请先选择并检查当前兼容工作流的参数声明"],configuration};
  }
  for(const key of suggestedKeys) {
    const value=defaults[key];if(value===undefined)continue;
    const field=schema.fields.find(item=>item.key===key);
    // The catalog API already validates exact live ComfyUI enums. Template schemas may
    // omit enum declarations; when present, validateParameter enforces them as well.
    if(!field || validateParameter(field,value) || (field.readOnlyReason && value!==field.default)) {
      errors.push(`${field?.label || key} 的云端建议不符合当前工作流约束`);continue;
    }
    overrides[key]=value;
    if(current[key]!==value)changes.push({key,label:field.label,from:current[key],to:value});
  }
  // Recommendations belong to this model/workflow baseline. Only subsequent
  // hand edits become overrides that can survive a model or workflow change.
  return {changes,errors,configuration:Object.keys(overrides).length
    ?applyRecipe(configuration,{id:"custom",parameters:overrides}):configuration};
}
export function cloudMappingForCurrentWorkflow(catalog:CloudCatalogResponse, item:CloudCatalogItem, configuration:CreationConfiguration) {
  if(catalog.status!=="ready" || !item.supported || !item.ready)return undefined;
  return item.workflow_mappings.find(mapping=>mapping.workflow_profile_id===configuration.workflow.id
    && mapping.revision===configuration.workflow.revision && !mapping.errors.length && Object.keys(mapping.mapping).length>0);
}
