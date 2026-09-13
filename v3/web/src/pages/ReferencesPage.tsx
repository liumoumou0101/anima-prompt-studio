import {useNavigate, useSearchParams} from "react-router-dom";
import {apiRequest} from "../lib/api";
import {ReferenceLibrary, type Example, type Role} from "./ReferenceLibrary";
import type {ConversationRecord} from "../lib/conversation";
import "./libraryPages.css";

export function ReferencesPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  async function start(example: Example, mode: "requirements" | "generation" | "prompt", role: Role) {
    const record = await apiRequest<ConversationRecord>(`/api/v3/reference-examples/${example.id}/workspace`, {
      method: "POST", body: JSON.stringify({source_version: example.source_version, mode, role})});
    navigate(`/workbench?workspace=${encodeURIComponent(record.id)}`);
  }
  return <section className="page library-page references-page"><header className="library-page-heading"><h1>参考案例库</h1>
    <p>从真实图片中借用提示词、画面要求或原始生成条件。</p></header>
    <ReferenceLibrary standalone exampleId={params.get("example") || undefined} onStart={start} />
  </section>;
}
