import type {RequirementsEdit} from "./conversation";

export type SceneField = "shot" | "layout" | "camera" | "gaze" | "mood";
export interface SceneChoice {value: string; source: "user" | "extracted" | "suggestion"; target?: string; evidence?: string}
export type SceneDesign = Partial<Record<Exclude<SceneField, "mood">, SceneChoice | null>>;
export type SceneChoices = Partial<Record<SceneField, SceneChoice | null>>;
export const sceneFields: SceneField[] = ["shot", "layout", "camera", "gaze", "mood"];
export const sceneLabels: Record<SceneField, string> = {shot: "景别", layout: "构图布局", camera: "相机机位", gaze: "人物视线", mood: "氛围"};
export const sceneOptions: Record<SceneField, string[]> = {
  shot: ["面部特写", "胸像", "半身", "全身", "远景"],
  layout: ["居中构图", "三分法", "对称布局", "对角线布局", "保留明显留白"],
  camera: ["平视", "俯视", "仰视", "从人物侧面观察", "从人物背后观察"],
  gaze: ["看向镜头", "看向远方", "注视画面中的某个物体", "闭眼"],
  mood: ["温暖治愈", "宁静日常", "清冷疏离", "紧张悬疑", "轻快明亮"],
};
export const sceneSourceLabels = {user: "已指定", extracted: "原文提取 · 已确认", suggestion: "建议 · 已采用"};
export function sceneChoice(requirements: RequirementsEdit, field: SceneField): SceneChoice | null {
  return (field === "mood" ? requirements.layers.lighting.mood : requirements.layers.composition.design?.[field]) || null;
}
export function sceneLocked(requirements: RequirementsEdit, field: SceneField): boolean {
  return field === "mood" ? requirements.layers.lighting.locked : requirements.layers.composition.locked;
}
export function applySceneChoices(requirements: RequirementsEdit, changes: SceneChoices): RequirementsEdit {
  const next = structuredClone(requirements);
  for (const field of sceneFields) {
    if (!(field in changes)) continue;
    const choice = changes[field];
    if (field === "mood") {
      if (choice) next.layers.lighting.mood = structuredClone(choice);
      else delete next.layers.lighting.mood;
    } else {
      const design = {...next.layers.composition.design};
      if (choice) design[field] = structuredClone(choice);
      else delete design[field];
      if (Object.keys(design).length) next.layers.composition.design = design;
      else delete next.layers.composition.design;
    }
  }
  return next;
}
const sameChoice = (a: SceneChoice | null, b: SceneChoice | null) =>
  a?.value === b?.value && a?.source === b?.source && (a?.target || "") === (b?.target || "") && (a?.evidence || "") === (b?.evidence || "");
export function undoSceneChoices(current: RequirementsEdit, before: RequirementsEdit, after: RequirementsEdit): RequirementsEdit {
  const changes: SceneChoices = {};
  for (const field of sceneFields) {
    if (!sameChoice(sceneChoice(before, field), sceneChoice(after, field)) && sameChoice(sceneChoice(current, field), sceneChoice(after, field))) {
      changes[field] = sceneChoice(before, field);
    }
  }
  const next = applySceneChoices(current, changes);
  // The freeform shot and its replacement control are one edit. Restoring only
  // the prose after a later control change would introduce a new contradiction.
  if (before.layers.composition.shot !== after.layers.composition.shot
    && current.layers.composition.shot === after.layers.composition.shot
    && sameChoice(sceneChoice(current, "shot"), sceneChoice(after, "shot"))) {
    next.layers.composition.shot = before.layers.composition.shot;
  }
  return next;
}

interface AdviceChoice {value: string; target?: string}
export interface SceneAdvice {
  suggestions: {title: string; reason: string; choices: Partial<Record<SceneField, AdviceChoice>>}[];
  extracted: (AdviceChoice & {field: SceneField; evidence: string})[];
}
export function parseSceneAdvice(raw: unknown): SceneAdvice {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("画面建议格式有误，请重试。");
  const data = raw as Record<string, unknown>;
  if (!Array.isArray(data.suggestions) || data.suggestions.length > 3 || !Array.isArray(data.extracted) || data.extracted.length > 5) throw new Error("画面建议格式有误，请重试。");
  const text = (value: unknown, max: number) => typeof value === "string" && value.trim().length > 0 && value.length <= max;
  const validChoice = (value: unknown, field: string) => {
    if (!value || typeof value !== "object" || Array.isArray(value) || !sceneFields.includes(field as SceneField)) return false;
    const choice = value as AdviceChoice;
    return text(choice.value, 400) && (choice.target == null || (typeof choice.target === "string" && choice.target.length <= 200)) && (field !== "gaze" || text(choice.target, 200));
  };
  for (const value of data.suggestions) {
    if (!value || typeof value !== "object" || !text(value.title, 100) || !text(value.reason, 600) || !value.choices || typeof value.choices !== "object") throw new Error("画面建议格式有误，请重试。");
    const entries = Object.entries(value.choices);
    if (!entries.length || entries.length > 5 || entries.some(([field, choice]) => !validChoice(choice, field))) throw new Error("画面建议格式有误，请重试。");
  }
  for (const value of data.extracted) if (!value || !validChoice(value, value.field) || !text(value.evidence, 1000)) throw new Error("原文提取格式有误，请重试。");
  // Return the contract fields only. Never spread unexpected model properties
  // into the user's requirements, even when a response bypasses server checks.
  const advice = data as unknown as SceneAdvice;
  const choice = (item: AdviceChoice): AdviceChoice => ({value: item.value.trim(), ...(item.target?.trim() ? {target: item.target.trim()} : {})});
  return {
    suggestions: advice.suggestions.map(item => ({title: item.title.trim(), reason: item.reason.trim(),
      choices: Object.fromEntries(Object.entries(item.choices).map(([field, value]) => [field, choice(value)]))})),
    extracted: advice.extracted.map(item => ({...choice(item), field: item.field, evidence: item.evidence})),
  };
}
