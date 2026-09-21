// Local interaction demo: no model, image service, persistence, or network calls.
const clone = value => JSON.parse(JSON.stringify(value));
const result = (ok, message) => ({ ok, message });
let sequence = 0;
const nextId = prefix => `${prefix}-${Date.now()}-${++sequence}`;
const time = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
const basePositive = 'adult woman, red coat, white shirt, holding bouquet, standing on old street, evening, anime illustration';
const supported = '此交互示例支持：外套换蓝 / 红、背景改为月夜、增强暖色光照、没有变化。';

function addHistory(state, title, kind, imageId) {
  const item = { id: nextId('history'), title, kind, time: time(), snapshot: clone(state.current) };
  if (imageId) item.imageId = imageId;
  state.history.push(item);
}

function record(state, before, label) {
  if (JSON.stringify(before) === JSON.stringify(state.current)) return false;
  state.undoStack.push({ label, before, after: clone(state.current) });
  state.redoStack.length = 0;
  return true;
}

export function createStudio() {
  const current = {
    positive: basePositive,
    negative: 'worst quality, low quality, artist name, blurry, jpeg artifacts, chromatic aberration',
    delta: '',
    intentTitle: '外套换成红色',
    model: 'Turbo v1.1',
    workflow: '基础文生图',
    width: 640,
    height: 832,
    seed: '20260918',
    steps: 10,
    cfg: 1,
    sourceId: 'image-red',
  };
  const blue = { ...current, positive: basePositive.replace('red coat', 'blue coat'), intentTitle: '蓝外套 · 初始画面', sourceId: 'image-blue' };
  return {
    current,
    images: [
      { id: 'image-blue', src: 'assets/blue.png', title: '蓝外套 · 初始画面', note: '初始画面：蓝外套、白衬衫，手捧花束。', snapshot: clone(blue), isDemo: true },
      { id: 'image-red', src: 'assets/red.png', title: '外套换成红色', note: '修改意见：外套换成红色，其余保持。', snapshot: clone(current), isDemo: true },
    ],
    history: [
      { id: 'history-blue', title: '蓝外套 · 初始画面', kind: 'generate', time: '14:20', imageId: 'image-blue', snapshot: clone(blue) },
      { id: 'history-red', title: '外套换成红色', kind: 'generate', time: '14:23', imageId: 'image-red', snapshot: clone(current) },
    ],
    selectedImageId: 'image-red',
    undoStack: [],
    redoStack: [],
  };
}

export function edit(state, patch, label = '手动修改工作区') {
  const before = clone(state.current);
  const keys = Object.keys(patch).filter(key => Object.hasOwn(state.current, key));
  keys.forEach(key => { state.current[key] = patch[key]; });
  if (keys.some(key => key !== 'delta')) record(state, before, label);
  return result(true, keys.length === 1 && keys[0] === 'delta' ? '修改意见已输入。' : '工作区已修改。');
}

function setTag(prompt, pattern, replacement) {
  if (pattern.test(prompt)) return prompt.replace(pattern, replacement);
  return `${prompt.trim().replace(/[,，]\s*$/, '')}, ${replacement}`;
}

export function updatePrompt(state) {
  const input = state.current.delta.trim();
  if (!input) return result(false, '请先输入修改意见。');
  if (!state.current.positive.trim()) return result(false, '请先填写正向提示词，再应用修改意见。');
  const rules = [
    { pattern: /(?:把)?外套(?:换成|换为|改为|改成|换)(蓝色?|红色?)/g, type: 'coat' },
    { pattern: /(?:把)?背景(?:改为|改成|换成|换为)月夜/g, type: 'night' },
    { pattern: /增强暖色光照/g, type: 'warm' },
    { pattern: /没有变化/g, type: 'same' },
  ];
  const matches = [];
  let remaining = input;
  for (const rule of rules) {
    remaining = remaining.replace(rule.pattern, (whole, color, offset) => {
      matches.push({ type: rule.type, color, position: input.indexOf(whole) });
      return '';
    });
  }
  // Accept combinations of the listed rules, but never silently ignore unknown requests.
  remaining = remaining.replace(/[\s,，。.!！;；、]/g, '').replace(/(?:其余|其他|人物(?:和背景)?|背景)保持(?:不变)?|并且|然后|以及|并/g, '');
  if (remaining || !matches.length) return result(false, supported);
  if (matches.some(item => item.type === 'same') && matches.some(item => item.type !== 'same')) {
    return result(false, '“没有变化”不能与其他修改同时使用，请明确一项修改意见。');
  }
  const before = clone(state.current);
  let positive = state.current.positive;
  for (const match of matches.sort((a, b) => a.position - b.position)) {
    if (match.type === 'coat') {
      const coatPattern = /\b(?:red|blue|green|yellow|black|white|pink|purple|brown|gray|grey|orange|beige|navy|teal|cyan|magenta|maroon|olive)\s+coat\b/gi;
      if (/\bcoat\b/i.test(positive.replace(coatPattern, ''))) {
        return result(false, '此交互示例仅支持常见单色 coat 的颜色替换，请先手动整理外套描述。');
      }
      positive = setTag(positive, coatPattern, `${match.color.startsWith('蓝') ? 'blue' : 'red'} coat`);
    }
    if (match.type === 'night') {
      positive = setTag(positive, /\b(?:evening|daytime|sunset|moonlit night)\b/gi, 'moonlit night');
    }
    if (match.type === 'warm') {
      positive = setTag(positive, /\b(?:soft warm lighting|warm lighting|warm light|enhanced warm lighting)\b/gi, 'enhanced warm lighting');
    }
  }
  state.current.positive = positive;
  state.current.delta = '';
  state.current.intentTitle = input;
  record(state, before, '更新提示词');
  addHistory(state, matches.every(item => item.type === 'same') ? '保持提示词不变' : `更新提示词：${input}`, 'update');
  return result(true, positive === before.positive ? '已确认保持当前提示词，修改意见已清空。' : '已按示例规则更新提示词；可继续手动编辑或生成。');
}

