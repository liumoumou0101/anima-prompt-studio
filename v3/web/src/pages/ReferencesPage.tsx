import {useNavigate, useSearchParams} from "react-router-dom";
import {apiRequest} from "../lib/api";
import {ReferenceLibrary, type Example, type Role} from "./ReferenceLibrary";
import type {ConversationRecord} from "../lib/conversation";
import "./conversationWorkbench.css";

export function ReferencesPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  async function start(example: Example, mode: "requirements" | "generation", role: Role) {
    const record = await apiRequest<ConversationRecord>(`/api/v3/reference-examples/${example.id}/workspace`, {
      method: "POST", body: JSON.stringify({source_version: example.source_version, mode, role})});
    navigate(`/workbench?workspace=${encodeURIComponent(record.id)}`);
  }
  return <section className="references-page"><header><p className="eyebrow">REFERENCE LIBRARY</p><h1>参考案例库</h1>
    <p>积累参考图片、提示词、生成参数与笔记，选择合适的内容开始下一次创作。</p></header>
    <ReferenceLibrary standalone exampleId={params.get("example") || undefined} onStart={start} />
  </section>;
}
