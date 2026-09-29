import type {ConversationRecord} from "./conversation";

export type PersonalPromptText = {positive: string; negative: string};
export type PersonalPromptTransfer = PersonalPromptText & {version: 1; id: string};
export type PersonalPromptReceipt = {
  id: string; workspace_id: string; result_revision: number; state: "applied" | "undone";
  can_undo: boolean; undo_revision: number | null;
};
export type PersonalPromptResult = {workspace: ConversationRecord; receipt: PersonalPromptReceipt; replayed: boolean};
const prefix = "anima-personal-prompt-transfer:";
function validate(value: PersonalPromptTransfer) {
  if (!value || value.version !== 1 || typeof value.id !== "string" || !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(value.id)
    || typeof value.positive !== "string" || typeof value.negative !== "string"
    || value.positive.length > 20000 || value.negative.length > 20000 || !(value.positive + value.negative).trim()) {
    throw new Error("个人提示词传递记录无效，请从个人标签超市重新追加。");
  }
}
export function storePersonalPromptTransfer(value: PersonalPromptText): string {
  const transfer: PersonalPromptTransfer = {...value, version: 1, id: crypto.randomUUID()};
  validate(transfer);
  localStorage.setItem(prefix + transfer.id, JSON.stringify(transfer));
  return `/workbench?personal_transfer=${transfer.id}`;
}
export function readPersonalPromptTransfer(id: string): PersonalPromptTransfer | null {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(id)) throw new Error("个人提示词传递标识无效。");
  const raw = localStorage.getItem(prefix + id);
  if (!raw) return null;
  const value = JSON.parse(raw) as PersonalPromptTransfer;
  validate(value);
  if (value.id !== id) throw new Error("个人提示词传递标识不匹配。");
  return value;
}
export function consumePersonalPromptTransfer(id: string) {localStorage.removeItem(prefix + id);}
export function appendPersonalPromptText(before: PersonalPromptText, addition: PersonalPromptText): PersonalPromptText {
  const join = (left: string, right: string) => left + (left && right ? "\n" : "") + right;
  return {positive: join(before.positive, addition.positive), negative: join(before.negative, addition.negative)};
}
