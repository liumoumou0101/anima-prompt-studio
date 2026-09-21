import {createStudio, edit, updatePrompt, generate, restoreImage, restoreHistory, undo, redo, selectImage} from './state.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const clone = value => structuredClone(value);
let state = createStudio();
let busy = false;
let comparing = false;
let expandedHistory = null;
let lastDifference = {before:state.images[0].snapshot.positive, after:state.current.positive};
let lastMessage = '更新后直接生效，不用再确认采用';
function compactView(view) {
  document.querySelector('.studio').dataset.view = view;
  $('view-images').setAttribute('aria-pressed',String(view === 'images'));
  $('view-prompt').setAttribute('aria-pressed',String(view === 'prompt'));
}
$('view-images').addEventListener('click',()=>compactView('images'));
$('view-prompt').addEventListener('click',()=>compactView('prompt'));
compactView('images');

function message(text, ok = true) {
  lastMessage = text;
  $('action-message').textContent = text;
  $('action-message').style.color = ok ? '#577451' : '#95622c';
}

function selected() { return state.images.find(image => image.id === state.selectedImageId) || state.images.at(-1); }
function matchingText(image) { return image.snapshot.positive === state.current.positive && image.snapshot.negative === state.current.negative; }

function renderButtons() {
  $('undo').disabled = busy || !state.undoStack.length;
  $('redo').disabled = busy || !state.redoStack.length;
  $('undo-label').textContent = state.undoStack.length ? `可撤销：${state.undoStack.at(-1).label}` : '暂无可撤销操作';
  $('update').disabled = busy || !state.current.delta.trim();
  $('combined').disabled = busy || !state.current.delta.trim();
  $('generate').disabled = busy || !$('positive').value.trim();
  ['restore-image','prompt-only','model','workflow','size','more-settings','seed','steps','cfg','reset','delta'].forEach(id => $(id).disabled = busy);
  $('positive').readOnly = busy;
  $('negative').readOnly = busy;
  document.querySelectorAll('[data-suggestion]').forEach(button => button.disabled = busy);
  $('pending-note').textContent = state.current.delta.trim() ? '修改意见尚未应用 · 可直接用当前提示词生图' : '写下修改意见，再更新提示词';
  $('pending-note').style.color = state.current.delta.trim() ? '#956b32' : '';
  $('busy-overlay').hidden = !busy;
}

function renderImages() {
  const image = selected();
  $('main-image').src = image.src;
  $('main-image').alt = `当前查看：${image.title}，交互演示样例图`;
  $('image-title').textContent = image.title;
  const index = state.images.indexOf(image);
  const previous = state.images[index > 0 ? index - 1 : Math.min(1,state.images.length - 1)];
  $('comparison-figure').hidden = !comparing;
  $('comparison-image').src = previous.src;
  $('comparison-image').alt = `对比图片：${previous.title}`;
  $('comparison-caption').textContent = previous.title;
  $('compare').setAttribute('aria-pressed', String(comparing));
  $('compare').textContent = comparing ? '结束对比' : '对比另一张';
  $('image-match').textContent = matchingText(image) ? '图片记录的提示词与当前一致' : '这张图使用旧提示词 · 当前文字已修改';
  $('image-match').style.color = matchingText(image) ? '' : '#956b32';
  $('image-count').textContent = `${state.images.length} 张`;
  $('filmstrip').innerHTML = state.images.map((item,index) => `<button data-image="${esc(item.id)}" aria-label="查看图片 ${index+1}：${esc(item.title)}" aria-pressed="${item.id===image.id}"><img src="${esc(item.src)}" alt="${esc(item.title)}"><span>${index+1}</span></button>`).join('');
}

