import type {CreationConfiguration, GenerationTarget, WorkbenchGenerationSettings, WorkflowParameterSchema} from "./types";
import {CORE_PARAMETER_KEYS, isDefaultGenerationSettings, legacyGenerationValues} from "./generationDefaults";
import {schemaForTarget, validateParameter} from "./workflowParameterSchema";
export type {CreationConfiguration, ExecutionPolicy} from "./types";

function baselineForTarget(target?: GenerationTarget) {
  const schema = schemaForTarget(target);
  const recipe = target?.generation_recipes?.find(item=>item.id===target.default_recipe_id) || target?.generation_recipes?.[0];
  const recipeValues = Object.fromEntries(schema.fields.map(field=>[field.key,field.default]));
  for (const [key,value] of Object.entries(recipe?.parameters || {})) {
    if (schema.fields.some(field=>field.key===key)) recipeValues[key]=value;
  }
  return {baseRecipeId:recipe?.id || "custom",recipeValues,workflow:{id:target?.workflow_profile_id || "",revision:target?.template_revision || ""}};
}

export function rebaseConfiguration(current: CreationConfiguration, target?: GenerationTarget): CreationConfiguration {
  return {...current,...baselineForTarget(target)};
}

function newModelConfiguration(modelProfile: string, target?: GenerationTarget): CreationConfiguration {
  return {modelProfile,...baselineForTarget(target),parameterOverrides:{},resourceRequirements:[],seedMode:"random"};
}

export function configurationFromSettings(
  settings: WorkbenchGenerationSettings,
  modelProfile: string,
  target?: GenerationTarget,
  options: {initialize?:boolean;preserveSnapshot?:boolean} = {},
): CreationConfiguration {
  const active = settings.creation_configuration;
  const saved = settings.model_configurations?.[modelProfile];
  const current = active?.modelProfile === modelProfile ? active : saved;
  if (current?.modelProfile === modelProfile) {
    if (options.preserveSnapshot || !target) return current;
    if (current.workflow.id !== target.workflow_profile_id) return rebaseConfiguration(current,target);
    if (current.workflow.revision !== (target.template_revision || "")) {
      return {...current,workflow:{...current.workflow,revision:target.template_revision || ""}};
    }
    return current;
  }
  if (active) return newModelConfiguration(modelProfile,target);
  if (!options.preserveSnapshot && (options.initialize || isDefaultGenerationSettings(settings))) {
    const initial=newModelConfiguration(modelProfile,target);
    const parameterOverrides:Record<string,number|string>={};
    const seedMode=String(settings.seed)==="-1"?"random":"fixed";
    if (seedMode==="fixed") parameterOverrides.seed=settings.seed;
    if (settings.batch_size!==initial.recipeValues.batch_size) parameterOverrides.batch_size=settings.batch_size;
    return {...initial,baseRecipeId:target?initial.baseRecipeId:settings.preset_id,parameterOverrides,seedMode};
  }
  const {preset_id: _preset, ...values} = legacyGenerationValues(settings);
  const savedSchema=settings.parameter_schema;
  const baseline=Object.fromEntries((savedSchema || schemaForTarget()).fields.map(field=>[field.key,field.default]));
  const coreValues = Object.fromEntries(Object.entries({width:settings.width,height:settings.height,...values}).filter(([,v])=>typeof v === "number" || typeof v === "string")) as Record<string,number|string>;
  // Old drafts do not record which fields were edited. Preserve all saved values
  // rather than inferring their provenance from today's defaults or recipes.
  const parameterOverrides = {...coreValues,...settings.workflow_parameter_overrides};
  const workflowId=settings.workflow_profile_id || savedSchema?.workflowId || (!options.preserveSnapshot?target?.workflow_profile_id:"") || "";
  const revision=!options.preserveSnapshot&&target&&workflowId===target.workflow_profile_id
    ?target.template_revision || "":savedSchema?.templateRevision || "";
  return {modelProfile, workflow:{id:workflowId,revision},
    baseRecipeId:settings.preset_id, recipeValues:baseline, parameterOverrides, resourceRequirements:[],seedMode:String(settings.seed) === "-1" ? "random":"fixed"};
}

