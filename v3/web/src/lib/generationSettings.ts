import type {GenerationRecipe, GenerationTarget, WorkbenchGenerationSettings} from "./types";

export const ASPECT_SIZES: Record<WorkbenchGenerationSettings["aspect"], {width: number; height: number} | null> = {
  portrait: {width: 896, height: 1152},
  landscape: {width: 1152, height: 896},
  square: {width: 1024, height: 1024},
  custom: null,
  model_default: null,
};

export function defaultGenerationSettings(): WorkbenchGenerationSettings {
  return {
    preset_id: "stable_baseline",
    aspect: "portrait",
    width: 896,
    height: 1152,
    steps: 30,
    cfg: 4,
    sampler: "er_sde",
    scheduler: "simple",
    seed: -1,
    batch_size: 1,
    remote_profile_id: null,
    workflow_profile_id: null,
  };
}

export function findGenerationRecipe(target: GenerationTarget | undefined, recipeId: string): GenerationRecipe | undefined {
  return target?.generation_recipes?.find((item) => item.id === recipeId);
}

export function applyGenerationRecipe(
  settings: WorkbenchGenerationSettings,
  target: GenerationTarget,
  recipeId = target.default_recipe_id || target.generation_recipes?.[0]?.id || "custom",
): WorkbenchGenerationSettings {
  const recipe = findGenerationRecipe(target, recipeId) || target.generation_recipes?.[0];
  return {
    ...settings,
    preset_id: recipe?.id || "custom",
    remote_profile_id: target.remote_profile_id,
    workflow_profile_id: target.workflow_profile_id,
    ...(recipe?.parameters || {}),
  };
}

export function markGenerationCustom(
  settings: WorkbenchGenerationSettings,
  patch: Partial<WorkbenchGenerationSettings>,
): WorkbenchGenerationSettings {
  return {...settings, ...patch, preset_id: "custom"};
}

export function applyAspect(
  settings: WorkbenchGenerationSettings,
  aspect: WorkbenchGenerationSettings["aspect"],
): WorkbenchGenerationSettings {
  const size = ASPECT_SIZES[aspect];
  return {...settings, aspect, ...(size || {})};
}

export function resolvedGenerationSettings(
  settings: WorkbenchGenerationSettings,
  overrides: {seed?: number; batch_size?: number} = {},
) {
  const size = settings.aspect === "model_default"
    ? null
    : settings.aspect === "custom"
      ? {width: settings.width, height: settings.height}
      : ASPECT_SIZES[settings.aspect];
  return {
    preset_id: settings.preset_id,
    ...(size || {}),
    steps: settings.steps,
    cfg: settings.cfg,
    sampler: settings.sampler,
    scheduler: settings.scheduler,
    seed: overrides.seed ?? settings.seed,
    batch_size: overrides.batch_size ?? settings.batch_size,
  };
}
