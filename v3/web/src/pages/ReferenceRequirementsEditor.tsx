import {emptyRequirements, layerLabels} from "../lib/conversation";
import type {LayerName, RequirementsEdit} from "../lib/conversation";

export function ReferenceRequirementsEditor({value, onChange}: {value: RequirementsEdit | null; onChange: (value: RequirementsEdit) => void}) {
  const requirements = value || emptyRequirements();
  function layer(name: LayerName, patch: Record<string, unknown>) {
    onChange({...requirements, layers: {...requirements.layers, [name]: {...requirements.layers[name], ...patch}}});
  }
  return <details><summary>编辑参考要求与 LoRA</summary>
    {(Object.keys(layerLabels) as LayerName[]).map(name => <section key={name} className="conversation-layer">
      <strong>{layerLabels[name]}</strong>
      <label><input type="checkbox" checked={requirements.layers[name].locked} onChange={event => layer(name, {locked: event.target.checked})} />分析时保留此层</label>
      {name !== "exclusions" ? <label>{layerLabels[name]}内容<textarea value={requirements.layers[name].text} maxLength={10000} onChange={event => layer(name, {text: event.target.value})} /></label>
        : <><label>全局排除（每行一项）<textarea value={requirements.layers.exclusions.global.join("\n")} onChange={event => layer(name, {global: event.target.value.split("\n")})} /></label>
          {requirements.layers.exclusions.scoped.map((item, index) => <div key={index} className="conversation-actions">
            <label>排除对象<input value={item.target} maxLength={200} onChange={event => layer(name, {scoped: requirements.layers.exclusions.scoped.map((entry,i) => i === index ? {...entry,target: event.target.value} : entry)})} /></label>
            <label>排除概念<input value={item.concept} maxLength={200} onChange={event => layer(name, {scoped: requirements.layers.exclusions.scoped.map((entry,i) => i === index ? {...entry,concept: event.target.value} : entry)})} /></label>
            <button onClick={() => layer(name, {scoped: requirements.layers.exclusions.scoped.filter((_,i) => i !== index)})}>移除此排除</button></div>)}
          <button disabled={requirements.layers.exclusions.scoped.length >= 100} onClick={() => layer(name, {scoped: [...requirements.layers.exclusions.scoped,{target:"",concept:""}]})}>添加局部排除</button></>}
      {name === "style" && <><label>媒介<input value={requirements.layers.style.medium} maxLength={200} onChange={event => layer(name,{medium:event.target.value})} /></label>
        <label>已确认画师（每行一位，不含 @）<textarea value={requirements.layers.style.artists.join("\n")} onChange={event => layer(name,{artists:event.target.value.split("\n")})} /></label></>}
      {name === "composition" && <label>景别<input value={requirements.layers.composition.shot} maxLength={200} onChange={event => layer(name,{shot:event.target.value})} /></label>}
      {(name === "lighting" || name === "composition") && <label><input type="checkbox" checked={requirements.layers[name].include_with_style_pin} onChange={event => layer(name, {include_with_style_pin:event.target.checked})} />钉选风格时也复制此层</label>}
    </section>)}
    <h4>参考 LoRA</h4>
    {requirements.loras.map((item,index) => <section className="conversation-layer" key={index}>
      {(["logical_id","file_name"] as const).map(field => <label key={field}>{field === "logical_id" ? "资源标识" : "文件名"}<input value={item[field]} maxLength={field === "logical_id" ? 200 : 1000} onChange={event => onChange({...requirements,loras:requirements.loras.map((entry,i) => i === index ? {...entry,[field]:event.target.value} : entry)})} /></label>)}
      <label>权重<input type="number" min={-2} max={2} step={0.05} value={item.weight} onChange={event => onChange({...requirements,loras:requirements.loras.map((entry,i) => i === index ? {...entry,weight:Number(event.target.value)} : entry)})} /></label>
      <label>触发词（每行一项）<textarea value={item.trigger_words.join("\n")} onChange={event => onChange({...requirements,loras:requirements.loras.map((entry,i) => i === index ? {...entry,trigger_words:event.target.value.split("\n")} : entry)})} /></label>
      <label><input type="checkbox" checked={item.required} onChange={event => onChange({...requirements,loras:requirements.loras.map((entry,i) => i === index ? {...entry,required:event.target.checked} : entry)})} />钉选时带入此 LoRA</label>
      <button onClick={() => onChange({...requirements,loras:requirements.loras.filter((_,i) => i !== index)})}>移除此 LoRA</button>
    </section>)}
    <button disabled={requirements.loras.length >= 16} onClick={() => onChange({...requirements,loras:[...requirements.loras,{
      logical_id:`lora_${crypto.randomUUID().slice(0,8)}`,file_name:"",weight:1,trigger_words:[],required:true,source:{kind:"user"}}]})}>添加参考 LoRA</button>
  </details>;
}
