import type {RequirementsEdit} from "./conversation";
import {normalizeIdentityTags} from "./conversation";

export function declaredIdentityTags(requirements:RequirementsEdit):string[] {
  const subject=requirements.layers.subject,style=requirements.layers.style;
  const names=[...normalizeIdentityTags([...(subject.character_tags||[]),...(subject.series_tags||[]),...(subject.general_tags||[])]),
    ...normalizeIdentityTags([...style.artists,...(style.manual_artist_tags||[])],true).map(name=>"@"+name)];
  return [...new Set(names)].map(name=>name.replace(/[()]/g,"\\$&"));
}
const normalized=(value:string)=>normalizeIdentityTags([value])[0]||"";
function tokenKey(value:string,known:Set<string>):string|null {
  let key=normalized(value);if(known.has(key))return key;
  for(let depth=0;depth<32;depth++){
    const match=value.trim().match(/^\((.*?)(?::\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+))?\)$|^\[(.*)\]$/);
    if(!match)return null;
    value=(match[1]??match[2]).trim();key=normalized(value);
    if(known.has(key))return key;
  }
  return null;
}
function tokens(text:string) {
  const result:{start:number;end:number;key:string|null;raw:string}[]=[];
  let start=0;
  for(let index=0;index<=text.length;index++)if(index===text.length||text[index]===","||text[index]==="\n"){
    result.push({start,end:index,key:null,raw:text.slice(start,index)});start=index+1;
  }
  return result;
}
/** Detect complete literal/weighted tag tokens; prose mentions are left as prose. */
export function missingIdentityTags(positive:string,tags:string[]):string[] {
  const known=new Set(tags.map(normalized)),present=new Set(tokens(positive).map(token=>tokenKey(token.raw,known)));
  return tags.filter(tag=>!present.has(normalized(tag)));
}
/** Overlay only a changed explicit selection; ordinary prompt edits stay exact. */
export function overlayIdentityTags(positive:string,next:RequirementsEdit,previous:RequirementsEdit):string {
  const tags=declaredIdentityTags(next),prior=declaredIdentityTags(previous);
  if(JSON.stringify(tags)===JSON.stringify(prior))return positive;
  const selected=new Set(tags.map(normalized)),known=new Set([...tags,...prior].map(normalized));
  let text=positive,marker="identitypresetblock";
  const preset=next.layers.style.artist_preset?.positive;
  while(text.includes(marker)||preset?.includes(marker))marker+="x";
  if(preset)text=text.replaceAll(preset,marker);
  const entries=tokens(text).map(token=>({...token,key:tokenKey(token.raw,known)}));
  const preferred=new Map<string,number>();
  entries.forEach((token,index)=>{
    if(!token.key||!selected.has(token.key))return;
    const priorIndex=preferred.get(token.key);
    if(priorIndex===undefined||normalized(token.raw)!==token.key&&normalized(entries[priorIndex].raw)===token.key)preferred.set(token.key,index);
  });
  const removed=entries.map((token,index)=>Boolean(token.key&&(!selected.has(token.key)||preferred.get(token.key)!==index)));
  const ranges:[number,number][]=[];
  entries.forEach((token,index)=>{
    if(!removed[index])return;
    const hasFollowing=entries.some((other,nextIndex)=>nextIndex>index&&!removed[nextIndex]&&other.raw.trim());
    if(hasFollowing){
      let end=Math.min(text.length,token.end+1);
      // A standard comma separator owns one space, never the body's indentation.
      const hasPrior=entries.some((other,priorIndex)=>priorIndex<index&&!removed[priorIndex]&&other.raw.trim());
      if(!hasPrior&&text[token.end]===","&&text[end]===" ")end++;
      ranges.push([token.start,end]);
    }else{
      const prior=entries.slice(0,index).findLast((other,priorIndex)=>!removed[priorIndex]&&other.raw.trim());
      ranges.push([prior?.end||0,text.length]);
    }
  });
  let body="",cursor=0;
  for(const [start,end] of ranges.sort((a,b)=>a[0]-b[0])){if(start>cursor)body+=text.slice(cursor,start);cursor=Math.max(cursor,end);}
  body+=text.slice(cursor);
  // Missing prior selections may have been deliberately deleted in the editor.
  const previousKeys=new Set(prior.map(normalized));
  const added=tags.filter(tag=>!previousKeys.has(normalized(tag)));
  const missing=missingIdentityTags(body,added);
  if(missing.length)body=missing.join(", ")+(body.trim()?", "+body:"");
  if(preset)body=body.replaceAll(marker,preset);
  return body.trim()?body:"";
}
