// Offline UI fixture. All writes are rejected; no backend or model is contacted.
import {useState} from "react";
import {createRoot} from "react-dom/client";
import {MemoryRouter} from "react-router-dom";
import {ReferenceRequirementsEditor} from "../src/pages/ReferenceRequirementsEditor";
import {LoraMappingPanel} from "../src/pages/LoraMappingPanel";
import {emptyRequirements} from "../src/lib/conversation";
import "../src/styles.css";
import "../src/pages/conversationWorkbench.css";

sessionStorage.setItem("anima-v3-session", "offline-fixture");
window.fetch = async (_,init) => {
  if (init?.method && init.method !== "GET") return new Response(JSON.stringify({error:{code:"fixture_read_only",message:"离线样例不执行写入。"}}),{status:422});
  return new Response(JSON.stringify({mapping_revision:1,workflow_revision:"fixture",remote_fingerprint:"a".repeat(64),current:true,
    capabilities_ready:true,slots:{"9.lora_name":["Anima/watercolor_example.safetensors"]},bindings:[]}));
};
function Fixture() {
  const [value,setValue] = useState(() => {
    const initial = emptyRequirements();
    initial.layers.subject.text = "窗边读信的侦探";
    initial.layers.style.text = "低饱和水彩插画";
    initial.layers.lighting.text = "柔和清晨侧光";
    return initial;
  });
  return <MemoryRouter><main className="conversation-workbench"><h1>参考要求与资源映射</h1><p>离线布局样例，未连接云主机。</p>
    <div className="conversation-layout"><section className="conversation-inspector"><ReferenceRequirementsEditor value={value} onChange={setValue} /></section>
      <section className="conversation-inspector"><LoraMappingPanel remote="fixture" workflow="fixture" disabled={false} onSaved={() => {}}
        resources={[{logical_id:"watercolor_style",file_name:"watercolor_example.safetensors",resource_digest:"b".repeat(64)}]} /></section></div>
  </main></MemoryRouter>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