export function generate(state) {
  if (!state.current.positive.trim()) return result(false, '请先填写正向提示词。');
  const id = nextId('image');
  const blue = /\bblue coat\b/i.test(state.current.positive);
  const title = `${state.current.intentTitle || '当前提示词'} · 样例 ${state.images.length + 1}`;
  state.images.push({
    id,
    src: blue ? 'assets/blue.png' : 'assets/red.png',
    title,
    note: '交互演示：复用预置样例图；已保存生成时的提示词和参数。待处理意见不会参与生成。',
    snapshot: clone(state.current),
    isDemo: true,
  });
  state.selectedImageId = id;
  addHistory(state, title, 'generate', id);
  return result(true, '已追加样例图并保存当前快照。本预览未调用图像生成服务。');
}

function restore(state, snapshot, sourceId, onlyPrompt, label, keepDelta = false) {
  const before = clone(state.current);
  addHistory(state, '恢复前的草稿', 'draft', before.sourceId);
  if (onlyPrompt) {
    state.current.positive = snapshot.positive;
    state.current.negative = snapshot.negative;
    state.current.intentTitle = snapshot.intentTitle || '当前提示词';
  } else {
    state.current = clone(snapshot);
  }
  state.current.delta = keepDelta ? snapshot.delta : '';
  state.current.sourceId = sourceId || snapshot.sourceId || null;
  record(state, before, label);
  addHistory(state, label, 'restore', state.current.sourceId);
  return result(true, onlyPrompt ? '已恢复正负提示词，保留当前模型和参数。' : '已恢复提示词、模型和生成参数，可继续修改。');
}

export function restoreImage(state, id, onlyPrompt = false) {
  const target = state.images.find(item => item.id === id);
  if (!target) return result(false, '未找到这张图片。');
  return restore(state, target.snapshot, id, onlyPrompt, onlyPrompt ? '仅恢复图片提示词' : '恢复图片快照');
}

export function restoreHistory(state, id) {
  const target = state.history.find(item => item.id === id);
  if (!target) return result(false, '未找到这条历史记录。');
  const sourceId = target.imageId || target.snapshot.sourceId;
  const restored = restore(state, target.snapshot, sourceId, false, '恢复历史快照', target.kind === 'draft');
  if (restored.ok && state.images.some(item => item.id === sourceId)) state.selectedImageId = sourceId;
  return restored;
}

function travel(state, from, to, targetKey, expectedKey, verb) {
  const operation = state[from].pop();
  if (!operation) return result(false, `没有可${verb}的操作。`);
  const freshDelta = state.current.delta !== operation[expectedKey].delta ? state.current.delta : undefined;
  state.current = clone(operation[targetKey]);
  if (freshDelta !== undefined) state.current.delta = freshDelta;
  state[to].push(operation);
  return result(true, `已${verb}：${operation.label}。`);
}

export function undo(state) {
  return travel(state, 'undoStack', 'redoStack', 'before', 'after', '撤销');
}

export function redo(state) {
  return travel(state, 'redoStack', 'undoStack', 'after', 'before', '重做');
}

export function selectImage(state, id) {
  if (!state.images.some(item => item.id === id)) return result(false, '未找到这张图片。');
  state.selectedImageId = id;
  return result(true, '已选择图片。');
}
