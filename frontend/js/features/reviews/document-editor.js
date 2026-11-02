import { $, $$ } from '../../core/dom.js'
import { request } from '../../core/http.js'
import { state } from '../../core/state.js'
import { openDialog } from '../../ui/dialog.js'
import { metadataFormHtml,collectMetadata,togglePurposeFields,validateMetadata } from '../knowledge/upload-metadata.js'
import { categoryOptions } from '../knowledge/categories.js'
import { renderChunkPreview,collectPreviewChunks } from '../knowledge/upload-chunks.js'

export function editDocumentDraft(row,afterSave) {
  const data=row.data, m=data.metadata
  openDialog('修改文档草稿',row.targetId?'审核发布前继续使用正式版本。保留原文件，只按实际改动更新索引。':'修改后需要重新提交审核，原始文件保留。发布时才建立向量索引。',
    metadataFormHtml({documentId:m.id||data.resourceId,categoryOptionsHtml:categoryOptions(m.categoryId),purposes:state.purposes})+
    '<span id="preview-button" hidden></span><div id="chunk-fields"><h3>确认分块</h3><div id="chunk-preview"></div></div>',
    async()=>{
      const invalid=validateMetadata(state.purposes)
      if(invalid){invalid.focus();throw new Error('请填写文档标题、用途及需要的模板家族')}
      const metadata={...collectMetadata(m.outline||[]),chunks:collectPreviewChunks()}
      metadata.categoryId=metadata.categoryId||null
      await request('/api/reviews/'+row.id,{method:'PUT',body:{revision:row.revision,data:metadata}})
    },{wide:true,guardChanges:true,saveLabel:'保存草稿',successMessage:'草稿已更新，请重新提交审核',afterSave})
  const fields={'document-title':m.title,'document-purpose':m.purposeId,'document-type':m.documentType,
    'document-category':m.categoryId||'','document-status':'effective','document-keywords':(m.keywords||[]).join('、'),
    'document-summary':m.summary,'template-family':m.templateFamily,'template-variant':m.templateVariant,
    'template-version':m.version,'template-scenario':m.applicableScenario}
  for(const [id,value] of Object.entries(fields))$('#'+id).value=value||''
  $('#document-id').readOnly=true
  $('#document-status').closest('.field').hidden=true
  $('#upload-category-create').hidden=true
  const chunks=m.chunks?.length?m.chunks:[{content:data.parsedText,enabled:true,parentIndex:null,sectionPath:'正文'}]
  renderChunkPreview(chunks.map((c,index)=>({...c,index,tokenCount:c.tokenCount||0})))
  $$('.chunk-content').forEach(input=>input.setAttribute('aria-label','分块正文'))
  $('#document-purpose').onchange=()=>togglePurposeFields(state.purposes)
  togglePurposeFields(state.purposes)
}
