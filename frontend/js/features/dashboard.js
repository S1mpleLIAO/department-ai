import { $ } from '../core/dom.js'
import { state } from '../core/state.js'
import { pageAllowed } from '../core/session.js'
import { serviceBadge } from '../ui/feedback.js'

const content = $('#content')

export function renderDashboard() {
  const steps = state.processes.reduce((sum, process) => sum + process.steps.length, 0)
  const templates = state.documents.filter(item => item.isGenerationTemplate && item.status === 'effective').length
  const indexed = state.documents.filter(item => item.indexed).length
  content.innerHTML = `
    <div class="hero">
      <div><span class="hero-eyebrow">部门任务入口</span><h2>让 AI 先查真实模板，再开始生成</h2><p>业务要求定义在流程步骤中；合同、方案和历史文件进入知识库。AI 只会推荐知识库中实际存在的模板和变体。</p></div>
      ${pageAllowed('assistant') ? '<a class="button" href="#assistant">打开个人 AI 助手</a>' : '<p class="identity-stage-note">AI 入口由管理员按空间授权</p>'}
    </div>
    <div class="stats">
      <div class="stat-card"><span>业务流程</span><strong>${state.processes.length}</strong></div>
      <div class="stat-card"><span>流程步骤</span><strong>${steps}</strong></div>
      <div class="stat-card"><span>有效生成模板</span><strong>${templates}</strong></div>
      <div class="stat-card"><span>已建立索引文档</span><strong>${indexed}</strong></div>
    </div>
    <div class="service-strip">
      <b>服务状态</b>
      ${serviceBadge(state.services.database, state.services.database ? 'PostgreSQL / pgvector：可用' : 'PostgreSQL / pgvector：不可用')}
      ${serviceBadge(state.services.docling, state.services.docling ? 'Docling：可用' : 'Docling：不可用')}
      ${serviceBadge(state.services.siliconflow, state.services.siliconflow ? 'Embedding / Rerank：已配置' : 'Embedding / Rerank：未配置')}
      ${serviceBadge(state.services.metadata, state.services.metadata ? 'AI 元数据分析：已配置' : 'AI 元数据分析：未配置')}
      <span class="tag">${pageAllowed('assistant') ? '个人 AI：可按需启动' : '个人 AI：未授权或未配置'}</span>
    </div>
    <p class="identity-stage-note">模型“已配置”表示已填写连接信息，实际可用性以分析、入库和检索结果为准。</p>
    <div class="section-heading"><div><h2>下一步</h2><p>先配置标准，再交给 AI 使用</p></div></div>
    <div class="quick-grid">
      <a href="#processes" class="quick-card"><b>维护业务流程</b><span>定义每一步需要什么、完成什么、做到什么程度。</span></a>
      <a href="#knowledge" class="quick-card"><b>上传知识与模板</b><span>解析文档、预览分块，并标记模板家族、变体和版本。</span></a>
      <a href="#settings" class="quick-card"><b>调整检索设置</b><span>设置分块大小、召回数量、重排序数量和模板推荐数。</span></a>
    </div>`
  content.querySelectorAll('a[href^="#"]').forEach(link=>{link.hidden=!pageAllowed(link.hash.slice(1))})
}
