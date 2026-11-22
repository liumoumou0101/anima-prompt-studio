import {describe, expect, it} from "vitest";
import type {GenerationTarget} from "./types";
import {targetDescription, targetLabel, targetRemoteLabel} from "./workflowTargets";

const target = (overrides: Partial<GenerationTarget> = {}): GenerationTarget => ({
  remote_profile_id: "cloud", remote_display_name: "测试环境", workflow_profile_id: "v3_aesthetic_v1_1",
  workflow_display_name: "ANIMA Aesthetic - V3 Baseline v1.1", workflow_kind: "txt2img_basic",
  workflow_origin: "official", compatible_model_profiles: ["anima_aesthetic_v1_1"],
  host_fingerprint_ready: false, auth_type: "agent", private_key_passphrase_configured: false,
  ...overrides,
});

describe("workflow target presentation", () => {
  it("distinguishes built-in model versions and experimental variants without changing target data", () => {
    const targets = [
      target({workflow_profile_id: "v3_aesthetic_v1_0", workflow_display_name: "ANIMA Aesthetic - V3 Legacy v1.0", compatible_model_profiles: ["anima_aesthetic_v1_0"]}),
      target(),
      target({workflow_profile_id: "23_Turbo_v1.1", workflow_display_name: "ANIMA Turbo v1.1 - Verified Baseline", compatible_model_profiles: ["anima_turbo_v1_1"]}),
      target({workflow_profile_id: "26_Turbo_v1.1", workflow_display_name: "ANIMA Turbo v1.1 - Community Optimization", compatible_model_profiles: ["anima_turbo_v1_1"], experimental: true}),
    ];
    const before = structuredClone(targets);
    const labels = targets.map(item => targetLabel(item, targets));
    expect(new Set(labels).size).toBe(4);
    expect(labels[0]).toContain("v1.0");
    expect(labels[1]).toContain("v1.1");
    expect(labels[2]).not.toContain("实验");
    expect(labels[3]).toContain("实验");
    expect(labels.every(label => /[\u4e00-\u9fff]/.test(label))).toBe(true);
    expect(targets).toEqual(before);
  });

  it("keeps custom names and uses explicit origin when user and built-in IDs overlap", () => {
    const custom = target({workflow_origin: "user", workflow_display_name: "我的 Aesthetic - V3 Baseline v1.1"});
    const official = target({workflow_profile_id: "official:v3_aesthetic_v1_1"});
    expect(targetLabel(custom)).toContain(custom.workflow_display_name);
    expect(targetLabel(custom)).toContain("用户");
    expect(targetLabel(official)).toContain("内置");
    expect(targetLabel(official)).not.toContain("V3 Baseline");
    const legacyUnknown = target({workflow_origin: undefined, workflow_display_name: "保留本地修改名"});
    expect(targetLabel(legacyUnknown)).toContain("保留本地修改名");
    expect(targetLabel({...legacyUnknown, workflow_profile_id: "official:v3_aesthetic_v1_1"})).toContain("保留本地修改名");
  });

  it("disambiguates same-name copies even when their ID prefixes collide", () => {
    const targets = ["user:12345678-a", "user:12345678-b"].map(workflow_profile_id => target({
      workflow_profile_id, workflow_origin: "user", workflow_display_name: "我的模板",
    }));
    const labels = targets.map(item => targetLabel(item, targets));
    expect(new Set(labels).size).toBe(2);
    expect(labels[0]).toContain(targets[0].workflow_profile_id);
    expect(labels[1]).toContain(targets[1].workflow_profile_id);
    expect(targetLabel(targets[0], [targets[0]])).not.toContain(targets[0].workflow_profile_id);
  });

  it("describes the actual workflow kind and retains unknown types for diagnosis", () => {
    const enlarged = target({workflow_profile_id: "user:hires", workflow_origin: "user", workflow_kind: "txt2img_hiresfix_1_5x"});
    expect(targetLabel(enlarged)).toContain("1.5");
    expect(targetDescription(enlarged)).toContain("放大");
    expect(targetDescription(enlarged)).toContain("user:hires");
    expect(targetLabel(target({workflow_kind: "future_kind"}))).toContain("future_kind");
    expect(targetDescription({...enlarged, workflow_notes: "放大需要已安装的模型文件"})).toContain("放大需要已安装的模型文件");
  });

  it("translates known official notes but preserves identical user notes and new official notes", () => {
    const english = "Packaged verified ANIMA Turbo v1.1 baseline. Uses 10 steps, CFG 1, er_sde, simple scheduler, and no legacy Turbo LoRA.";
    const turbo = target({workflow_profile_id: "23_Turbo_v1.1", workflow_notes: english});
    const translated = targetDescription(turbo);
    expect(translated).not.toContain("Packaged");
    expect(translated).toContain("10");
    expect(translated).toContain("CFG 1");
    expect(translated).toContain("er_sde");
    expect(translated).toContain("simple");
    expect(targetDescription({...turbo, workflow_origin: "user"})).toContain(english);
    const customNotes = "Keep my custom sampler setup, 32 steps.";
    expect(targetDescription({...turbo, workflow_notes: customNotes})).toContain(customNotes);
  });
});

