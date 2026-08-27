import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

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
assert.match(features, /\.upload-stepper \.(?:current|completed)/, '四步步骤条应包含当前和已完成状态')
assert.match(features, /\.upload-workflow \[data-upload-step\]\[hidden\]\s*\{\s*display: none;/, '隐藏的实际阶段节点应从布局中移除')
assert.match(features, /\[data-ai-suggested="true"\]\s*\{\s*border-color: rgba\(0, 122, 255, \.35\);/, 'AI 建议字段应有克制的蓝色描边')
assert.match(features, /#final-summary\s*\{[\s\S]*?background: rgba\(255, 255, 255, \.96\);/, '最终入库前的实际摘要节点应保持可读白色表面')
assert.match(features, /\.upload-workflow \.actions\s*\{[\s\S]*?justify-content: space-between;[\s\S]*?gap: 12px;/, '实际操作区应稳定分布按钮')
assert.doesNotMatch(features, /\.upload-stage\b|\.ai-suggested\b|\.upload-actions\b|\.upload-summary\b/, 'CSS 不应保留未被状态机消费的计划类名')
assert.match(responsive, /@media \(max-width: 620px\)\s*\{[\s\S]*?\.upload-stepper\s*\{[\s\S]*?grid-template-columns: 1fr;[\s\S]*?\.upload-stepper i\s*\{[\s\S]*?display: none;[\s\S]*?\.upload-workflow \.actions\s*\{[\s\S]*?flex-direction: column;/, '窄屏应单列步骤、隐藏连接器并堆叠实际操作区')
assert.match(design, /解析正文 → 确认属性 → 索引预览 → 最终入库/, '设计规范应记录四步知识入库流程')

console.log('css-contract-check: ok')
