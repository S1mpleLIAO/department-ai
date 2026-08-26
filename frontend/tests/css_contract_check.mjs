import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const frontendRoot = new URL('../', import.meta.url)
const [html, styles, premium] = await Promise.all([
  readFile(new URL('index.html', frontendRoot), 'utf8'),
  readFile(new URL('styles.css', frontendRoot), 'utf8'),
  readFile(new URL('premium.css', frontendRoot), 'utf8'),
])
const css = `${styles}\n${premium}`

assert.match(html, /\/department\/styles\.css/, 'HTML 应保留 styles.css 公共样式入口')
assert.match(html, /\/department\/premium\.css/, 'HTML 应保留 premium.css 覆盖样式入口')
assert.match(styles, /:root\s*\{/, 'styles.css 应保留基础 :root 设计令牌')
assert.match(css, /\.process-card \.step-card::before/, 'CSS 应保留流程时间线节点伪元素')
assert.match(css, /\.confirm-dialog/, 'CSS 应保留产品确认弹窗样式')
assert.match(css, /\.toast/, 'CSS 应保留 Toast 样式')
assert.match(css, /@media \(max-width: 1050px\)/, 'CSS 应保留 1050px 响应式断点')
assert.match(css, /@media \(max-width: 900px\)/, 'CSS 应保留 900px 响应式断点')
assert.match(css, /@media \(max-width: 620px\)/, 'CSS 应保留 620px 响应式断点')
assert.match(premium, /@media \(prefers-reduced-motion: reduce\)/, 'premium.css 应保留 reduced-motion 降级规则')

console.log('css-contract-check: ok')
