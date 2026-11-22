// Offline UI acceptance fixture. Requests are intercepted locally; no LLM/GPU traffic.
import {createRoot} from 'react-dom/client';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {AppShell} from '../src/components/AppShell';
import {ConversationWorkbenchPage} from '../src/pages/ConversationWorkbenchPage';
import {emptyRequirements} from '../src/lib/conversation';
import {defaultGenerationSettings} from '../src/lib/generationSettings';
import {initializeAppearance} from '../src/lib/appearance';
import '../src/styles.css';
import sampleImage from '../../../anima-ref/images/b04-06-ghibli-meadow.jpg';

const requirements = emptyRequirements();
requirements.layers.subject = {...requirements.layers.subject, text: '女孩站在微风吹拂的草地上，远处有山和白云。', locked: true};
requirements.layers.style.text = '清新的手绘动画风格，克制的色彩';
requirements.layers.lighting.text = '午后的柔和阳光';
const workspace = {id: 'workspace_visualfixture', title: '草地上的微风', revision: 3,
  draft: {mode: 'faithful', model_profile: 'anima_base_v1', requirements: {...requirements, contract: 'anima-requirements/1', revision: 2},
    generation_settings: {...defaultGenerationSettings(), remote_profile_id: 'sample', workflow_profile_id: 'sample'},
    compile_state: 'fresh', compiled: {positive: '1girl, standing in a meadow, gentle breeze, distant mountains, white clouds, hand-drawn animation, soft afternoon sunlight, fresh natural colors', negative: '', compiled_token: 'cmp_fixture', source: 'llm'},
    conversation_events: [{id: 'one', delta: '女孩站在微风吹拂的草地上，远处有山和白云。', changed_layers: ['subject','style'], warnings: []}]}};
const run = {id:'run_visualfixture',state:'completed',status_message:'布局验收样例 · 使用已收集参考图',artifact_count:1,created_at:'2026-09-12T08:30:00Z'};
sessionStorage.setItem('anima-v3-session','offline-fixture');
localStorage.setItem('anima-conversation-active',JSON.stringify(workspace.id));
window.fetch = async (input, init) => {
  const path=String(input); let data: unknown;
  if (init?.method && init.method!=='GET') return new Response(JSON.stringify({error:{code:'fixture_read_only',message:'离线验收样例不发送模型请求；你的本地输入仍保留。'}}),{status:422});
  if(path.includes('/workbench/availability')) data={availability:'ready'};
  else if(path.includes('/reference-examples')) data={items:[],next_cursor:null,official_pack:{ready:false}};
  else if(path.includes('/generation-targets')) data={items:[{remote_profile_id:'sample',remote_display_name:'创作服务器',workflow_profile_id:'sample',workflow_display_name:'ANIMA Base',compatible_model_profiles:['anima_base_v1']}]};
  else if(path.includes('/artifacts')) data={items:[{id:'asset_visualfixture',path:'offline-reference.jpg',thumbnail_url:sampleImage,content_url:sampleImage,removed:false}]};
  else if(path.includes('/runs?')) data={items:[run]};
  else if(path.endsWith(workspace.id)) data=workspace;
  else if(path.includes('/workspaces?')) data={items:[workspace]};
  else if(path.includes('/identities/suggest')) data={items:[],recent:[],favorites:[]};
  else data={items:[]};
  return new Response(JSON.stringify(data),{status:200});
};
initializeAppearance();
createRoot(document.getElementById('root')!).render(<MemoryRouter initialEntries={['/workbench']}><Routes><Route element={<AppShell bootstrap={{app_version:'UI QA',api_version:'3',data_pack:{ready:true,id:'offline',cutoff_mode:'exact'},features:{},model_profiles:[],settings_summary:{}}}/>}><Route path='*' element={<ConversationWorkbenchPage remoteEnabled/>}/></Route></Routes></MemoryRouter>);
