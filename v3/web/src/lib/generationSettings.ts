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
    steps: 35,
    cfg: 4.5,
    sampler: "euler",
    scheduler: "normal",
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
  recipeId?: string,
): WorkbenchGenerationSettings {
  if (recipeId === undefined && (settings.preset_id === "custom" || (!!settings.workflow_profile_id && !findGenerationRecipe(target, settings.preset_id)))) {
    return {...settings, preset_id: "custom", remote_profile_id: target.remote_profile_id, workflow_profile_id: target.workflow_profile_id};
  }
  const recipe = findGenerationRecipe(target, recipeId ?? target.default_recipe_id ?? "") || target.generation_recipes?.[0];
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
  overrides: {seed?: number | string; batch_size?: number} = {},
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

// Keep large seeds as decimal text until Python converts them to exact integers.
export function seedInput(value: string): number | string {
  if (!/^-?\d+$/.test(value)) return value;
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : value;
}

// A model change starts a new sampling recipe. Target refreshes within the same
// model still use applyGenerationRecipe to retain saved/manual parameters.
export function changeGenerationModel(
  settings: WorkbenchGenerationSettings,
  target?: GenerationTarget,
): WorkbenchGenerationSettings {
  const next = {...settings, preset_id: "stable_baseline", workflow_profile_id: null};
  return target ? applyGenerationRecipe(next, target, target.default_recipe_id) : next;
}

export function validSeed(value: number | string, allowRandom = true): boolean {
  if (typeof value === "number" && !Number.isSafeInteger(value)) return false;
  if (!/^-?\d{1,19}$/.test(String(value))) return false;
  const seed = BigInt(value);
  return seed >= (allowRandom ? -1n : 0n) && seed <= 9223372036854775807n;
}
