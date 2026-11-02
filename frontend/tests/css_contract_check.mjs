import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { JSDOM } from '../../../deepseek-harness/node_modules/jsdom/lib/api.js'

const frontendRoot = new URL('../', import.meta.url)
const [html, styles, tokens, base, layout, components, features, responsive, design] = await Promise.all([
  readFile(new URL('index.html', frontendRoot), 'utf8'),
  readFile(new URL('styles.css', frontendRoot), 'utf8'),
  readFile(new URL('css/tokens.css', frontendRoot), 'utf8'),
  readFile(new URL('css/base.css', frontendRoot), 'utf8'),
  readFile(new URL('css/layout.css', frontendRoot), 'utf8'),
  readFile(new URL('css/components.css', frontendRoot), 'utf8'),
  readFile(new URL('css/features.css', frontendRoot), 'utf8'),
  readFile(new URL('css/responsive.css', frontendRoot), 'utf8'),
  readFile(new URL('DESIGN.md', frontendRoot), 'utf8'),
])

function mediaBlocks(source, query) {
  const marker = `@media (max-width: ${query})`
  const blocks = []
  let searchFrom = 0
  while (true) {
    const start = source.indexOf(marker, searchFrom)
    if (start < 0) return blocks
    const open = source.indexOf('{', start + marker.length)
    assert.notEqual(open, -1, `${marker} 应有开始花括号`)
    let depth = 0
    let closed = false
    for (let index = open; index < source.length; index += 1) {
      if (source[index] === '{') depth += 1
      if (source[index] === '}') depth -= 1
      if (depth === 0) {
        blocks.push(source.slice(open + 1, index))
        searchFrom = index + 1
        closed = true
        break
      }
    }
    assert.ok(closed, `${marker} 应有结束花括号`)
  }
}

const narrowUpload = mediaBlocks(responsive, '620px').find(block => block.includes('.upload-stepper'))
const narrowBatch = mediaBlocks(responsive, '620px').find(block => block.includes('.batch-upload-row'))
const compactBatch = mediaBlocks(responsive, '900px').find(block => block.includes('.batch-upload-row'))
const narrowKnowledge = mediaBlocks(responsive, '620px').find(block => block.includes('.knowledge-system-views'))
const compactKnowledge = mediaBlocks(responsive, '1050px').find(block => block.includes('.document-list-scroll'))

const dialogDom = new JSDOM(html, { pretendToBeVisual: true })
const dialogStyle = dialogDom.window.document.createElement('style')
dialogStyle.textContent = components
dialogDom.window.document.head.append(dialogStyle)
const dialogShell = dialogDom.window.document.querySelector('.dialog-shell')
const dialogContent = dialogDom.window.document.querySelector('.dialog-content')
const shellStyles = dialogDom.window.getComputedStyle(dialogShell)
const contentStyles = dialogDom.window.getComputedStyle(dialogContent)

