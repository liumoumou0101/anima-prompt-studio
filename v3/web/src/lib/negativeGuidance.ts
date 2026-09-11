// Source: https://huggingface.co/circlestone-labs/Anima (checked 2026-09-11).
// Aesthetic suggestion applies the author's no-score rule to the general list;
// it is a starting point for comparison, not a separately validated recipe.
export function negativeGuidance(model: string): {text: string; note: string; source?: string} {
  const common = "worst quality, low quality, artist name, blurry, jpeg artifacts, chromatic aberration";
  if (model === "anima_base_v1") return {
    text: "worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration",
    note: "Base：作者提供了负向词起点；可按画面需要删改。",
  };
  if (["anima_aesthetic_v1", "anima_aesthetic_v1_0", "anima_aesthetic_v1_1"].includes(model)) return {
    text: common,
    note: "Aesthetic：按作者说明从通用建议中去掉 score_*，供对照试验；不是已经验收的最佳配方。",
  };
  if (model.startsWith("anima_turbo_")) return {
    text: "", note: "Turbo 推荐 CFG 1；常规 CFG 1 采样不使用负向引导。已有负向文本仍保留，实验工作流须另行核验。",
  };
  if (model === "miaomiao_harem_anima_v1_6") return {
    text: "worst quality, low quality, score_1, score_2, score_3, artist name, shiny skin",
    note: "MiaoMiao Anima 1.6：该版本作者列出的负向建议，可按画面需要删改。",
    source: "https://civitai.com/models/934764?modelVersionId=3248362",
  };
  if (model === "animayume_v1_0_final") return {
    text: "", note: "AnimaYume 1.0 Final：作者说明训练未使用质量评分标签，暂未找到该版本明确的负向配方。请按需求手工填写，不自动套用 Base 的 score_*。",
    source: "https://civitai.com/models/2385278?modelVersionId=3065644",
  };
  return {text: "", note: "该模型的作者负向建议尚待核验，可先手工填写需要避免的内容。"};
}

export function appendNegative(current: string, suggested: string): string {
  const existing = new Set(current.split(",").map(word => word.trim().toLowerCase()));
  const additions = suggested.split(",").map(word => word.trim()).filter(word => word && !existing.has(word.toLowerCase()));
  return additions.length ? [current.trim(), ...additions].filter(Boolean).join(", ") : current;
}
