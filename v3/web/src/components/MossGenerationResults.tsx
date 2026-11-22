import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest} from "../lib/api";
import type {GenerationRunRecord} from "../lib/types";
import {useWorkbenchArtifacts} from "../lib/workbenchHistory";
import {ImagePreview} from "./ImagePreview";
import {MOSS_IMAGE_MODEL} from "../lib/workbenchRoute";

const terminal = new Set(["completed", "failed", "canceled", "remote_missing"]);

export function MossGenerationResults({runId}: {runId?: string}) {
  const [run, setRun] = useState<GenerationRunRecord | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState(-1);
  const [selected, setSelected] = useState(0);
  const [registering,setRegistering]=useState(false);
  useEffect(() => {
    setRun(null);setError("");setPreview(-1);setSelected(0);setRegistering(false);
    if (!runId) return;
    const controller = new AbortController();
    let timer = 0;
    let emptyCompletedReads=0;
    const poll = async () => {
      try {
        const current = await apiRequest<GenerationRunRecord>(`/api/v3/generation-runs/${encodeURIComponent(runId)}`, {signal:controller.signal});
        if (controller.signal.aborted) return;
        const moss=current.source?.model_profile===MOSS_IMAGE_MODEL || (!current.source?.model_profile && current.workflow_profile_id==="v3_moss_image_sft_int8");
        if (current.id !== runId || !moss)
          throw new Error("没有找到匹配的 MOSS 任务。");
        setRun(current);setError("");
        const registering=current.state==="completed" && !current.artifact_count && ++emptyCompletedReads<=3;
        setRegistering(registering);
        if (!terminal.has(current.state) || registering) timer=window.setTimeout(() => void poll(), 1500);
      } catch (caught) {
        if (!controller.signal.aborted) setError((caught as Error).message || "暂时无法读取任务。");
      }
    };
    void poll();
    return () => {controller.abort();window.clearTimeout(timer);};
  }, [runId, attempt]);
  const pictures = useWorkbenchArtifacts(run);
  const previewImages = pictures.items.filter(image => image.content_url);
  const selectedIndex = Math.min(selected, Math.max(0, pictures.items.length-1));
  const picture = pictures.items[selectedIndex];
  useEffect(() => {
    setSelected(index => Math.min(index, Math.max(0, pictures.items.length-1)));
  }, [pictures.items.length]);
  return <section className="moss-results" aria-label="MOSS 生成结果">
    {!runId && <div className="moss-result-empty"><h3>生成结果会显示在这里</h3><p>提交后自动显示任务进度和图片，可点击图片放大查看。</p></div>}
    {runId && !run && !error && <p role="status">正在读取 MOSS 任务…</p>}
    {error && <p role="alert">{error}<button onClick={() => setAttempt(value=>value+1)}>重新读取任务</button></p>}
    {run && <div className="moss-result-status" role="status">
      <span>{run.error?.message || run.status_message || run.state}</span>
      {!terminal.has(run.state) && <progress aria-label="生成进度" max={1} value={Math.max(0,Math.min(1,run.progress||0))}/>}
      {registering && <p>正在登记结果图片…</p>}
      {run.state === "completed" && !run.artifact_count && !registering && <p>本次任务没有记录到输出图片。</p>}
    </div>}
    {pictures.loading && <p role="status">正在读取结果图片…</p>}
    {pictures.error && <p role="alert">{pictures.error}<button onClick={pictures.retry}>重新读取图片</button></p>}
    {picture && <div className="moss-result-images">
      <button key={picture.id} type="button" disabled={!picture.content_url} aria-label={`放大结果图片 ${selectedIndex+1}`}
        onClick={() => setPreview(previewImages.findIndex(item=>item.id===picture.id))}>
        <img src={picture.content_url || picture.thumbnail_url!} alt={`MOSS 生成结果 ${selectedIndex+1}`}/>
      </button></div>}
    {pictures.items.length>1 && <nav className="moss-result-navigation" aria-label="切换结果图片">
      <button type="button" disabled={selectedIndex===0} onClick={() => setSelected(selectedIndex-1)}>上一张</button>
      <span>第 {selectedIndex+1} 张 / 共 {pictures.items.length} 张</span>
      <button type="button" disabled={selectedIndex===pictures.items.length-1} onClick={() => setSelected(selectedIndex+1)}>下一张</button>
    </nav>}
    {runId && <p className="moss-result-links"><Link to="/generate">查看任务详情</Link><Link to="/gallery">前往画廊</Link></p>}
    {preview>=0 && <ImagePreview index={preview} onClose={()=>setPreview(-1)} images={previewImages.map((picture,index)=>({
      src:picture.content_url!,alt:`MOSS 生成结果 ${index+1}`,positive:run?.source?.positive_prompt,
      negative:run?.source?.negative_prompt,parameters:run?.source?.settings,
    }))}/>}
  </section>;
}
