import type {ConversationRecord, LocalConversation, RequirementsEdit} from "../lib/conversation";
import {layerLabels} from "../lib/conversation";
import {diffPrompt} from "../lib/promptDiff";
import {useEffect, useRef} from "react";

export interface ConversationProposal {
  id: string; workspace_id: string; base_revision: number; draft: ConversationRecord["draft"];
  changed_layers: string[]; warnings: string[]; created_at: string;
  unchanged?: boolean; message?: string;
}
export function PromptChanges({before, after}: {before: {positive: string; negative: string}; after: {positive: string; negative: string}}) {
  return <div className="conversation-diff">{(["positive", "negative"] as const).map(key =>
    <section key={key}><h4>{key === "positive" ? "正向提示词" : "负向提示词"}{before[key] === after[key] && <span> · 未改变</span>}</h4>
      <p className="conversation-diff-text">{!before[key] && !after[key] ? "未填写" : diffPrompt(before[key], after[key]).map((part, index) =>
        part.kind === "added" ? <ins key={index} aria-label={`新增：${part.text}`}>{part.text}</ins>
          : part.kind === "removed" ? <del key={index} aria-label={`删除：${part.text}`}>{part.text}</del> : <span key={index}>{part.text}</span>)}</p>
    </section>)}</div>;
}
function readable(value: unknown): string {
  if (value == null || value === "") return "未指定";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(readable).join("、") || "未指定";
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${fieldNames[key] || key}：${readable(item)}`).join("；") || "未指定";
  return String(value);
}
const fieldNames: Record<string, string> = {text: "描述", locked: "锁定", medium: "媒介", artists: "画师", shot: "景别", global: "全局排除", scoped: "局部排除", target: "对象", concept: "排除内容", mood: "氛围", design: "画面设计", character_tags: "角色", series_tags: "作品", general_tags: "标签", manual_artist_tags: "指定画师", include_with_style_pin: "随风格借用"};
export function RequirementChanges({before, after}: {before: RequirementsEdit; after: RequirementsEdit | null}) {
  const changes = Object.keys(layerLabels).flatMap(key => {
    const name = key as keyof typeof layerLabels, left = before.layers[name], right = after?.layers[name];
    return Object.keys({...left, ...right}).filter(field => readable(left[field as keyof typeof left]) !== readable(right?.[field as keyof typeof right])).map(field =>
      <li key={`${key}.${field}`}><strong>{layerLabels[name]} · {fieldNames[field] || field}</strong><div><del>{readable(left[field as keyof typeof left])}</del><span aria-hidden="true"> → </span><ins>{readable(right?.[field as keyof typeof right])}</ins></div></li>);
  });
  return changes.length ? <ul className="conversation-requirement-diff">{changes}</ul> : <p className="conversation-muted">中文画面要求未改变。</p>;
}
export function ConversationReview({proposal, before, disabled, acceptBlocked = false, onAccept, onDiscard}: {proposal: ConversationProposal; before: LocalConversation; disabled: boolean; acceptBlocked?: boolean; onAccept: () => void; onDiscard: () => void}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.scrollIntoView?.({block: "start", behavior: "instant"});
    heading.current?.focus({preventScroll: true});
  }, [proposal.id]);
  const after = {positive: proposal.draft.compiled?.positive || "", negative: proposal.draft.compiled?.negative || ""};
  return <section className="conversation-review" aria-label="待确认的修改">
    <header><h2 ref={heading} tabIndex={-1}>待确认的修改</h2><span>尚未替换当前版本</span></header>
    <p>检查新增与删除内容，再决定是否采用。<span className="conversation-diff-legend"><ins>新增</ins> <del>删除</del></span></p>
    <RequirementChanges before={before.requirements} after={proposal.draft.requirements} />
    <PromptChanges before={before} after={after} />
    {proposal.warnings.length > 0 && <div className="conversation-review-notes"><strong>模型说明</strong><ul>{proposal.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></div>}
    {acceptBlocked && <p role="alert">当前草稿或版本已变化，请先不采用这份候选，处理草稿后重新整理。</p>}
    <div className="conversation-actions"><button className="conversation-primary" disabled={disabled || acceptBlocked} onClick={onAccept}>采用修改</button><button disabled={disabled} onClick={onDiscard}>不采用</button></div>
  </section>;
}
