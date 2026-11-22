import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,expect,it,vi} from "vitest";
import {LoraLibraryPage} from "./LoraLibraryPage";

afterEach(()=>{cleanup();vi.restoreAllMocks();});
it("shows skipped files and saves a classification without uploading files",async()=>{
  const sha="f".repeat(64);
  const asset={id:sha,sha256:sha,name:"Pencil",family:"unknown",relative_path:"style/Pencil.safetensors",file_name:"remote",size_bytes:100,model_profiles:[],trigger_words:[],weight:1,clip_weight:null,present:true,valid:true,error:""};
  const calls:{url:string;body:Record<string,unknown>|null}[]=[];
  let items:typeof asset[]=[];
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,options)=>{
    const url=String(input),body=options?.body?JSON.parse(String(options.body)):null;
    calls.push({url,body});
    if(url.endsWith("/scan")){items=[asset];return Response.json({root_path:"loras",items,errors:[{path:"bad.safetensors",error:"文件不完整"}]});}
    if(options?.method==="PUT"){Object.assign(asset,body);return Response.json(asset);}
    return Response.json({root_path:"loras",items});
  });
  render(<LoraLibraryPage profiles={[{id:"turbo",family:"anima",display_name:"ANIMA Turbo",variant:"turbo"}]}/>);
  await screen.findByText(/文件夹尚未收录/);
  fireEvent.click(screen.getByRole("button",{name:"扫描文件"}));
  await screen.findByText(/bad.safetensors/);
  fireEvent.click(screen.getByRole("button",{name:"编辑资料"}));
  fireEvent.change(screen.getByLabelText("模型系列"),{target:{value:"anima"}});
  fireEvent.click(screen.getByLabelText("ANIMA Turbo"));
  fireEvent.change(screen.getByLabelText("触发词（每行一项）"),{target:{value:"ink\nink"}});
  fireEvent.click(screen.getByRole("button",{name:"保存资料"}));
  await waitFor(()=>expect(calls.find(call=>call.url.endsWith(sha))?.body).toMatchObject({family:"anima",model_profiles:["turbo"],trigger_words:["ink"]}));
  expect(calls.some(call=>call.url.includes("/sync"))).toBe(false);
});
