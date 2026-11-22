export type PromptDiffKind = "same" | "added" | "removed";
export interface PromptDiffPart {kind: PromptDiffKind; text: string}

const MAX_LCS_CELLS = 120_000;
const tokenPattern = /\p{Script=Han}|[\p{L}\p{N}_]+|\s+|[^\s\p{L}\p{N}_]/gu;

function tokens(value: string): string[] {
  return value.match(tokenPattern) || [];
}

function append(parts: PromptDiffPart[], kind: PromptDiffKind, text: string): void {
  if (!text) return;
  const last = parts.at(-1);
  if (last?.kind === kind) last.text += text;
  else parts.push({kind, text});
}

function fallback(before: string, after: string): PromptDiffPart[] {
  let prefix = 0;
  const limit = Math.min(before.length, after.length);
  while (prefix < limit && before[prefix] === after[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < limit - prefix && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) suffix += 1;
  const parts: PromptDiffPart[] = [];
  append(parts, "same", before.slice(0, prefix));
  append(parts, "removed", before.slice(prefix, before.length - suffix));
  append(parts, "added", after.slice(prefix, after.length - suffix));
  append(parts, "same", before.slice(before.length - suffix));
  return parts;
}

export function diffPrompt(before: string, after: string): PromptDiffPart[] {
  if (before === after) return before ? [{kind: "same", text: before}] : [];
  const left = tokens(before), right = tokens(after);
  if (left.length * right.length > MAX_LCS_CELLS) return fallback(before, after);
  const width = right.length + 1;
  const table = new Uint32Array((left.length + 1) * width);
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      table[i * width + j] = left[i] === right[j]
        ? table[(i + 1) * width + j + 1] + 1
        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const parts: PromptDiffPart[] = [];
  let i = 0, j = 0;
  while (i < left.length || j < right.length) {
    if (i < left.length && j < right.length && left[i] === right[j]) {
      append(parts, "same", left[i]); i += 1; j += 1;
    } else if (j < right.length && (i === left.length || table[i * width + j + 1] >= table[(i + 1) * width + j])) {
      append(parts, "added", right[j]); j += 1;
    } else {
      append(parts, "removed", left[i]); i += 1;
    }
  }
  return parts;
}
