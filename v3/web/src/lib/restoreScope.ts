import {emptyRequirements,type LocalConversation} from "./conversation";
import {reconcileArtistPresetCompiled} from "./artistPresetApplication";
/** Content versions carry meaning and locks; execution/resource bindings remain current. */
export function restoreContent(current:LocalConversation,historical:Partial<LocalConversation>,source:string):LocalConversation {
 const requirements=structuredClone(historical.requirements||emptyRequirements());
 requirements.loras=structuredClone(current.requirements.loras);
 const restored={...current,positive:historical.positive||"",negative:historical.negative||"",mode:historical.mode||current.mode,requirements,restoredFrom:source};
 delete restored.artistPresetPlacement;
 delete restored.artistPresetCustomized;
 return reconcileArtistPresetCompiled(restored);
}
