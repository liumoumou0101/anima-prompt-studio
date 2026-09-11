import type {ModelProfileOption, GenerationTarget, WorkbenchGenerationSettings} from "./types";

export const LEGACY_AESTHETIC = "anima_aesthetic_v1";

export const BUILT_IN_MODEL_PROFILES: ModelProfileOption[] = [
  {id: "anima_base_v1", display_name: "ANIMA Base", variant: "base"},
  {id: "anima_aesthetic_v1_0", display_name: "ANIMA Aesthetic v1.0", variant: "aesthetic"},
  {id: "anima_aesthetic_v1_1", display_name: "ANIMA Aesthetic v1.1", variant: "aesthetic"},
  {id: "anima_turbo_v1", display_name: "ANIMA Turbo", variant: "turbo"},
  {id: "anima_turbo_v1_1", display_name: "ANIMA Turbo v1.1", variant: "turbo"},
  {id: "animayume_v1_0_final", display_name: "AnimaYume v1.0 Final", variant: "community"},
  {id: "miaomiao_harem_anima_v1_6", display_name: "MiaoMiao Harem ANIMA v1.6", variant: "community"},
];

export function modelProfileChoices(modelProfiles?: ModelProfileOption[]) {
  const source = modelProfiles?.length ? modelProfiles : BUILT_IN_MODEL_PROFILES;
  const expanded = source.flatMap(item => item.id === LEGACY_AESTHETIC ? BUILT_IN_MODEL_PROFILES.filter(p => p.variant === "aesthetic") : [item]);
  return expanded.filter((item, index) => expanded.findIndex(p => p.id === item.id) === index)
    .map((item) => ({id: item.id, label: item.display_name}));
}

export function resolveLegacyAesthetic(model: string, settings: WorkbenchGenerationSettings, targets: GenerationTarget[]): string {
  if (model !== LEGACY_AESTHETIC) return model;
  const target = targets.find(item => item.remote_profile_id === settings.remote_profile_id && item.workflow_profile_id === settings.workflow_profile_id);
  const versions = target?.compatible_model_profiles.filter(id => ["anima_aesthetic_v1_0", "anima_aesthetic_v1_1"].includes(id)) || [];
  return versions.length === 1 ? versions[0] : model;
}