assert.equal(styles, [
  '@import url("./css/tokens.css");',
  '@import url("./css/base.css");',
  '@import url("./css/layout.css");',
  '@import url("./css/components.css");',
  '@import url("./css/features.css");',
  '@import url("./css/responsive.css");',
  '',
  '/* Public entry: CSS ownership lives in frontend/css/. */',
  '',
].join('\n'), 'styles.css 应只保留六个精确有序的 imports 与简短 ownership comment')
assert.equal((html.match(/<link\b[^>]*\brel="stylesheet"[^>]*>/g) || []).length, 1, 'HTML 应只保留一个 stylesheet 入口')
assert.match(html, /\/department\/styles\.css/, 'HTML 应保留 styles.css 公共样式入口')
assert.doesNotMatch(html, /\/department\/premium\.css/, 'HTML 不应再引用 premium.css')
await assert.rejects(readFile(new URL('premium.css', frontendRoot), 'utf8'), error => error?.code === 'ENOENT', 'premium.css 应已删除')
assert.match(tokens, /:root\s*\{/, 'tokens.css 应保留基础 :root 设计令牌')
assert.match(features, /\.process-card \.step-card::before/, 'features.css 应保留流程时间线节点伪元素')
assert.match(components, /\.confirm-dialog/, 'components.css 应保留产品确认弹窗样式')
assert.match(components, /\.toast/, 'components.css 应保留 Toast 样式')
assert.match(responsive, /@media \(max-width: 1200px\)/, 'responsive.css 应保留 1200px 响应式断点')
assert.match(responsive, /@media \(max-width: 1050px\)/, 'responsive.css 应保留 1050px 响应式断点')
assert.match(responsive, /@media \(max-width: 900px\)/, 'responsive.css 应保留 900px 响应式断点')
assert.match(responsive, /@media \(max-width: 620px\)/, 'responsive.css 应保留 620px 响应式断点')
assert.match(responsive, /@media \(prefers-reduced-motion: reduce\)/, 'responsive.css 应保留 reduced-motion 降级规则')
assert.match(features, /\.upload-stepper \.current\s*\{[^}]*color: var\(--brand\);/, '四步步骤条应包含当前状态')
assert.match(features, /\.upload-stepper \.completed\s*\{[^}]*color: var\(--ink\);/, '四步步骤条应包含已完成状态')
assert.match(features, /\.upload-stepper \.completed b\s*\{[^}]*color: var\(--brand\);[^}]*background: rgba\(0, 122, 255, \.1\);/, '已完成步骤应使用品牌蓝勾选底色')
assert.match(features, /\.upload-workflow \[data-upload-step\]\[hidden\]\s*\{\s*display: none;/, '隐藏的实际阶段节点应从布局中移除')
assert.match(features, /\[data-ai-suggested="true"\]\s*\{\s*border-color: rgba\(0, 122, 255, \.35\);/, 'AI 建议字段应有克制的蓝色描边')
assert.match(features, /#final-summary\s*\{[\s\S]*?background: rgba\(255, 255, 255, \.96\);/, '最终入库前的实际摘要节点应保持可读白色表面')
assert.match(features, /\.upload-workflow \.actions\s*\{[\s\S]*?justify-content: space-between;[\s\S]*?gap: 12px;/, '实际操作区应稳定分布按钮')
assert.doesNotMatch(features, /\.upload-stage\b|\.ai-suggested\b|\.upload-actions\b|\.upload-summary\b/, 'CSS 不应保留未被状态机消费的计划类名')
assert.ok(narrowUpload, '620px 媒体查询应包含知识入库窄屏规则')
assert.match(narrowUpload, /\.upload-stepper\s*\{[^}]*grid-template-columns: 1fr;/, '窄屏步骤条应改为单列')
assert.match(narrowUpload, /\.upload-stepper i\s*\{[^}]*display: none;/, '窄屏应隐藏步骤连接器')
assert.match(narrowUpload, /\.upload-workflow \.actions\s*\{[^}]*align-items: stretch;/, '窄屏实际操作区应占满交叉轴')
assert.match(narrowUpload, /\.upload-workflow \.actions\s*\{[^}]*flex-direction: column;/, '窄屏实际操作区应纵向堆叠')
assert.match(narrowUpload, /\.upload-workflow \.actions \.button\s*\{[^}]*width: 100%;/, '窄屏操作按钮应稳定占满可用宽度')
assert.match(design, /解析正文 → 确认属性 → 索引预览 → 最终入库/, '设计规范应记录四步知识入库流程')
for (const selector of ['knowledge-system-views', 'knowledge-system-view', 'knowledge-directory-heading']) {
  assert.ok(features.includes(`.${selector}`), `系统导航应定义 ${selector} 样式`)
}
assert.match(features, /\.knowledge-system-view\s*\{[^}]*min-width: 0;[^}]*overflow-wrap: anywhere;/, '系统按钮应允许长文本收缩换行')
assert.match(compactBatch || '', /\.batch-upload-row\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\);/, '900px 批量行应降为双列')
assert.match(narrowBatch || '', /\.inline-category-creator\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\);/, '620px 批量行和内联目录应降为单列')
assert.match(narrowKnowledge || '', /\.knowledge-system-views\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\);/, '窄屏系统导航应使用可收缩单列')
assert.match(features, /\.knowledge-layout\s*\{[^}]*height: calc\(100dvh - 164px\);[^}]*align-items: stretch;/, '桌面知识库应占满页面剩余高度')
assert.match(features, /\.category-panel\s*\{[^}]*grid-template-rows: auto auto auto minmax\(0, 1fr\);[^}]*overflow: hidden;/, '目录面板应固定标题并限制滚动范围')
assert.match(features, /\.category-tree\s*\{[^}]*overflow-y: auto;[^}]*overscroll-behavior: contain;/, '目录树应独立纵向滚动且不传递滚轮')
assert.match(features, /\.document-panel\s*\{[^}]*grid-template-rows: auto minmax\(0, 1fr\);[^}]*overflow: hidden;/, '文档面板应固定标题并限制滚动范围')
assert.match(features, /\.document-list-scroll\s*\{[^}]*overflow: auto;[^}]*overscroll-behavior: contain;/, '文档列表应独立滚动且不传递滚轮')
assert.match(features, /\.document-list-scroll \.data-table th\s*\{[^}]*position: sticky;[^}]*top: 0;/, '文档列表滚动时表头应保持可见')
assert.ok(compactKnowledge, '1050px 媒体查询应恢复知识库自然页面滚动')
assert.match(compactKnowledge || '', /\.knowledge-layout\s*\{[^}]*height: auto;/, '窄屏知识库不应继承桌面固定高度')
assert.match(compactKnowledge || '', /\.category-tree\s*\{[^}]*overflow: visible;/, '窄屏目录树应交还纵向滚动给页面')
assert.match(compactKnowledge || '', /\.document-list-scroll\s*\{[^}]*overflow-x: auto;[^}]*overflow-y: visible;/, '窄屏文档区仅保留必要的横向滚动')

assert.match(features, /\.batch-upload-state\s*\{[^}]*overflow-wrap: anywhere;/, '实际 AI 长标题与用途必须在状态列内换行，不得产生水平溢出')
assert.equal(shellStyles.display, 'grid', '弹窗外壳应固定头尾，只让正文区域滚动')
assert.equal(shellStyles.gridTemplateRows, 'auto minmax(0, 1fr) auto', '弹窗外壳应为固定头部、可收缩正文、固定底部三行')
assert.equal(contentStyles.minHeight, '0px', '弹窗正文必须允许在网格内收缩')
assert.equal(contentStyles.maxHeight, 'none', '弹窗正文高度应由外壳统一约束，避免双重限高')
assert.equal(contentStyles.overflowX, 'hidden', '弹窗正文不应产生第二条横向滚动条')
assert.equal(contentStyles.overflowY, 'auto', '弹窗正文应是唯一纵向滚动区域')
console.log('css-contract-check: ok')
