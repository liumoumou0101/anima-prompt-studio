import {useRef, useState} from "react";
import {apiRequest} from "../lib/api";

const dimensions = ["角色辨识", "构图", "结构", "风格"] as const;
type Outcome = "unreviewed" | "pass" | "fail" | "uncertain";
const outcomes: Record<Outcome, string> = {unreviewed: "未评", pass: "符合预期", fail: "不符合预期", uncertain: "不确定"};

export function GenerationAssessment({runId, path}: {runId: string; path: string}) {
  const [scores, setScores] = useState<Record<string, Outcome>>({});
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exampleId, setExampleId] = useState("");
  const lock = useRef(false);
  const hasObservation = tags.trim() || notes.trim() || Object.values(scores).some(score => score !== "unreviewed");

  async function save() {
    if (lock.current || exampleId || !hasObservation) return;
    lock.current = true; setBusy(true); setError("");
    const userNotes = ["人工实测记录（单图观察，不代表模型整体能力）", `测试 tag：${tags.trim() || "未填写"}`,
      ...dimensions.map(dimension => `${dimension}：${outcomes[scores[dimension] || "unreviewed"]}`),
      `备注：${notes.trim() || "无"}`].join("\n");
    try {
      const example = await apiRequest<{id: string}>("/api/v3/reference-examples/from-run", {
        method: "POST", body: JSON.stringify({run_id: runId, path, user_notes: userNotes}),
      });
      setExampleId(example.id);
    } catch (caught) {setError(caught instanceof Error ? caught.message : "保存失败，请重试。");}
    finally {setBusy(false); lock.current = false;}
  }

  return <details className="generation-assessment">
    <summary>记录人工实测（可选）</summary>
    <p className="conversation-muted">只记录这张图片的人工观察。保存时一起归档图片、原始提示词、参数及生成任务来源，不会再次出图或自动评分。</p>
    {exampleId ? <a href={`/references?example=${encodeURIComponent(exampleId)}`}>实测已保存 · 打开参考记录</a> : <>
      <fieldset disabled={busy}>
        <legend>人工观察</legend>
        {dimensions.map(dimension => <label key={dimension}>{dimension}<select value={scores[dimension] || "unreviewed"}
          onChange={event => setScores(previous => ({...previous, [dimension]: event.target.value as Outcome}))}>
          {Object.entries(outcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>)}
        <label>测试 tag（可选）<input value={tags} maxLength={1000} onChange={event => setTags(event.target.value)} placeholder="角色、作品或画师的原始 tag" /></label>
        <label>实测备注<textarea rows={3} maxLength={18000} value={notes} onChange={event => setNotes(event.target.value)} placeholder="具体哪里符合或不符合预期，可记录对照条件" /></label>
      </fieldset>
      <button type="button" disabled={busy || !hasObservation} onClick={() => void save()}>{busy ? "正在保存实测…" : "保存实测到参考库"}</button>
    </>}
    {error && <p role="alert">{error} 记录内容已保留，可重试。</p>}
  </details>;
}
