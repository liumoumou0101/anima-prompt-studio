import {beforeEach, describe, expect, it, vi} from "vitest";
import {apiRequest} from "./api";
import {artistPresetsApi} from "./artistPresets";
vi.mock("./api", () => ({apiRequest: vi.fn()}));
beforeEach(() => vi.clearAllMocks());
describe("artist preset transport", () => {
  it("marks DELETE mutations as JSON and retains expected revisions", async () => {
    await artistPresetsApi.remove("preset", 7);
    await artistPresetsApi.removeSample("preset", "sample", 8);
    expect(apiRequest).toHaveBeenNthCalledWith(1, "/api/v3/artist-presets/preset?expected_revision=7", {method: "DELETE", headers: {"Content-Type": "application/json"}});
    expect(apiRequest).toHaveBeenNthCalledWith(2, "/api/v3/artist-presets/preset/samples/sample?expected_revision=8", {method: "DELETE", headers: {"Content-Type": "application/json"}});
  });
  it("uses bounded multipart upload metadata without declaring a JSON body", async () => {
    const metadata = {caption: "原图", model_label: "Anima", source_url: "", full_positive: "raw\n  @a", full_negative: "", parameters: {seed: "18446744073709551615"}};
    await artistPresetsApi.uploadSample("preset", new File(["image"], "sample.png", {type: "image/png"}), metadata, 9);
    const init = vi.mocked(apiRequest).mock.calls[0][1]!;
    expect(init.headers).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect(JSON.parse(String((init.body as FormData).get("metadata")))).toEqual({...metadata, expected_revision: 9});
  });
  it("can export one entry including its samples", async () => {
    await artistPresetsApi.export("preset /1");
    expect(apiRequest).toHaveBeenCalledWith("/api/v3/artist-presets/export?preset_id=preset%20%2F1");
  });
});
