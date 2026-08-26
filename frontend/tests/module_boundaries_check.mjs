import assert from 'node:assert/strict'
import { readdir, readFile, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = fileURLToPath(new URL('../', import.meta.url))
const jsRoot = path.join(frontendRoot, 'js')
const featuresRoot = path.join(jsRoot, 'features')

function readString(source, start) {
  const quote = source[start]
  let value = ''
  let index = start + 1
  while (index < source.length) {
    const char = source[index]
    if (char === quote) return { token: { type: 'string', value }, end: index + 1 }
    if (char !== '\\') { value += char; index += 1; continue }
    const escaped = source[index + 1]
    if (escaped === '\n') { index += 2; continue }
    if (escaped === '\r' && source[index + 2] === '\n') { index += 3; continue }
    if (escaped === 'u') {
      const braced = source[index + 2] === '{'
      const close = braced ? source.indexOf('}', index + 3) : index + 6
      const digits = source.slice(index + (braced ? 3 : 2), close)
      if (/^[\da-f]+$/i.test(digits) && (braced || digits.length === 4)) {
        value += String.fromCodePoint(Number.parseInt(digits, 16))
        index = braced ? close + 1 : close
        continue
      }
    }
    if (escaped === 'x' && /^[\da-f]{2}$/i.test(source.slice(index + 2, index + 4))) {
      value += String.fromCodePoint(Number.parseInt(source.slice(index + 2, index + 4), 16))
      index += 4
      continue
    }
    value += ({ n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', v: '\v', 0: '\0' })[escaped] ?? escaped
    index += 2
  }
  throw new SyntaxError('Unterminated string literal')
}

function tokenize(source) {
  const tokens = []
  let index = 0
  while (index < source.length) {
    const char = source[index]
    if (/\s/.test(char)) { index += 1; continue }
    if (char === '/' && source[index + 1] === '/') {
      index = source.indexOf('\n', index + 2)
      if (index === -1) break
      continue
    }
    if (char === '/' && source[index + 1] === '*') {
      const close = source.indexOf('*/', index + 2)
      if (close === -1) throw new SyntaxError('Unterminated block comment')
      index = close + 2
      continue
    }
    const previous = tokens.at(-1)
    const regexStart = !previous
      || (previous.type === 'punct' && /[([{:,;=!?&|+*%^~<>-]/.test(previous.value))
      || (previous.type === 'word' && /^(?:return|case|throw|else|do|typeof|void|delete|yield|await)$/.test(previous.value))
    if (char === '/' && regexStart) {
      let escaped = false
      let characterClass = false
      index += 1
      while (index < source.length) {
        const regexChar = source[index]
        if (escaped) escaped = false
        else if (regexChar === '\\') escaped = true
        else if (regexChar === '[') characterClass = true
        else if (regexChar === ']') characterClass = false
        else if (regexChar === '/' && !characterClass) { index += 1; break }
        index += 1
      }
      while (/[A-Za-z]/.test(source[index] || '')) index += 1
      tokens.push({ type: 'regex', value: '' })
      continue
    }
    if (char === '"' || char === "'") {
      const parsed = readString(source, index)
      tokens.push(parsed.token)
      index = parsed.end
      continue
    }
    if (/[A-Za-z_$]/.test(char)) {
      const match = source.slice(index).match(/^[A-Za-z_$][\w$]*/)[0]
      tokens.push({ type: 'word', value: match })
      index += match.length
      continue
    }
    tokens.push({ type: 'punct', value: char })
    index += 1
  }
  return tokens
}

function moduleSpecifiers(source) {
  const tokens = tokenize(source)
  const specifiers = []
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index]
    if (token.type !== 'word' || (token.value !== 'import' && token.value !== 'export')) continue
    if (token.value === 'import' && tokens[index + 1]?.value === '.') continue
    if (token.value === 'import' && tokens[index + 1]?.value === '(') {
      if (tokens[index + 2]?.type === 'string') specifiers.push(tokens[index + 2].value)
      continue
    }
    if (token.value === 'import' && tokens[index + 1]?.type === 'string') {
      specifiers.push(tokens[index + 1].value)
      continue
    }
    for (let cursor = index + 1; cursor < tokens.length && tokens[cursor].value !== ';'; cursor += 1) {
      if (tokens[cursor].value === 'from' && tokens[cursor + 1]?.type === 'string') {
        specifiers.push(tokens[cursor + 1].value)
        break
      }
    }
  }
  return specifiers
}

function pointsToFeatures(specifier, importer) {
  const barePath = specifier.split(/[?#]/, 1)[0]
  if (barePath.startsWith('/')) return /(?:^|\/)js\/features(?:\/|$)/.test(path.posix.normalize(barePath))
  if (!barePath.startsWith('.')) return false
  let decoded = barePath
  try { decoded = decodeURIComponent(barePath) } catch (_) {}
  const resolved = path.resolve(path.dirname(importer), decoded)
  return resolved === featuresRoot || resolved.startsWith(`${featuresRoot}${path.sep}`)
}

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(entry => {
    const target = path.join(directory, entry.name)
    return entry.isDirectory() ? filesUnder(target) : target
  }))
  return files.flat().filter(file => /\.m?js$/.test(file))
}

const fixtureImporter = path.join(jsRoot, 'ui', 'nested', 'fixture.js')
const bypassFixture = String.raw`
  import/* split */('../../features/dashboard.js')
  export {
    renderSkills
  } from '../../f\u0065atures/skills/index.js'
  import value from '../../core/../features/settings.js'
`
assert.deepEqual(moduleSpecifiers(bypassFixture), [
  '../../features/dashboard.js',
  '../../features/skills/index.js',
  '../../core/../features/settings.js',
])
assert.ok(moduleSpecifiers(bypassFixture).every(specifier => pointsToFeatures(specifier, fixtureImporter)), '常见语法绕过仍应识别为 feature 依赖')
assert.equal(pointsToFeatures('../feedback.js', fixtureImporter), false, 'ui 同层依赖不应误报')
assert.deepEqual(moduleSpecifiers(`const example = "import('../features/fake.js')" // import '../features/fake.js'`), [], '字符串和注释不应伪造 import')

const violations = []
for (const directory of [path.join(jsRoot, 'core'), path.join(jsRoot, 'ui')]) {
  for (const file of await filesUnder(directory)) {
    const source = await readFile(file, 'utf8')
    for (const specifier of moduleSpecifiers(source)) {
      if (pointsToFeatures(specifier, file)) violations.push(`${path.relative(frontendRoot, file)} -> ${specifier}`)
    }
  }
}
assert.deepEqual(violations, [], `core/ui 不得导入 features:\n${violations.join('\n')}`)

const mainPath = path.join(jsRoot, 'main.js')
const appPath = path.join(frontendRoot, 'app.js')
assert.equal((await stat(mainPath)).isFile(), true, '最终入口 frontend/js/main.js 必须存在')
await assert.rejects(stat(appPath), { code: 'ENOENT' }, '旧入口 frontend/app.js 必须删除')

const [mainSource, html, domHelper] = await Promise.all([
  readFile(mainPath, 'utf8'),
  readFile(path.join(frontendRoot, 'index.html'), 'utf8'),
  readFile(path.join(frontendRoot, 'tests/helpers/dom.mjs'), 'utf8'),
])
const businessFunction = String.raw`(?:open\w*Editor|render(?:Knowledge|Processes|Skills|Settings))`
assert.doesNotMatch(mainSource, new RegExp(String.raw`\b(?:async\s+)?function\s+${businessFunction}\b|\b(?:const|let|var)\s+${businessFunction}\s*=`), 'main.js 不得声明业务函数')
assert.match(html, /<script\b(?=[^>]*\btype=["']module["'])(?=[^>]*\bsrc=["']\/department\/js\/main\.js(?:\?[^"']*)?["'])[^>]*><\/script>/, 'HTML 必须加载 /department/js/main.js')
assert.doesNotMatch(html, /\/department\/app\.js/, 'HTML 不得引用旧入口 app.js')
assert.match(domHelper, /new URL\(\s*["']js\/main\.js["']\s*,\s*root\s*\)/, 'JSDOM helper 必须导入 js/main.js')
assert.doesNotMatch(domHelper, /new URL\(\s*["']app\.js["']/, 'JSDOM helper 不得导入旧入口 app.js')

console.log('frontend-module-boundaries-check: ok')