function renderHistory() {
  $('history-count').textContent = state.history.length;
  const kinds = {generate:'图片',update:'改词',restore:'恢复',manual:'编辑',settings:'设置',draft:'草稿'};
  $('history-list').innerHTML = [...state.history].reverse().map(item => {
    const image = state.images.find(value => value.id === item.imageId);
    const draftNote = item.kind === 'draft' && item.snapshot.delta ? `<p>未发送意见：${esc(item.snapshot.delta)}</p>` : '';
    return `<article class="history-item">${image ? `<img src="${esc(image.src)}" alt="${esc(image.title)}">` : `<div class="history-marker">${kinds[item.kind]||'编辑'}</div>`}<div><h3>${esc(item.title)}</h3>${draftNote}<p>${esc(item.time)} · ${image?'已有样例':'未绑定新图'}<br>${esc(item.snapshot.model)} · ${item.snapshot.width} × ${item.snapshot.height}</p><button class="button" data-restore-history="${esc(item.id)}" ${busy?'disabled':''}>恢复到这里</button><button class="text-button" data-view-history="${esc(item.id)}">${expandedHistory===item.id?'收起详情':'查看内容'}</button></div>${expandedHistory===item.id?`<div class="history-preview"><p>${esc(item.snapshot.positive)}</p><p>工作流：${esc(item.snapshot.workflow)} · 种子 ${esc(item.snapshot.seed)}</p></div>`:''}</article>`;
  }).join('');
}

function render() {
  const current = state.current;
  ['positive','negative','delta','model','workflow','seed','steps','cfg'].forEach(id => { if ($(id).value !== String(current[id])) $(id).value = current[id]; });
  $('size').value = `${current.width}x${current.height}`;
  $('draft-status').textContent = current.positive.trim() ? '可直接生成' : '请填写提示词';
  const source = state.images.find(image => image.id === current.sourceId);
  $('source-line').hidden = !source;
  if (source) { $('source-thumb').src = source.src; $('source-title').textContent = source.title; }
  $('latest-change').textContent = state.history.at(-1)?.title || '从当前提示词开始';
  $('prompt-diff').innerHTML = `<strong>修改前</strong><pre>${esc(lastDifference.before)}</pre><strong>修改后</strong><pre>${esc(lastDifference.after)}</pre>`;
  renderButtons(); renderImages(); renderHistory();
}

function noteEdit(label) {
  state.history.push({id:`edit-${crypto.randomUUID()}`,title:label,kind:'manual',time:new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}),snapshot:clone(state.current)});
}

function flushText() {
  const patch = {};
  for (const id of ['positive','negative']) if ($(id).value !== state.current[id]) patch[id] = $(id).value;
  if (Object.keys(patch).length) {
    const before = state.current.positive;
    edit(state,patch,'手工编辑提示词'); noteEdit('手工编辑提示词');
    lastDifference = {before,after:state.current.positive};
  }
}

function action(fn) {
  if (busy) return;
  flushText();
  const before = state.current.positive;
  const result = fn();
  if (before !== state.current.positive) lastDifference = {before,after:state.current.positive};
  render(); message(result.message,result.ok);
  return result;
}

const pause = milliseconds => new Promise(resolve => setTimeout(resolve,milliseconds));
async function run(kind) {
  if (busy) return;
  flushText(); busy = true; renderButtons();
  try {
    if (kind !== 'generate') {
      $('busy-label').textContent = '正在更新提示词…';
      message('正在演示提示词更新…');
      await pause(700);
      const before = state.current.positive;
      const updated = updatePrompt(state);
      if (!updated.ok) { message(updated.message,false); return; }
      lastDifference = {before,after:state.current.positive};
      render(); message(before === state.current.positive ? '本次提示词没有变化，可直接生成或换个说法再试' : '提示词已更新，可以直接生成或撤销');
      if (kind === 'update') compactView('prompt');
    }
    if (kind !== 'update') {
      $('busy-label').textContent = '正在演示图片生成…';
      await pause(650);
      const result = generate(state);
      if (result.ok) compactView('images');
      message(result.ok ? '演示完成 · 已记录当前用词与条件，图片复用已有样例' : result.message,result.ok);
    }
  } finally { busy = false; render(); }
}

