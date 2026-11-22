import type {WorkflowParameterField, WorkflowParameterSchema, GenerationTarget} from "./types";
export type {WorkflowParameterField, WorkflowParameterSchema} from "./types";

export function basicWorkflowSchema(workflowId: string, templateRevision = ""): WorkflowParameterSchema {
  return {version:1, workflowId, templateRevision, fields:[
    {key:"width",label:"宽度",type:"integer",default:896,min:64,max:8192,step:8,group:"common"},
    {key:"height",label:"高度",type:"integer",default:1152,min:64,max:8192,step:8,group:"common"},
    {key:"batch_size",label:"张数",type:"integer",default:1,min:1,max:100,step:1,group:"common"},
    {key:"seed",label:"Seed",type:"seed",default:"-1",min:"-1",max:"9223372036854775807",group:"common"},
    {key:"steps",label:"Steps",type:"integer",default:35,min:1,max:200,step:1,group:"sampling"},
    {key:"cfg",label:"CFG",type:"number",default:4.5,min:0,max:30,step:0.1,group:"sampling"},
    {key:"sampler",label:"Sampler",type:"string",default:"euler",group:"sampling"},
    {key:"scheduler",label:"Scheduler",type:"string",default:"normal",group:"sampling"},
  ]};
}

export function schemaForTarget(target?: GenerationTarget): WorkflowParameterSchema {
  if (target?.parameter_schema) return target.parameter_schema;
  const schema = basicWorkflowSchema(target?.workflow_profile_id || "", target?.template_revision);
  // Legacy contract exposes actual template constraints, never an environment intersection.
  for (const field of schema.fields) {
    const capability = target?.parameter_capabilities?.[field.key as "steps" | "cfg" | "sampler" | "scheduler"];
    if (capability) {
      field.default = capability.value;
      if (capability.mode === "fixed") field.readOnlyReason = capability.reason || "模板固定";
      if (capability.minimum != null) field.min = capability.minimum;
      if (capability.maximum != null) field.max = capability.maximum;
      // Legacy options were suggestions rather than an exhaustive declaration.
    }
  }
  return schema;
}

export function validateParameter(field: WorkflowParameterField, value: unknown): string | undefined {
  if (value === "" || value == null) return "请输入数值";
  if (field.type === "seed") {
    if (typeof value === "number" && !Number.isSafeInteger(value)) return "Seed 请使用精确十进制文本";
    if (!/^-?\d{1,19}$/.test(String(value))) return "Seed 必须是十进制整数";
    const seed = BigInt(String(value));
    if (seed < BigInt(field.min ?? "-1") || seed > BigInt(field.max ?? "9223372036854775807")) return "Seed 超出允许范围";
  } else if (field.type === "string") {
    if (typeof value !== "string" || !value.trim()) return "请输入值";
    if (field.enum?.length && !field.enum.includes(value)) return "模板不支持此选项";
  } else {
    if (typeof value !== "number" || !Number.isFinite(value)) return "请输入有效数值";
    if (field.type === "integer" && !Number.isInteger(value)) return "请输入整数";
    if ((field.min != null && value < Number(field.min)) || (field.max != null && value > Number(field.max))) return `允许范围 ${field.min ?? "—"}–${field.max ?? "—"}`;
  }
  return undefined;
}