describe("remote target labels", () => {
  it("keeps one connection's name concise even when it has several workflow choices", () => {
    const first = target({remote_ssh_host: "host.example", remote_ssh_port: 2222});
    const second = {...first, workflow_profile_id: "other-workflow"};
    expect(targetRemoteLabel(first, [first, second])).toBe("测试环境");
  });

  it("uses host and port to distinguish same-name connections without changing any identifiers", () => {
    const remotes = [
      target({remote_profile_id: "one", remote_ssh_host: "host.example", remote_ssh_port: 2222}),
      target({remote_profile_id: "two", remote_ssh_host: "host.example", remote_ssh_port: 3333}),
      target({remote_profile_id: "three", remote_ssh_host: "2001:db8::1", remote_ssh_port: 2222}),
    ];
    const before = structuredClone(remotes);
    const labels = remotes.map(item => targetRemoteLabel(item, remotes));
    expect(new Set(labels).size).toBe(3);
    expect(labels[0]).toContain("host.example:2222");
    expect(labels[1]).toContain("host.example:3333");
    expect(labels[2]).toContain("[2001:db8::1]:2222");
    expect(remotes).toEqual(before);
  });

  it("uses the HTTP endpoint for local connections instead of their placeholder SSH values", () => {
    const remotes = [8188, 8189].map((port, index) => target({remote_profile_id: `local-${index}`,
      connection_type: "local", remote_ssh_host: "unused", remote_ssh_port: 22,
      remote_comfy_host: "::1", remote_comfy_port: port}));
    expect(targetRemoteLabel(remotes[0], remotes)).toContain("http://[::1]:8188");
    expect(targetRemoteLabel(remotes[1], remotes)).toContain("http://[::1]:8189");
    expect(targetRemoteLabel(remotes[0], remotes)).not.toContain("unused");
  });

  it("falls back to full IDs when same-endpoint connections also share an ID prefix", () => {
    const remotes = ["12345678-a", "12345678-b"].map(remote_profile_id => target({remote_profile_id,
      remote_ssh_host: "host.example", remote_ssh_port: 22}));
    expect(targetRemoteLabel(remotes[0], remotes)).toContain("12345678-a");
    expect(targetRemoteLabel(remotes[1], remotes)).toContain("12345678-b");
    const noAddress = ["abcdefgh-rest", "ijklmnop-rest"].map(remote_profile_id => target({remote_profile_id}));
    const labels = noAddress.map(item => targetRemoteLabel(item, noAddress));
    expect(labels[0]).toContain("abcdefgh");
    expect(labels[1]).toContain("ijklmnop");
    expect(new Set(labels).size).toBe(2);
  });
});
