// Run: node --test next/tests/setup_auth_races.test.cjs
// Executes the actual onboarding JS in a minimal DOM, without human OAuth.
const { test } = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const { randomUUID } = require('node:crypto')
const html = fs.readFileSync(path.join(__dirname, '../guest/overlay/opt/wizard/setup/static/index.html'), 'utf8')
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1]
const flush = () => new Promise(resolve => setImmediate(resolve))
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function harness() {
  const elements = new Map(), timers = new Map(), storage = new Map()
  let nextTimer = 1
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, { textContent: '', innerHTML: '', disabled: false,
      classList: { add() {}, remove() {}, toggle() {} }, handlers: {},
      addEventListener(event, handler) { this.handlers[event] = handler } })
    return elements.get(selector)
  }
  const context = vm.createContext({ document: { querySelector: element, querySelectorAll: () => [] },
    sessionStorage: { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
    fetch: async () => ({ ok: true, json: async () => ({}) }), crypto: { randomUUID },
    setTimeout: f => { const id = nextTimer++; timers.set(id, f); return id }, clearTimeout: id => timers.delete(id), console })
  vm.runInContext(source, context)
  await flush()
  const calls = []
  context.request = async (url, opts = {}) => { calls.push({ url, ...opts }); return {} }
  vm.runInContext('api = (...args) => request(...args); brainKind = "chatgpt"; show = step => { shownStep = step };', context)
  const run = script => vm.runInContext(script, context)
  return { context, calls, elements, timers, storage, run }
}

test('Back before start response cancels exact attempt and never arms polling', async () => {
  const h = await harness(), started = deferred()
  h.context.request = async (url, opts) => { h.calls.push({ url, ...opts }); if (url.endsWith('/start')) return started.promise; return {} }
  const start = h.run('startCodex()')
  await flush()
  const attempt = JSON.parse(h.calls[0].body).attempt
  assert.match(attempt, /^[0-9a-f]{32}$/)
  const stop = h.run('stopCodex()')
  assert.equal(h.calls.length, 1)
  started.resolve({ attempt, status: 'starting' })
  await Promise.all([start, stop])
  assert.deepEqual(h.calls.map(c => c.url.split('/').pop()), ['start', 'cancel'])
  assert.equal(JSON.parse(h.calls[1].body).attempt, attempt)
  assert.equal(h.timers.size, 0)
  assert.equal(h.run('codexAttempt'), null)
})

test('rapid reselection waits for previous cancellation before a new start', async () => {
  const h = await harness(), cancelling = deferred()
  h.context.request = async (url, opts) => { h.calls.push({ url, ...opts }); if (url.endsWith('/cancel')) return cancelling.promise; return {} }
  await h.run('startCodex()')
  const old = h.run('codexAttempt')
  const next = h.run('startCodex()')
  await flush()
  assert.deepEqual(h.calls.map(c => c.url.split('/').pop()), ['start', 'cancel'])
  assert.equal(h.timers.size, 0)
  cancelling.resolve({ status: 'idle', attempt: old })
  await next
  assert.deepEqual(h.calls.map(c => c.url.split('/').pop()), ['start', 'cancel', 'start'])
  assert.notEqual(h.run('codexAttempt'), old)
  assert.equal(h.timers.size, 1)
})

test('old signed-in polling response cannot advance or overwrite a newer attempt', async () => {
  const h = await harness(), polling = deferred()
  await h.run('startCodex()')
  const old = h.run('codexAttempt'), generation = h.run('codexGeneration')
  h.context.request = async (url, opts) => { h.calls.push({ url, ...opts }); if (url.includes('?attempt=')) return polling.promise; return {} }
  const pending = h.run(`pollCodex(${JSON.stringify(old)}, ${generation})`)
  await flush()
  await h.run('startCodex()')
  const current = h.run('codexAttempt')
  polling.resolve({ status: 'signed-in', attempt: old })
  await pending
  assert.notEqual(current, old)
  assert.equal(h.run('codexAttempt'), current)
  assert.equal(h.run('typeof shownStep'), 'undefined')
  assert.equal(h.elements.get('#codexNote').textContent, 'Getting a sign-in code…')
})

test('failed cancellation preserves cleanup ID and blocks new start until retried', async () => {
  const h = await harness()
  await h.run('startCodex()')
  const old = h.run('codexAttempt')
  h.context.request = async (url, opts) => { h.calls.push({ url, ...opts }); throw new Error('offline') }
  await assert.rejects(h.run('startCodex()'), /offline/)
  assert.equal(h.run('codexAttempt'), old)
  assert.equal(h.storage.get('wizardCodexAttempt'), old)
  assert.deepEqual(h.calls.map(c => c.url.split('/').pop()), ['start', 'cancel'])
  h.context.request = async (url, opts) => { h.calls.push({ url, ...opts }); return {} }
  await h.run('startCodex()')
  assert.deepEqual(h.calls.map(c => c.url.split('/').pop()), ['start', 'cancel', 'cancel', 'start'])
})

test('late other-brain connect cannot advance UI after ChatGPT selection', async () => {
  const h = await harness(), connecting = deferred()
  h.run('brainKind = "free"')
  h.context.request = async (url, opts) => { h.calls.push({ url, ...opts }); if (url === '/api/brain') return connecting.promise; return {} }
  const connect = h.elements.get('#next2').handlers.click()
  await flush()
  h.run('brainKind = "chatgpt"')
  await h.run('startCodex()')
  connecting.resolve({ brain: { kind: 'free' } })
  await connect
  assert.equal(h.run('typeof shownStep'), 'undefined')
  assert.equal(h.run('brainKind'), 'chatgpt')
  assert.equal(h.run('state.brain'), undefined)
})

test('current signed-in result advances; mismatched attempt does not', async () => {
  const h = await harness()
  await h.run('startCodex()')
  h.timers.clear()
  h.context.request = async () => ({ status: 'signed-in', attempt: 'stale' })
  await h.run('pollCodex(codexAttempt, codexGeneration)')
  assert.equal(h.run('typeof shownStep'), 'undefined')
  h.context.request = async () => ({ status: 'signed-in', attempt: h.run('codexAttempt') })
  await h.run('pollCodex(codexAttempt, codexGeneration)')
  assert.equal(h.run('shownStep'), 3)
  assert.equal(h.timers.size, 0)
})

test('network polling failure schedules retry without claiming sign-in', async () => {
  const h = await harness()
  await h.run('startCodex()')
  h.timers.clear()
  h.context.request = async () => { throw new Error('offline') }
  await h.run('pollCodex(codexAttempt, codexGeneration)')
  assert.equal(h.timers.size, 1)
  assert.equal(h.run('typeof shownStep'), 'undefined')
  assert.match(h.elements.get('#codexNote').textContent, /Waiting/)
})
