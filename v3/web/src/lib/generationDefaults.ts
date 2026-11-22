import type {WorkbenchGenerationSettings} from "./types";

export const CORE_PARAMETER_KEYS = ["width", "height", "steps", "cfg", "sampler", "scheduler", "seed", "batch_size"] as const;

const ASPECT_SIZES: Record<WorkbenchGenerationSettings["aspect"], {width:number;height:number}|null> = {
  portrait:{width:896,height:1152}, landscape:{width:1152,height:896}, square:{width:1024,height:1024},
  custom:null, model_default:null,
};

export function defaultGenerationSettings():WorkbenchGenerationSettings {
  return {preset_id:"stable_baseline",aspect:"portrait",width:896,height:1152,steps:35,cfg:4.5,
    sampler:"euler",scheduler:"normal",seed:-1,batch_size:1,remote_profile_id:null,workflow_profile_id:null};
}

export function isDefaultGenerationSettings(settings:WorkbenchGenerationSettings):boolean {
  const defaults=defaultGenerationSettings();
  return Object.keys(settings).length===Object.keys(defaults).length && Object.keys(defaults).every(key=>
    settings[key as keyof WorkbenchGenerationSettings]===defaults[key as keyof WorkbenchGenerationSettings]);
}

// Compatibility reader for records created before CreationConfiguration existed.
// Modern records must be resolved from their configuration, never these cached fields.
export function legacyGenerationValues(settings:WorkbenchGenerationSettings) {
  const size=settings.aspect==="custom"?{width:settings.width,height:settings.height}:ASPECT_SIZES[settings.aspect];
  return {preset_id:settings.preset_id,...size,steps:settings.steps,cfg:settings.cfg,sampler:settings.sampler,
    scheduler:settings.scheduler,seed:settings.seed,batch_size:settings.batch_size};
}
