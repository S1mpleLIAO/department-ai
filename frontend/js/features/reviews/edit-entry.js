import { request } from '../../core/http.js'
import { identity,spaceId } from '../../core/session.js'
import { toast } from '../../ui/feedback.js'
import { openProcessEditor } from '../processes/editor.js'
import { openSkillEditor } from '../skills/editor.js'
import { editDocumentDraft } from './document-editor.js'

// Retain the request ID after an uncertain response; retry opens the same draft.
const attempts=new Map()
export async function beginEdit(kind,targetId,button) {
  const space=spaceId,user=identity?.user.id,route=location.hash,key=[space,user,kind,targetId].join(':')
  if(!attempts.has(key))attempts.set(key,crypto.randomUUID())
  if(button)button.disabled=true
  try {
    const row=await request('/api/reviews/edits',{method:'POST',body:{id:attempts.get(key),kind,targetId}})
    if(space!==spaceId||user!==identity?.user.id||route!==location.hash)return
    attempts.delete(key)
    editDraft(row,()=>{location.hash='#reviews'})
  } catch(error) {toast(error.message,true)}
  finally {if(button)button.disabled=false}
}

export function editDraft(row,afterSave) {
  if(row.kind==='processes')openProcessEditor(row.data,afterSave,{draft:row})
  else if(row.kind==='knowledge')editDocumentDraft(row,afterSave)
  else openSkillEditor({...row.data.skill,resources:row.data.resources.map(r=>({
    path:r.path,name:r.path.split('/').pop(),kind:r.path.split('/')[0],size:Math.floor(r.contentBase64.length*3/4)
  }))},afterSave,{draft:row})
}
