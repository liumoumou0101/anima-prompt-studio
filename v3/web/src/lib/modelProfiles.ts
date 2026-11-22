import type {ModelProfileOption, GenerationTarget, WorkbenchGenerationSettings} from "./types";

export const LEGACY_AESTHETIC = "anima_aesthetic_v1";
export const MOSS_IMAGE_MODEL = "moss_image_sft_int8";

export const BUILT_IN_MODEL_PROFILES: ModelProfileOption[] = [
  {id: "anima_base_v1", display_name: "ANIMA Base", variant: "base"},
  {id: "anima_aesthetic_v1_0", display_name: "ANIMA Aesthetic v1.0", variant: "aesthetic"},
  {id: "anima_aesthetic_v1_1", display_name: "ANIMA Aesthetic v1.1", variant: "aesthetic"},
  {id: "anima_turbo_v1", display_name: "ANIMA Turbo", variant: "turbo"},
  {id: "anima_turbo_v1_1", display_name: "ANIMA Turbo v1.1", variant: "turbo"},
  {id: "animayume_v1_0_final", display_name: "AnimaYume v1.0 Final", variant: "community"},
  {id: "anima_2_9b_preview_v1", display_name: "Anima 2.9B Preview v1", variant: "community"},
  {id: "animayume_v1_5_base", display_name: "AnimaYume v1.5 Base", variant: "community"},
  {id: "miaomiao_harem_anima_v1_6", display_name: "MiaoMiao Harem ANIMA v1.6", variant: "community"},
  {id: "wai_anima_v1_0", display_name: "WAI-ANIMA 1.0", variant: "community"},
];

export function isAnimaModel(model: string, profiles?: ModelProfileOption[]): boolean {
  if (!model || model===MOSS_IMAGE_MODEL) return false;
  const family=profiles?.find(item=>item.id===model)?.family;
  return family ? family==="anima" : model===LEGACY_AESTHETIC || BUILT_IN_MODEL_PROFILES.some(item=>item.id===model);
}

export function modelProfileChoices(modelProfiles?: ModelProfileOption[]) {
  const source = modelProfiles?.length ? modelProfiles : BUILT_IN_MODEL_PROFILES;
  const expanded = source.flatMap(item => item.id === LEGACY_AESTHETIC ? BUILT_IN_MODEL_PROFILES.filter(p => p.variant === "aesthetic") : [item]);
  return expanded.filter(item => isAnimaModel(item.id,expanded)).filter((item, index, items) => items.findIndex(p => p.id === item.id) === index)
    .map((item) => ({id: item.id, label: item.display_name}));
}

export function resolveLegacyAesthetic(model: string, settings: WorkbenchGenerationSettings, targets: GenerationTarget[]) {
  if (model !== LEGACY_AESTHETIC) return;
  const workflow = settings.creation_configuration?.workflow.id ?? settings.workflow_profile_id;
  const target = targets.find(item => item.remote_profile_id === settings.remote_profile_id && item.workflow_profile_id === workflow);
  if (!target) return;
  const versions = target.compatible_model_profiles.filter(id => ["anima_aesthetic_v1_0", "anima_aesthetic_v1_1"].includes(id));
  if (versions.length === 1) return {model: versions[0], target};
}
