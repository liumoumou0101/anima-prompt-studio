import {useEffect,useState} from "react";
import {apiRequest} from "../lib/api";
import {families,libraryPath,type LibraryListing,type LibraryLora,type LoraFamily} from "../lib/loraLibrary";
import type {ModelProfileOption} from "../lib/types";
import "../components/loraLibrary.css";

function AssetEditor({asset,profiles,onSaved,onClose}:{asset:LibraryLora;profiles:ModelProfileOption[];onSaved:()=>void;onClose:()=>void}){
  const [name,setName]=useState(asset.name),[family,setFamily]=useState(asset.family),[models,setModels]=useState(asset.model_profiles);
  const [words,setWords]=useState(asset.trigger_words.join("\n")),[weight,setWeight]=useState(String(asset.weight)),[clip,setClip]=useState(asset.clip_weight?.toString()||"");
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const options=profiles.filter(p=>(p.family||"anima").toLowerCase()===family);
  return <form onSubmit={async event=>{
    event.preventDefault();if(busy)return;setBusy(true);setError("");
    try{
      await apiRequest(libraryPath+"/"+encodeURIComponent(asset.sha256),{method:"PUT",body:JSON.stringify({name:name.trim(),family,model_profiles:models,
        trigger_words:[...new Set(words.split("\n").map(s=>s.trim()).filter(Boolean))],weight:Number(weight),clip_weight:clip===""?null:Number(clip)})});
      onSaved();
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }}><fieldset disabled={busy}><legend>编辑资料</legend>
    <label>显示名称<input required maxLength={200} value={name} onChange={e=>setName(e.target.value)}/></label>
    <label>模型系列<select value={family} onChange={e=>{setFamily(e.target.value as LoraFamily);setModels([]);}}>{Object.entries(families).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
    {family!=="unknown" && <fieldset><legend>限定底模（可选）</legend>
      <small>未勾选时，所选系列的工作台均可选择此项。这是你声明的适配范围。</small>
      {[...new Set([...options.map(p=>p.id),...models])].map(id=><label className="lora-model-choice" key={id}><input type="checkbox" checked={models.includes(id)} onChange={e=>setModels(prev=>e.target.checked?[...prev,id]:prev.filter(m=>m!==id))}/>{options.find(p=>p.id===id)?.display_name || id}</label>)}
    </fieldset>}
    <div className="lora-fields"><label>默认权重<input type="number" required step="any" min="-2" max="2" value={weight} onChange={e=>setWeight(e.target.value)}/></label>
    {family!=="moss" && <label>默认文本编码器权重<input type="number" step="any" min="-2" max="2" placeholder="跟随权重" value={clip} onChange={e=>setClip(e.target.value)}/></label>}</div>
    <label>触发词（每行一项）<textarea value={words} onChange={e=>setWords(e.target.value)}/></label>
    <div className="lora-actions"><button type="submit" disabled={!name.trim()}>保存资料</button><button type="button" onClick={onClose}>取消</button></div></fieldset>
    {error && <p role="alert">{error}</p>}
  </form>;
}

export function LoraLibraryPage({profiles=[]}:{profiles?:ModelProfileOption[]}){
  const [list,setList]=useState<LibraryListing|null>(null),[revision,setRevision]=useState(0),[family,setFamily]=useState("all"),[query,setQuery]=useState("");
  const [editing,setEditing]=useState<string|null>(null),[busy,setBusy]=useState(""),[error,setError]=useState(""),[notice,setNotice]=useState("");
  useEffect(()=>{
    const controller=new AbortController();setError("");
    void apiRequest<LibraryListing>(libraryPath,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setList(data);}).catch(e=>{if(!controller.signal.aborted)setError((e as Error).message);});
    return ()=>controller.abort();
  },[revision]);
  async function action(kind:"scan"|"open-folder"){
    setBusy(kind);setError("");setNotice("");
    try{
      if(kind==="scan"){
        const scanned=await apiRequest<LibraryListing>(libraryPath+"/scan",{method:"POST",body:"{}"});
        setList(scanned);setNotice("扫描完成。");
      }else{
        const result=await apiRequest<{opened:boolean;root_path:string}>(libraryPath+"/open-folder",{method:"POST",body:"{}"});
        setNotice(result.opened?"已打开收件文件夹。":"请在文件管理器中打开 "+result.root_path);
      }
    }catch(e){setError((e as Error).message);}finally{setBusy("");}
  }
  const entries=list?.items.filter(a=>(family==="all" || a.family===family) && (a.name+" "+a.relative_path).toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="lora-library"><header><h1>LoRA 库</h1>
    <p>把下载好的 .safetensors 文件放入收件文件夹，然后扫描。在工作台启用时，才会准备云端文件。</p>
    {list && <small>收件文件夹 · <code>{list.root_path}</code></small>}
    <div className="lora-actions"><button disabled={!!busy} onClick={()=>void action("open-folder")}>打开收件文件夹</button><button disabled={!!busy || !!editing} onClick={()=>void action("scan")}>{busy==="scan"?"正在扫描…":"扫描文件"}</button></div></header>
    {error && <p role="alert">{error} <button onClick={()=>setRevision(n=>n+1)}>重新读取</button></p>}{notice && <p role="status">{notice}</p>}
    {Boolean(list?.errors?.length) && <div role="alert"><strong>下列文件未能收录</strong><ul>{list?.errors?.map(item=><li key={item.path}>{item.path} · {item.error}</li>)}</ul></div>}
    <div className="lora-filters"><label>搜索资源<input type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label><label>筛选系列<select value={family} onChange={e=>setFamily(e.target.value)}><option value="all">全部系列</option>{Object.entries(families).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><span>{entries?.length??0} 项</span></div>
    {!list&&!error && <p role="status">正在读取本地库…</p>}{list && !entries?.length && <p>{list.items.length?"没有符合筛选条件的资源。":"文件夹尚未收录 LoRA。添加文件后点击「扫描文件」。"}</p>}
    {entries?.map(asset=><article key={asset.id || asset.relative_path}><div><h2>{asset.name}</h2><small>{families[asset.family]} · {asset.present?"本地文件已找到":"本地文件缺失"} · {(asset.size_bytes/1048576).toFixed(1)} MiB</small></div>
      <small>{asset.relative_path}</small>
      {!asset.valid && <p role="alert">{asset.error || "文件无效，请检查文件后重新扫描。"}</p>}
      {asset.valid && !asset.present && <p>仍可在工作台尝试从 Drive 缓存恢复。</p>}
      {editing===asset.id ? <AssetEditor asset={asset} profiles={profiles} onSaved={()=>{setEditing(null);setRevision(n=>n+1);setNotice("资料已保存。");}} onClose={()=>setEditing(null)}/> :
        <><p>默认权重 {asset.weight} · {asset.trigger_words.length ? asset.trigger_words.join("、") : "未提供触发词"}</p>
          {asset.valid && <div><button disabled={!!editing || !!busy} onClick={()=>{setEditing(asset.id);setNotice("");}}>编辑资料</button></div>}</>}
    </article>)}
  </section>;
}
