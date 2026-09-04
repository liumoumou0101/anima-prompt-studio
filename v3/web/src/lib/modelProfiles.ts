import type {ModelProfileOption} from "./types";

export const BUILT_IN_MODEL_PROFILES: ModelProfileOption[] = [
  {id: "anima_base_v1", display_name: "ANIMA Base", variant: "base"},
  {id: "anima_aesthetic_v1", display_name: "ANIMA Aesthetic", variant: "aesthetic"},
  {id: "anima_turbo_v1", display_name: "ANIMA Turbo", variant: "turbo"},
  {id: "anima_turbo_v1_1", display_name: "ANIMA Turbo v1.1", variant: "turbo"},
  {id: "animayume_v1_0_final", display_name: "AnimaYume v1.0 Final", variant: "community"},
  {id: "miaomiao_harem_anima_v1_6", display_name: "MiaoMiao Harem ANIMA v1.6", variant: "community"},
];

export function modelProfileChoices(modelProfiles?: ModelProfileOption[]) {
  return (modelProfiles?.length ? modelProfiles : BUILT_IN_MODEL_PROFILES)
    .map((item) => ({id: item.id, label: item.display_name}));
}