export function resolveConfiguration(configuration: CreationConfiguration, schema: WorkflowParameterSchema) {
  const values: Record<string,number|string> = {};
  const errors: Record<string,string> = {};
  for (const field of schema.fields) {
    const value = field.key === "seed" && configuration.seedMode === "random" ? "-1" : configuration.parameterOverrides[field.key] ?? configuration.recipeValues[field.key] ?? field.default;
    values[field.key] = field.type === "seed" ? String(value) : value;
    const error = validateParameter(field, values[field.key]);
    if (error) errors[field.key] = error;
    if (field.readOnlyReason && value !== field.default) errors[field.key] = field.readOnlyReason;
  }
  for (const key of Object.keys(configuration.parameterOverrides)) if (!schema.fields.some(field=>field.key===key)) errors[key] = "当前工作流未声明此参数";
  return {values,errors,valid:Object.keys(errors).length===0};
}

export function setParameter(configuration: CreationConfiguration, key:string, value:number|string): CreationConfiguration {
  return {...configuration, ...(key==="seed"?{seedMode:String(value)==="-1"?"random" as const:"fixed" as const}:{}), parameterOverrides:{...configuration.parameterOverrides,[key]:value}};
}
export function resetParameter(configuration: CreationConfiguration, key:string): CreationConfiguration {
  const parameterOverrides = {...configuration.parameterOverrides}; delete parameterOverrides[key];
  return {...configuration,parameterOverrides,...(key==="seed"?{seedMode:String(configuration.recipeValues.seed??"-1")==="-1"?"random" as const:"fixed" as const}:{})};
}
export function recipeDifferences(configuration:CreationConfiguration, recipe:{parameters:Record<string,number|string>}, schema:WorkflowParameterSchema) {
  const current = resolveConfiguration(configuration,schema).values;
  return Object.entries(recipe.parameters).filter(([key,value])=>current[key]!==value).map(([key,to])=>({key,from:current[key],to}));
}
export function applyRecipe(configuration:CreationConfiguration, recipe:{id:string;parameters:Record<string,number|string>}): CreationConfiguration {
  const parameterOverrides = {...configuration.parameterOverrides};
  for (const key of Object.keys(recipe.parameters)) delete parameterOverrides[key];
  return {...configuration,baseRecipeId:recipe.id,recipeValues:{...configuration.recipeValues,...recipe.parameters},parameterOverrides};
}

// The active configuration lives only in creation_configuration. Replacing it,
// including when restoring a run, parks the departing model's last configuration.
export function inactiveModelConfigurations(
  settings: WorkbenchGenerationSettings,
  source: CreationConfiguration | undefined,
  nextModel: string,
): WorkbenchGenerationSettings["model_configurations"] {
  const inactive = {...settings.model_configurations};
  delete inactive[nextModel];
  if (source?.modelProfile && source.modelProfile !== nextModel) {
    inactive[source.modelProfile] = source;
  }
  return Object.keys(inactive).length ? inactive : undefined;
}

export function settingsFromConfiguration(configuration:CreationConfiguration, previous:WorkbenchGenerationSettings, schema:WorkflowParameterSchema): WorkbenchGenerationSettings {
  const {values,errors} = resolveConfiguration(configuration,schema);
  const core = Object.fromEntries(Object.entries(values).filter(([key])=>!errors[key] && CORE_PARAMETER_KEYS.some(field=>field===key)));
  const dimensionsChanged = (core.width ?? previous.width) !== previous.width || (core.height ?? previous.height) !== previous.height;
  return {...previous,...core,preset_id:configuration.baseRecipeId,aspect:dimensionsChanged?"custom":previous.aspect,workflow_profile_id:configuration.workflow.id,
    creation_configuration:configuration,model_configurations:inactiveModelConfigurations(previous,previous.creation_configuration,configuration.modelProfile),
    parameter_schema:schema,workflow_parameter_overrides:{...configuration.parameterOverrides}} as WorkbenchGenerationSettings;
}
export type GenerationParameterPayload = Pick<WorkbenchGenerationSettings,"preset_id"|"steps"|"cfg"|"sampler"|"scheduler"|"seed"|"batch_size">
  & Partial<Pick<WorkbenchGenerationSettings,"width"|"height">>
  & {parameter_schema:WorkflowParameterSchema;workflow_parameter_overrides:Record<string,number|string>};

export function configurationToGenerationPayload(configuration:CreationConfiguration,schema:WorkflowParameterSchema):GenerationParameterPayload {
  const result = resolveConfiguration(configuration,schema);
  if (!result.valid) throw new Error(Object.values(result.errors).join("；"));
  const core = Object.fromEntries(Object.entries(result.values).filter(([key])=>CORE_PARAMETER_KEYS.some(field=>field===key)));
  return {preset_id:configuration.baseRecipeId, ...core, parameter_schema:schema,workflow_parameter_overrides:result.values} as GenerationParameterPayload;
}