$('delta').addEventListener('input', () => {edit(state,{delta:$('delta').value});renderButtons();});
['positive','negative'].forEach(id => {
  $(id).addEventListener('input', () => { $('draft-status').textContent = '已手工修改';renderButtons(); });
  $(id).addEventListener('change', () => {flushText(); render(); message('已保留手工修改，点击生成即可使用');});
});
['model','workflow','seed','steps','cfg'].forEach(id => $(id).addEventListener('change', () => {
  let value = $(id).value;
  if (id==='steps'||id==='cfg') { value=Number(value);if(!$(id).checkValidity()||!Number.isFinite(value)){render();message('请输入范围内的有效参数',false);return;} }
  const names={model:'模型',workflow:'工作流',seed:'种子',steps:'步数',cfg:'CFG'};
  action(() => { const result=edit(state,{[id]:value},`修改${names[id]}`);noteEdit(`修改${names[id]}：${value}`);return {...result,message:`${names[id]}已修改，可直接生成，无需更新提示词`}; });
}));
$('size').addEventListener('change', () => {const [width,height]=$('size').value.split('x').map(Number);action(()=>{const result=edit(state,{width,height},'修改尺寸');noteEdit(`尺寸改为 ${width} × ${height}`);return {...result,message:'尺寸已修改，可直接生成'};});});
$('update').addEventListener('click',()=>run('update'));
$('generate').addEventListener('click',()=>run('generate'));
$('combined').addEventListener('click',()=>run('combined'));
$('undo').addEventListener('click',()=>action(()=>undo(state)));
$('redo').addEventListener('click',()=>action(()=>redo(state)));
$('restore-image').addEventListener('click',()=>action(()=>restoreImage(state,selected().id)));
$('prompt-only').addEventListener('click',()=>action(()=>restoreImage(state,selected().id,true)));
$('compare').addEventListener('click',()=>{comparing=!comparing;renderImages();});
$('filmstrip').addEventListener('click',event=>{const button=event.target.closest('[data-image]');if(button){selectImage(state,button.dataset.image);renderImages();}});
document.querySelectorAll('[data-suggestion]').forEach(button=>button.addEventListener('click',()=>{edit(state,{delta:button.dataset.suggestion});$('delta').value=state.current.delta;renderButtons();$('delta').focus();}));
$('more-settings').addEventListener('click',()=>{const open=$('advanced').hidden;$('advanced').hidden=!open;$('more-settings').setAttribute('aria-expanded',String(open));$('more-settings').textContent=open?'收起参数':'更多参数';});
$('show-diff').addEventListener('click',()=>{$('prompt-diff').hidden=!$('prompt-diff').hidden;$('show-diff').textContent=$('prompt-diff').hidden?'查看本次文字变化':'收起文字变化';});
$('open-history').addEventListener('click',()=>{flushText();renderHistory();$('history-dialog').showModal();});
$('close-history').addEventListener('click',()=>$('history-dialog').close());
$('history-list').addEventListener('click',event=>{
  const restore=event.target.closest('[data-restore-history]'),view=event.target.closest('[data-view-history]');
  if(restore){action(()=>restoreHistory(state,restore.dataset.restoreHistory));$('history-dialog').close();}
  if(view){expandedHistory=expandedHistory===view.dataset.viewHistory?null:view.dataset.viewHistory;renderHistory();}
});
$('show-used').addEventListener('click',()=>{
  const image=selected(), snapshot=image.snapshot;
  $('used-content').innerHTML=`<p>${esc(image.title)} · 交互预览记录</p><h3>本次演示记录的正向提示词</h3><pre>${esc(snapshot.positive)}</pre><h3>负向提示词</h3><pre>${esc(snapshot.negative)}</pre><h3>生成条件</h3><p>${esc(snapshot.model)} / ${esc(snapshot.workflow)}<br>${snapshot.width} × ${snapshot.height} · ${snapshot.steps} 步 · CFG ${snapshot.cfg} · 种子 ${esc(snapshot.seed)}</p><h3>与当前编辑区对照</h3><p>${matchingText(image)?'正负提示词相同。':'提示词不同，当前修改尚未体现在这张图的记录中。'}</p><p class="quiet">演示中的新增图片复用已有样例，用于体验流程，不代表模型实际输出。</p>`;
  $('used-dialog').showModal();
});
$('close-used').addEventListener('click',()=>$('used-dialog').close());
$('reset').addEventListener('click',()=>{if(busy)return;state=createStudio();comparing=false;expandedHistory=null;lastDifference={before:state.images[0].snapshot.positive,after:state.current.positive};compactView('images');render();message('演示已重置，可以重新体验更新、生成和回退');});
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}}));
const footerObserver = new ResizeObserver(()=>{document.querySelector('.studio').style.paddingBottom=window.innerWidth<=760?`${document.querySelector('.composer').getBoundingClientRect().height+12}px`:'';});
footerObserver.observe(document.querySelector('.composer'));
window.addEventListener('resize',()=>{document.querySelector('.studio').style.paddingBottom=window.innerWidth<=760?`${document.querySelector('.composer').getBoundingClientRect().height+12}px`:'';});
render();
