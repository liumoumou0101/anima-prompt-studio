import type {GenerationTarget, WorkbenchGenerationSettings} from "./types";
import {configurationFromSettings, rebaseConfiguration, settingsFromConfiguration} from "./creationConfiguration";
import {schemaForTarget} from "./workflowParameterSchema";

export {defaultGenerationSettings} from "./generationDefaults";
export {inactiveModelConfigurations} from "./creationConfiguration";

export function changeGenerationModel(
  settings: WorkbenchGenerationSettings, target?: GenerationTarget, modelProfile?: string, sourceModel?: string,
): WorkbenchGenerationSettings {
  const compatible = target?.compatible_model_profiles || [];
  const model = modelProfile || (compatible.length === 1 ? compatible[0] : settings.creation_configuration?.modelProfile || sourceModel || compatible[0] || "");
  // A pre-configuration draft has no model identifier in its settings.
  if (!settings.creation_configuration && sourceModel && sourceModel !== model) {
    settings = {...settings,creation_configuration:configurationFromSettings(settings,sourceModel,undefined,{preserveSnapshot:true})};
  }
  let configuration = configurationFromSettings(settings,model,target);
  const sameModel = !settings.creation_configuration || settings.creation_configuration.modelProfile === model;
  // A returning model keeps its remembered workflow while the catalog is offline.
  if ((target || sameModel) && configuration.workflow.id !== (target?.workflow_profile_id || "")) {
    configuration = rebaseConfiguration(configuration,target);
  }
  const previousSchema = settings.parameter_schema;
  const schema = target?.parameter_schema || (target && sameModel && previousSchema?.workflowId === target.workflow_profile_id
    && previousSchema.templateRevision === (target.template_revision || "") ? previousSchema : schemaForTarget(target));
  const next = settingsFromConfiguration(configuration,settings,schema);
  if (target) return next;
  const {parameter_schema:_schema,...withoutSchema} = next;
  return {...withoutSchema,workflow_profile_id:configuration.workflow.id || null};
}

// Keep large seeds as decimal text until Python converts them to exact integers.
export function seedInput(value:string):number|string {
  if(!/^-?\d+$/.test(value))return value;
  const number=Number(value);
  return Number.isSafeInteger(number)?number:value;
}

export function validSeed(value:number|string,allowRandom=true):boolean {
  if(typeof value==="number"&&!Number.isSafeInteger(value))return false;
  if(!/^-?\d{1,19}$/.test(String(value)))return false;
  const seed=BigInt(value);
  return seed>=(allowRandom?-1n:0n)&&seed<=9223372036854775807n;
}
