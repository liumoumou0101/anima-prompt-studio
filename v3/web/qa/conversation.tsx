// Offline visual fixture. No model or generation request leaves this page.
import {createRoot} from "react-dom/client";
import {MemoryRouter} from "react-router-dom";
import {ConversationWorkbenchPage} from "../src/pages/ConversationWorkbenchPage";
import {emptyRequirements} from "../src/lib/conversation";
import {defaultGenerationSettings} from "../src/lib/generationSettings";
import "../src/styles.css";

const requirements = emptyRequirements();
requirements.layers.subject = {text: "雨后的街道，一位短发侦探，右手拿着信。", locked: true};
requirements.layers.style.text = "安静的水彩插画，克制的色彩";
requirements.layers.lighting.text = "傍晚的柔和侧光";
const workspace = {id: "workspace_visualfixture", title: "雨后的来信", revision: 3,
  draft: {mode: "faithful", model_profile: "anima_base_v1", requirements: {...requirements, contract: "anima-requirements/1", revision: 2},
    generation_settings: {...defaultGenerationSettings(), remote_profile_id: "sample", workflow_profile_id: "sample"},
    compile_state: "fresh", compiled: {positive: "short-haired detective, holding a letter in her right hand, rain-washed street, watercolor illustration, subdued colors, soft evening sidelight", negative: "", compiled_token: "cmp_fixture", source: "llm"},
    conversation_events: [{id: "one", delta: "雨后的街道，一位短发侦探，右手拿着信。用安静的水彩风格。", changed_layers: ["subject", "style"], warnings: []},
      {id: "two", delta: "光线改成傍晚的柔和侧光，人物保持不变。", changed_layers: ["lighting"], warnings: ["已保留锁定的主体要求。"]}]}};
sessionStorage.setItem("anima-v3-session", "offline-fixture");
localStorage.setItem("anima-conversation-active", JSON.stringify(workspace.id));
window.fetch = async (input, init) => {
  const path = String(input);
  let data: unknown;
  if (init?.method && init.method !== "GET") return new Response(JSON.stringify({error: {code: "fixture_read_only", message: "这是离线布局样例，请在正式工作台操作。"}}), {status: 422});
  if (path.includes("/workbench/availability")) data = {availability: "ready"};
  else if (path.includes("/reference-examples")) data = {items: [], next_cursor: null, official_pack: {ready: false}};
  else if (path.includes("/generation-targets")) data = {items: [{remote_profile_id: "sample", remote_display_name: "创作服务器", workflow_profile_id: "sample", workflow_display_name: "ANIMA Base", compatible_model_profiles: ["anima_base_v1"]}]};
  else if (path.endsWith(workspace.id)) data = workspace;
  else if (path.includes("/workspaces?")) data = {items: [workspace]};
  else data = {items: []};
  return new Response(JSON.stringify(data), {status: 200});
};
createRoot(document.getElementById("root")!).render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
