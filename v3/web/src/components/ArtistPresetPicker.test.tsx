import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {apiRequest} from "../lib/api";
import {ArtistPresetPicker,artistPresetSnapshot} from "./ArtistPresetPicker";
import type {ArtistPreset} from "../lib/artistPresets";
vi.mock("../lib/api",()=>({apiRequest:vi.fn()}));
function preset(overrides:Partial<ArtistPreset>={}):ArtistPreset{return {id:"p1",revision:2,name:"组合甲",positive:"(@a:1.2), @b ",negative:"bad style",model_family:"anima",model_label:"Anima Base 1.0",syntax:"comfy",source_url:"https://example.com/source",source_author:"author",notes:"memo",favorite:false,content_hash:"hash",created_at:"now",updated_at:"now",samples:[],ready:false,...overrides};}
beforeEach(()=>{localStorage.clear();vi.mocked(apiRequest).mockReset();});
afterEach(cleanup);
it("loads only when requested, defaults to Anima and sends a literal frozen snapshot",async()=>{
  const one=preset(),other=preset({id:"p2",name:"其他组合",model_family:"novelai"});
  vi.mocked(apiRequest).mockResolvedValue({items:[one,other]});const apply=vi.fn();
  render(<MemoryRouter><ArtistPresetPicker model="anima_base_v1" onApply={apply} onRemove={vi.fn()}/></MemoryRouter>);
  expect(apiRequest).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"选择画师串"}));
  fireEvent.click(await screen.findByRole("button",{name:/组合甲/}));
  expect(screen.queryByRole("button",{name:/其他组合/})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"应用这组画师串"}));
  expect(apply).toHaveBeenCalledWith(artistPresetSnapshot(one));
  expect(apply.mock.calls[0][0].positive).toBe("(@a:1.2), @b ");
  expect(apply.mock.calls[0][0]).not.toHaveProperty("samples");
  expect(JSON.parse(localStorage.getItem("anima-artist-preset-recent")!)).toEqual(["p1"]);
});
it("shows other-model warning and uses explicit replacement, without switching model",async()=>{
  const other=preset({id:"p2",name:"NAI 串",model_family:"novelai",model_label:"NovelAI 4.5",syntax:"novelai"});
  vi.mocked(apiRequest).mockResolvedValue({items:[other]});const apply=vi.fn();
  render(<MemoryRouter><ArtistPresetPicker model="anima_base_v1" active={artistPresetSnapshot(preset())} preferredId="p2" onApply={apply} onRemove={vi.fn()}/></MemoryRouter>);
  expect(await screen.findByText(/与当前 Anima 不同/)).toBeInTheDocument();
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"替换当前画师串"}));
  expect(apply).toHaveBeenCalledWith(artistPresetSnapshot(other));
});
it("does not dismiss the picker or remember a failed application",async()=>{
  vi.mocked(apiRequest).mockResolvedValue({items:[preset()]});
  render(<MemoryRouter><ArtistPresetPicker model="anima_base_v1" preferredId="p1" onApply={()=>false} onRemove={vi.fn()}/></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button",{name:"应用这组画师串"}));
  expect(screen.getByRole("button",{name:"应用这组画师串"})).toBeInTheDocument();
  expect(localStorage.getItem("anima-artist-preset-recent")).toBeNull();
});
