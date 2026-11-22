import {act,cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {PromptTranslationPreview} from "./PromptTranslationPreview";
const result={positive_prompt:"blue coat, custom_word",negative_prompt:"bad",chinese_positive:"蓝色外套，custom_word",chinese_negative:"差",matched_count:1,unmatched_count:1,translation_engine:"local dictionary",positive_tokens:[{original:"blue coat",zh:"蓝色外套",matched:true,canonical_tag:"blue_coat"},{original:"custom_word",zh:"custom_word",matched:false}],negative_tokens:[{original:"bad",zh:"差",matched:true,canonical_tag:"bad"}]};
beforeEach(()=>{sessionStorage.setItem("anima-v3-session","test");vi.spyOn(globalThis,"fetch").mockResolvedValue(new Response(JSON.stringify(result)));});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it("requests explicit read-only dictionary/local translation and preserves original text",async()=>{
 render(<PromptTranslationPreview positive={"  blue coat, custom_word\n"} negative="bad" model="anima"/>);
 expect(fetch).not.toHaveBeenCalled();fireEvent.click(screen.getByText("中英标签对照",{selector:"summary"}));fireEvent.click(screen.getByRole("button",{name:"查看中文对照"}));
 await screen.findByText("蓝色外套，custom_word");expect(screen.getByText("未匹配，保留原词")).toBeInTheDocument();expect(screen.getByText(/1 个已对照中文标签/)).toHaveTextContent("1 个未入词典");
 expect(fetch).toHaveBeenCalledTimes(1);const [url,init]=vi.mocked(fetch).mock.calls[0];expect(url).toBe("/api/v3/direct-prompt/preview");expect(JSON.parse(String(init?.body))).toEqual({positive_prompt:"  blue coat, custom_word\n",negative_prompt:"bad"});
 expect(screen.queryByRole("textbox")).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:/送到|生成|更新提示词/})).not.toBeInTheDocument();
});
it("aborts input/model changes and ignores an older result even if abort is not honored",async()=>{
 let finish!:(response:Response)=>void;vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 const view=render(<PromptTranslationPreview positive="old prompt" negative="" model="old"/>);fireEvent.click(screen.getByText("中英标签对照",{selector:"summary"}));fireEvent.click(screen.getByRole("button",{name:"查看中文对照"}));
 const signal=vi.mocked(fetch).mock.calls[0][1]?.signal;view.rerender(<PromptTranslationPreview positive="new prompt" negative="" model="new"/>);expect(signal?.aborted).toBe(true);
 await act(async()=>finish(new Response(JSON.stringify(result))));expect(screen.queryByText("蓝色外套，custom_word")).not.toBeInTheDocument();expect(screen.getByRole("button",{name:"查看中文对照"})).toBeEnabled();
});
it("aborts on unmount and blocks blank or disabled requests",()=>{
 const view=render(<PromptTranslationPreview positive="" negative="" model="anima"/>);fireEvent.click(screen.getByText("中英标签对照",{selector:"summary"}));expect(screen.getByRole("button",{name:"查看中文对照"})).toBeDisabled();
 view.rerender(<PromptTranslationPreview positive="text" negative="" model="anima" disabled/>);expect(screen.getByRole("button",{name:"查看中文对照"})).toBeDisabled();
 vi.mocked(fetch).mockImplementationOnce(()=>new Promise(()=>{}));view.rerender(<PromptTranslationPreview positive="text" negative="" model="anima"/>);fireEvent.click(screen.getByRole("button",{name:"查看中文对照"}));const signal=vi.mocked(fetch).mock.calls[0][1]?.signal;view.unmount();expect(signal?.aborted).toBe(true);
});
