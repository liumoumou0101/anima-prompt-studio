import {expect,it} from "vitest";
import {basicWorkflowSchema,schemaForTarget,validateParameter} from "./workflowParameterSchema";
import type {GenerationTarget} from "./types";

it("keeps schema bound to workflow rather than intersecting execution environments",()=>{
  const schema = basicWorkflowSchema("base","v1");
  const target = {workflow_profile_id:"base",parameter_schema:schema} as GenerationTarget;
  expect(schemaForTarget(target)).toBe(schema);
  expect(schema.fields.some(field=>field.key==="refiner_steps")).toBe(false);
});
it("uses only declared second-stage fields and validates exhaustive enums",()=>{
  const field = {key:"refiner_sampler",label:"精修采样器",type:"string" as const,default:"euler",enum:["euler","er_sde"],group:"workflow" as const};
  expect(validateParameter(field,"unsupported")).toBe("模板不支持此选项");
  expect(validateParameter(field,"er_sde")).toBeUndefined();
});
