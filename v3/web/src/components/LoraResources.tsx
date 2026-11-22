import {useEffect,useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest} from "../lib/api";
import {libraryPath,libraryRequirement,type LibraryListing,type LibraryLora,type LoraFamily,type LoraPreparation} from "../lib/loraLibrary";
import type {GenerationTarget,RequirementLora} from "../lib/types";
import "./loraLibrary.css";

interface Props {
  items:RequirementLora[]; onChange:(items:RequirementLora[])=>void; model:string; family:LoraFamily;
  preparation:LoraPreparation; target?:GenerationTarget; frozen?:boolean; disabled?:boolean; onEditSnapshot?:()=>void;
}
export function LoraResources({items,onChange,model,family,preparation,target,frozen,disabled,onEditSnapshot}:Props) {
  const [picker,setPicker]=useState(false),[epoch,setEpoch]=useState(0);
  const [assets,setAssets]=useState<LibraryLora[]>([]),[error,setError]=useState(""),[loading,setLoading]=useState(false);
  const [copyNotice,setCopyNotice]=useState("");
  const lookup=picker || items.some(item=>item.sha256);
  useEffect(()=>{
    if(!lookup)return;
    const controller=new AbortController();
    setError("");setLoading(true);
    void apiRequest<LibraryListing>(libraryPath,{signal:controller.signal}).then(list=>{
      if(!controller.signal.aborted)setAssets(list.items);
    }).catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[lookup,epoch]);
  const fixed=target?.lora_extension_supported===false || target?.workflow_origin==="user";
  const ordered=!fixed && !frozen;
  const choices=assets.filter(a=>a.valid && a.family===family && (!a.model_profiles.length || a.model_profiles.includes(model)));
  function edit(index:number,patch:Partial<RequirementLora>){onChange(items.map((item,i)=>i===index?{...item,...patch}:item));}
  function move(index:number,to:number){const next=[...items];next.splice(to,0,next.splice(index,1)[0]);onChange(next);}
  return <section className="lora-resources" aria-label="LoRA 资源">
    {frozen && <div className="lora-snapshot">
      <p>当前使用历史工作流快照，保留当时的资源与顺序。</p>
      <button type="button" disabled={disabled || !onEditSnapshot} onClick={onEditSnapshot}>切换模板并编辑 LoRA</button>
      {!onEditSnapshot && <small>当前模型没有可用的兼容模板。请在工作流中配置后再试。</small>}
    </div>}
    <fieldset className="lora-selection" disabled={disabled || frozen}><legend>已选 LoRA · {items.filter(r=>r.enabled!==false).length} 项启用</legend>
      {fixed && <p>此工作流使用固定插槽。实际加载顺序：{target?.lora_slot_order?.join(" → ") || "未声明可用插槽"}。</p>}
      {items.map((item,i)=>{
        const asset=assets.find(a=>a.sha256===item.sha256);
        const title=asset?.name || (item.sha256 ? "LoRA "+item.sha256.slice(0,10) : item.file_name || item.logical_id);
        const result=preparation.results?.find(r=>r.sha256===item.sha256);
        return <div className="lora-selected" key={item.sha256 || i}>
          <div className="lora-card-heading">
            <label className="lora-enabled"><input aria-label={"启用 "+title} type="checkbox" checked={item.enabled!==false} onChange={e=>edit(i,{enabled:e.target.checked})}/><span>{i+1}. {title}</span></label>
            <div className="lora-card-actions">
              {ordered && <><button type="button" title="上移" aria-label={"上移 "+title} disabled={!i} onClick={()=>move(i,i-1)}>↑</button>
                <button type="button" title="下移" aria-label={"下移 "+title} disabled={i===items.length-1} onClick={()=>move(i,i+1)}>↓</button></>}
              <button type="button" title="移除" aria-label={"移除 "+title} onClick={()=>onChange(items.filter((_,n)=>n!==i))}>移除</button>
            </div>
          </div>
          <label className="lora-weight">权重<input type="number" min={-2} max={2} step="0.05" value={item.weight} onChange={e=>edit(i,{weight:Number(e.target.value)})}/></label>
          <details className="lora-advanced"><summary>高级设置</summary>
            {family!=="moss" && target?.lora_loader!=="LoraLoaderModelOnly" && <label>文本编码器权重<input type="number" min={-2} max={2} step="0.05" placeholder="跟随权重" value={item.clip_weight??""} onChange={e=>edit(i,{clip_weight:e.target.value===""?null:Number(e.target.value)})}/></label>}
            {!item.sha256 && <><label>资源 ID<input value={item.logical_id} onChange={e=>edit(i,{logical_id:e.target.value})}/></label><label>文件名<input value={item.file_name} onChange={e=>edit(i,{file_name:e.target.value})}/></label></>}
            <label>触发词（每行一项）<textarea value={item.trigger_words.join("\n")} onChange={e=>edit(i,{trigger_words:e.target.value.split("\n")})}/></label></details>
          {preparation.state==="ready" && result?.installed && item.enabled!==false && <small className="lora-installed">{result.cached?"Drive 已保存 · ":""}当前环境可用{result.restored?" · 已从 Drive 恢复":""}</small>}
        </div>;
      })}
      <div className="lora-actions"><button type="button" aria-expanded={picker} disabled={items.length>=16} onClick={()=>setPicker(open=>!open)}>从库中选择</button>
        {disabled?<span aria-disabled="true">管理 LoRA 库</span>:<Link to="/loras">管理 LoRA 库</Link>}</div>
      {picker && <div className="lora-choices"><strong>适用于当前模型的 LoRA</strong>
        {loading && <p role="status">正在读取资料…</p>}
        {!loading && !error && !choices.length && <p>还没有匹配的资源。请先在库中扫描文件并确认模型分类。</p>}
        {choices.map(asset=><button key={asset.sha256} type="button" aria-label={"添加 "+asset.name} disabled={items.length>=16 || items.some(r=>r.sha256===asset.sha256)} onClick={()=>onChange([...items,libraryRequirement(asset)])}>{asset.name} · {asset.weight}{!asset.present?" · 本地缺失，检查云端缓存":""}</button>)}
        <button type="button" disabled={loading} onClick={()=>setEpoch(n=>n+1)}>刷新列表</button></div>}
      {error && <p role="alert">{error}</p>}
      <details><summary>手动填写已有服务器文件</summary><button type="button" disabled={items.length>=16} onClick={()=>onChange([...items,{logical_id:"lora-"+crypto.randomUUID().slice(0,8),file_name:"",weight:1,trigger_words:[],required:true,source:{kind:"user"}}])}>添加手动 LoRA</button></details>
    </fieldset>
    {items.some(r=>r.enabled!==false && r.trigger_words.some(w=>w.trim())) && <div className="lora-actions"><button type="button" disabled={disabled} onClick={async()=>{
      const words=[...new Set(items.filter(r=>r.enabled!==false).flatMap(r=>r.trigger_words).map(w=>w.trim()).filter(Boolean))];
      try{await navigator.clipboard.writeText(words.join(", "));setCopyNotice("已复制启用项的触发词。");}
      catch{setCopyNotice("请手动复制："+words.join(", "));}
    }}>复制已启用的触发词</button><small>{family==="moss"?"原文直出时，请将需要的触发词粘贴到正文。":"更新提示词会参考启用项的触发词。直出时可复制到正文。"}</small></div>}
    {copyNotice && <small role="status">{copyNotice}</small>}
    {preparation.message && <div className="lora-preparation" role={preparation.state==="failed"?"alert":"status"}>{preparation.message}
      {preparation.state==="preparing" && <progress aria-label="LoRA 准备进度" {...(preparation.progress!=null?{value:preparation.progress,max:1}:{})}/>}
      {["failed","ready"].includes(preparation.state) && <button type="button" disabled={disabled} onClick={preparation.retry}>{preparation.state==="failed"?"重试准备":"重新检查环境"}</button>}</div>}
  </section>;
}
