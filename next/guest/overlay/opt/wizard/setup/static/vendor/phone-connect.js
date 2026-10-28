/* Phone connect: the one "use Wizard on your phone" component (connect over Tailscale).
 *
 * Every place that connects a phone renders this, so the owner sees the same steps, words and dead ends everywhere:
 *   - Settings › Phones & devices (web/core/settings.js)
 *   - the Setup app's phone screen (web/setup/setup.js)
 *   - Mac onboarding's phone step (try-wizard, a vendored copy of this file; see the provenance note there)
 *
 * It renders the Agent Service's Phone Setup states (wizard-agent-service docs/phone-setup.md):
 *   unavailable → off → signin → https → serving → phone_seen
 * plus its own: checking, can't check, owner only, and "starting" between Connect and the sign-in link.
 *
 * Usage:  const pc = WizPhoneConnect.create({ api, open, layout, active, onChange }); pc.attach(element)
 *   api(action)        action is 'status' | 'start' | 'reset'; resolves { kind: 'ok'|'denied'|'missing'|'neterr', data }.
 *                      WizPhoneConnect.serviceApi() talks to /wizard/v1/setup/phone directly (same origin).
 *   open(url, kind)    opens a Tailscale page outside Wizard; resolves true/false when the host knows, else null.
 *                      Default: an ordinary target=_blank anchor (the shell's frame guard hands it to the browser).
 *   layout             'desktop' shows QR codes; 'phone' shows the address to open instead.
 *   active()           whether the component is on screen; it polls only then (and only while the page is visible).
 *   onChange(pc)       after every status change, for the host's own summary (a Continue button, a list).
 *   qrScript           URL of vendor/qrcode.js, loaded on first QR when window.qrcode isn't there yet.
 * The controller keeps its state across attach() calls, so a host that re-renders its own HTML just attaches again.
 * The DOM is only touched when the rendered HTML changes, so spinners don't restart on every poll.
 * Tailscale links are only ever https://tailscale.com or a subdomain. QR codes are drawn locally (window.qrcode). */
(() => {
  'use strict';
  const STEPS = new Set(['unavailable', 'off', 'signin', 'https', 'serving', 'phone_seen']);
  const ON = new Set(['serving', 'phone_seen']);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const str = v => (typeof v === 'string' && v ? v : '');

  /** Only Tailscale's own https pages are offered as sign-in or HTTPS links. */
  function tailscaleLink(value) {
    try {
      const u = new URL(str(value));
      return u.protocol === 'https:' && (u.hostname === 'tailscale.com' || u.hostname.endsWith('.tailscale.com')) && !u.username && !u.password ? u.href : '';
    } catch (e) { return ''; }
  }
  function httpsOrigin(value) {
    try { const u = new URL(str(value)); return u.protocol === 'https:' && u.host && !u.username && !u.password ? u.origin : ''; } catch (e) { return ''; }
  }
  /** What the Wizard phone apps (and the iPhone Camera) open: an origin, never credentials or a path. */
  function connectPayload(origin) {
    try {
      const u = new URL(origin);
      if (u.protocol !== 'https:' || u.username || u.password || u.pathname !== '/' || u.search || u.hash) return '';
      return 'wizard://connect?origin=' + encodeURIComponent(u.origin);
    } catch (e) { return ''; }
  }
  /** One shape from either the Service's view or a host's relay of it (Mac onboarding renames a few fields). */
  function norm(d) {
    if (!d || typeof d !== 'object' || !STEPS.has(d.step)) return null;
    let origin = httpsOrigin(d.wizard_url);
    if (!origin && str(d.connect_url)) { try { origin = httpsOrigin(new URL(d.connect_url).searchParams.get('origin')); } catch (e) {} }
    if (!origin && str(d.address)) origin = httpsOrigin('https://' + d.address);
    const phones = (Array.isArray(d.phones) ? d.phones : []).filter(p => p && typeof p === 'object')
      .map(p => ({ name: str(p.name) || 'Phone', os: str(p.os), online: p.online === true }));
    return {
      step: d.step,
      error: str(d.error) && d.error !== 'owner_not_recorded' ? d.error : '',
      signin: tailscaleLink(d.auth_url) || tailscaleLink(d.signin_url),
      https: tailscaleLink(d.https_enable_url) || tailscaleLink(d.https_url),
      // The name the Wizard joins the tailnet under, so the owner knows which new device to approve.
      device: (str(d.this_device) || str(d.device_name).split('.')[0] || 'wizard').slice(0, 64),
      origin, phones,
      install: tailscaleLink(d.install_url) || 'https://tailscale.com/download',
    };
  }
  const isPhone = p => /ios|android|ipados/i.test(p.os);
  const errText = code => ({
    tailscale_not_installed: 'This Wizard is missing Tailscale.',
    helper_error: 'Wizard couldn’t reach its private-network helper.',
    helper_forbidden: 'Wizard isn’t allowed to use its private-network helper.',
  })[code] || `Phone setup: ${String(code).replace(/_/g, ' ')}`;

  const REQUEST_MS = 8000;
  /** After this many failed checks in a row the last answer is no longer shown as current. */
  const LOST_AFTER = 2;

  /** The default API: the Agent Service's owner-only Phone Setup endpoints on this origin. */
  function serviceApi(base = '/wizard/v1/setup/phone') {
    const paths = { status: ['GET', base], start: ['POST', base + '/start'], reset: ['POST', base + '/reset'] };
    return async action => {
      const [method, path] = paths[action];
      // A Wizard this device can't reach (e.g. a phone removed from Tailscale) doesn't fail the request; it hangs.
      // Give up after a while so the screen can say so instead of keeping the last answer up.
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const timer = ctl ? setTimeout(() => ctl.abort(), REQUEST_MS) : 0;
      try {
        const r = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', ...(ctl ? { signal: ctl.signal } : {}),
          ...(method === 'POST' ? { headers: { 'content-type': 'application/json' }, body: '{}' } : {}) });
        if (r.status === 401 || r.status === 403) return { kind: 'denied' };
        if (r.status === 404) return { kind: 'missing' };
        if (!r.ok) return { kind: 'neterr' };
        const data = await r.json().catch(() => null);
        return data && typeof data === 'object' ? { kind: 'ok', data } : { kind: 'neterr' };
      } catch (e) { return { kind: 'neterr' }; } finally { clearTimeout(timer); }
    };
  }
  function openAnchor(url) {
    const a = document.createElement('a'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    document.body.appendChild(a); a.click(); a.remove();
    return Promise.resolve(null);
  }

  function create(options = {}) {
    const o = { api: serviceApi(), open: openAnchor, layout: 'desktop', active: () => true, onChange() {}, offline: () => false, ...options };
    const S = { status: 'loading', view: null, banner: false, starting: false, startUntil: 0, opErr: '', opened: {}, openFailed: false, again: false, busy: false };
    let el = null, timer = 0, seq = 0, lastHtml = '', at = 0, inflight = false;

    const changed = () => { try { o.onChange(api); } catch (e) { console.error(e); } };
    // Lost: Wizard hasn't answered the last checks, or the host already knows this device can't reach it (the
    // connection pill's evidence), then even one failed check is enough.
    const lost = () => !!S.view && ((S.fails || 0) >= LOST_AFTER || (S.offline && (S.fails || 0) >= 1));
    function take(r) {
      if (r.kind === 'ok' && norm(r.data)) { S.status = 'ok'; S.view = norm(r.data); S.raw = r.data; S.banner = false; S.fails = 0; }
      else if (r.kind === 'denied' || r.kind === 'missing') { S.status = r.kind; S.view = null; S.starting = false; S.fails = 0; }
      else { S.fails = (S.fails || 0) + 1; if (S.view) S.banner = true; else S.status = 'neterr'; }
      const v = S.view;
      if (S.starting && v && (v.step !== 'off' || v.error)) S.starting = false;
      if (S.starting && Date.now() > S.startUntil) { S.starting = false; S.opErr = 'That didn’t work. Try again.'; }
      // After Connect, open each Tailscale page once, as soon as the Wizard reports it.
      if (v && S.started) for (const kind of ['signin', 'https']) {
        const url = v.step === kind && v[kind];
        if (url && !S.opened[url]) { S.opened[url] = true; launch(url, kind); }
      }
    }
    async function load() {
      const n = ++seq;
      const r = await o.api('status');
      if (n !== seq) return;
      at = Date.now(); take(r); paint(); changed();
    }
    async function launch(url, kind) {
      let ok = null;
      try { ok = await o.open(url, kind); } catch (e) { ok = false; }
      S.openFailed = ok === false; paint();
    }

    /* ---------- polling: only while attached, active and visible ---------- */
    const live = () => !!el && el.isConnected && document.visibilityState === 'visible' && o.active() && !['denied', 'missing'].includes(S.status);
    function schedule(ms) {
      clearTimeout(timer); timer = 0;
      if (!live()) return;
      timer = setTimeout(async () => { timer = 0; if (!live()) return; await load(); schedule(interval()); }, ms);
    }
    const interval = () => S.starting ? 1000 : ['signin', 'https', 'serving'].includes(S.view?.step) || S.again ? 2000 : 10000;
    const kick = () => { if (live()) schedule(0); };
    document.addEventListener('visibilitychange', kick);
    addEventListener('focus', kick);

    /* ---------- actions ---------- */
    async function start() {
      if (S.starting) return;
      S.starting = true; S.started = true; S.opErr = ''; S.startUntil = Date.now() + 15000; paint();
      const r = await o.api('start'); seq++;
      if (r.kind === 'ok' || r.kind === 'denied' || r.kind === 'missing') take(r);
      else { S.starting = false; S.opErr = 'That didn’t work. Try again.'; }
      paint(); changed(); schedule(S.starting ? 1000 : 2000);
    }
    async function reset() {
      if (S.busy) return false;
      S.busy = true;
      const r = await o.api('reset'); seq++;
      S.busy = false;
      if (r.kind !== 'ok') { if (r.kind === 'denied' || r.kind === 'missing') take(r); paint(); changed(); return false; }
      S.opened = {}; S.started = false; S.opErr = ''; S.again = false;
      take(norm(r.data) ? r : { kind: 'ok', data: { step: 'off', phones: [] } });
      paint(); changed(); schedule(2000);
      return true;
    }
    async function copy(text, btn) {
      let ok = false;
      try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); ok = true; } } catch (e) {}
      if (!ok) { try { const t = document.createElement('textarea'); t.value = text; t.setAttribute('readonly', ''); t.style.cssText = 'position:fixed;opacity:0;top:0'; document.body.appendChild(t); t.select(); ok = document.execCommand('copy'); t.remove(); } catch (e) { ok = false; } }
      const label = btn.textContent; btn.textContent = ok ? 'Copied' : 'Select it'; setTimeout(() => { if (btn.isConnected) btn.textContent = label; }, 1800);
    }
    function onClick(e) {
      const t = e.target.closest('[data-pc]');
      if (!t || !el?.contains(t)) return;
      const act = t.dataset.pc;
      if (act === 'out') return; // an ordinary link: it leaves on its own
      e.preventDefault();
      if (act === 'start') start();
      else if (act === 'retry') { S.status = S.view ? S.status : 'loading'; paint(); load().then(() => schedule(interval())); }
      else if (act === 'open') { const url = S.view?.[t.dataset.kind]; if (url) { S.opened[url] = true; launch(url, t.dataset.kind); } }
      else if (act === 'copy') copy(t.dataset.text, t);
      else if (act === 'again') { S.again = !S.again; paint(); schedule(interval()); }
    }

    /* ---------- render ---------- */
    const spin = text => `<div class="pc-wait"><span class="pc-spin" aria-hidden="true"></span><span>${text}</span></div>`;
    const btn = (act, label, cls = 'primary', extra = '') => `<button type="button" class="pc-btn ${cls}" data-pc="${act}" ${extra}>${label}</button>`;
    const note = (html, cls = '') => `<p class="pc-note ${cls}">${html}</p>`;
    const shown = origin => { try { return new URL(origin).host; } catch (e) { return origin; } };
    const copyRow = (text, label, shownText = text) => `<div class="pc-copy"><span class="pc-copy-t" title="${esc(text)}">${esc(shownText)}</span><button type="button" class="pc-btn quiet small" data-pc="copy" data-text="${esc(text)}" aria-label="${esc(label)}">Copy</button></div>`;
    function manual(url) {
      return `<div class="pc-manual"><p class="pc-note small ${S.openFailed ? 'warn' : ''}">${S.openFailed ? 'Your browser didn’t open. Copy this link into it:' : 'Nothing opened? Copy this link into your browser:'}</p>${copyRow(url, 'Copy the Tailscale link')}</div>`;
    }
    function pair(v, waiting) {
      // Only while waiting for the first phone: a phone online on Tailscale still has to open Wizard. A hint, not a state.
      const phone = waiting && v.phones.find(p => p.online && isPhone(p));
      const tell = phone
        ? `<b>${esc(phone.name)}</b> is on your private network. One more step: open the Wizard app on it, tap <b>Scan QR code</b> and point it here.`
        : 'Open the Wizard app on your phone, tap <b>Scan QR code</b> and point it here. The iPhone Camera works too.';
      const wait = waiting ? spin('Waiting for your phone…') : '';
      const get = note(`Your phone needs Tailscale too, signed in to the same account. <a href="${esc(v.install)}" target="_blank" rel="noopener noreferrer" data-pc="out">Get Tailscale</a>`, 'small');
      const payload = connectPayload(v.origin);
      if (!payload) return spin('Getting your Wizard’s address…');
      if (o.layout === 'phone') {
        return note('On the phone you want to connect, open the Wizard app and enter this address, or open it in the browser.')
          + copyRow(v.origin, 'Copy your Wizard’s address', shown(v.origin))
          + `<div class="pc-act"><a class="pc-btn primary" href="${esc(v.origin)}" target="_blank" rel="noopener noreferrer" data-pc="out">Open Wizard at this address</a></div>` + wait + get;
      }
      return `<div class="pc-pair"><div class="pc-qr" data-qr="${esc(payload)}" role="img" aria-label="QR code to connect your phone to ${esc(shown(v.origin))}"><canvas></canvas></div>`
        + `<div class="pc-side">${note(tell)}${wait}</div></div>` + copyRow(v.origin, 'Copy your Wizard’s address', shown(v.origin)) + get;
    }
    function html() {
      const v = S.view;
      if (S.status === 'denied') return note('Only Wizard’s owner can connect a phone.');
      if (S.status === 'missing' || v?.step === 'unavailable') {
        return `<div class="pc-wall">${note('Phone access isn’t available on this Wizard yet. It comes with a Wizard update; there’s nothing you need to do now.')}</div>`;
      }
      if (!v) return S.status === 'neterr' ? note('Can’t check right now.') + `<div class="pc-act">${btn('retry', 'Try again', 'secondary')}</div>` : spin('Checking…');
      // The last answer is too old to show as current (e.g. "connected" on a phone that was just removed).
      if (lost()) return `<div class="pc-banner" role="status">Can’t reach your Wizard from this device right now.</div>`
        + note('So this can’t show whether a phone is connected. On a phone, check that Tailscale is on and signed in to the same account as your Wizard, and that the computer running your Wizard is on.')
        + `<div class="pc-act">${btn('retry', 'Try again', 'secondary')}</div>`;
      let h = S.banner ? '<div class="pc-banner" role="status">Wizard can’t check on this right now. Trying again.</div>' : '';
      const err = S.opErr || (v.error ? errText(v.error) : '');
      const errLine = err ? `<p class="pc-note err" role="alert">${esc(err)}</p>` : '';
      if (S.starting) return h + spin('Starting Tailscale…');
      if (v.step === 'off') {
        return h + note('Your Wizard joins <b>Tailscale</b>, a free private network, as its own device. Sign in to the same Tailscale account on your phone, and it can reach Wizard from anywhere. Nothing is opened to the internet.')
          + errLine + `<div class="pc-act">${btn('start', err ? 'Try again' : 'Connect a phone')}</div>`;
      }
      if (v.step === 'signin') {
        const again = S.opened[v.signin];
        return h + note(`Sign in to Tailscale in your browser, then approve the new device <b>${esc(v.device)}</b>. That’s your Wizard joining your private network; it’s separate from any Tailscale app on this computer.`)
          + errLine + `<div class="pc-act">${v.signin ? btn('open', again ? 'Open again' : 'Sign in to Tailscale', again ? 'secondary' : 'primary', 'data-kind="signin"') : btn('start', 'Open the sign-in page')}${spin('Waiting for approval…')}</div>`
          + (v.signin ? manual(v.signin) : '');
      }
      if (v.step === 'https') {
        const again = S.opened[v.https];
        return h + note('One more switch: your Tailscale network needs HTTPS certificates turned on, so your phone gets a secure address.')
          + errLine + (v.https ? `<div class="pc-act">${btn('open', again ? 'Open again' : 'Turn on HTTPS', again ? 'secondary' : 'primary', 'data-kind="https"')}${spin('Waiting…')}</div>` + manual(v.https)
            : `<div class="pc-act">${spin('Setting up the secure address…')}</div>`);
      }
      if (v.step === 'serving') return h + errLine + pair(v, true);
      // phone_seen
      const phone = v.phones.find(p => isPhone(p)) || v.phones[0];
      return h + `<div class="pc-ok"><span class="pc-check" aria-hidden="true">✓</span><span>${esc(phone ? phone.name : 'Your phone')} is connected</span></div>`
        + note('Open the Wizard app on your phone any time.') + errLine
        + `<div class="pc-act">${btn('again', S.again ? 'Hide the code' : 'Connect another phone', 'secondary', `aria-expanded="${S.again}"`)}</div>`
        + (S.again ? `<div class="pc-again">${pair(v, false)}</div>` : '');
    }
    // The QR library is loaded on first use when the host names it (the shells don't load it up front).
    let qrLoading = null;
    function drawQrs() {
      if (!el) return;
      if (typeof window.qrcode !== 'function') {
        if (o.qrScript && el.querySelector('.pc-qr') && !qrLoading) {
          qrLoading = new Promise(done => { const s = document.createElement('script'); s.src = o.qrScript; s.onload = s.onerror = done; document.head.appendChild(s); });
          qrLoading.then(() => { if (typeof window.qrcode === 'function') drawQrs(); else qrLoading = null; });
        }
        return;
      }
      const dpr = Math.max(1, Math.min(4, window.devicePixelRatio || 1));
      el.querySelectorAll('.pc-qr[data-qr]').forEach(box => {
        const c = box.querySelector('canvas'); if (!c || box.dataset.drawn === box.dataset.qr) return;
        const q = window.qrcode(0, 'M'); q.addData(box.dataset.qr); q.make();
        const n = q.getModuleCount(), quiet = 2, cells = n + quiet * 2;
        const cell = Math.max(1, Math.floor((136 * dpr) / cells)); // whole device pixels per module: crisp edges
        const px = cell * cells; c.width = px; c.height = px; c.style.width = c.style.height = (px / dpr) + 'px';
        const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, px, px); x.fillStyle = '#000';
        for (let r = 0; r < n; r++) for (let k = 0; k < n; k++) if (q.isDark(r, k)) x.fillRect((k + quiet) * cell, (r + quiet) * cell, cell, cell);
        box.dataset.drawn = box.dataset.qr;
      });
    }
    function paint() {
      if (!el || !el.isConnected) return;
      const h = html();
      if (h === lastHtml && el.dataset.pcPainted === '1') return;
      lastHtml = h; el.innerHTML = h; el.dataset.pcPainted = '1';
      drawQrs();
    }

    const api = {
      /** Render into `node` (a host re-render just attaches again) and start polling if it's on screen. */
      attach(node) {
        if (el && el !== node) el.removeEventListener('click', onClick);
        el = node || null; if (!el) { schedule(0); return api; }
        el.classList.add('pc'); el.setAttribute('aria-live', 'polite');
        el.addEventListener('click', onClick);
        lastHtml = ''; paint();
        if (!at || Date.now() - at > 2000) kick(); else schedule(interval());
        return api;
      },
      /** Ask now, unless the last answer is younger than `maxAge` ms. Works unattached (for a host's summary). */
      refresh(maxAge = 0) {
        // While the host knows this device can't reach Wizard, a cached answer is no evidence: always ask.
        S.offline = !!o.offline();
        if (S.offline && S.view && !S.fails) S.fails = 1;
        if (S.offline) { lastHtml = ''; paint(); changed(); }
        if (inflight || (!S.offline && maxAge && at && Date.now() - at < maxAge)) return;
        inflight = true; load().finally(() => { inflight = false; schedule(interval()); });
      },
      start, reset,
      /** 'loading' | 'ok' | 'neterr' | 'denied' | 'missing' */
      get status() { return S.status; },
      /** The normalized view (null until the first answer): step, device, origin, phones, ... */
      get view() { return S.view; },
      /** The last answer as the host's API gave it (for host-only fields, e.g. Mac onboarding's app links). */
      get raw() { return S.raw || null; },
      get busy() { return S.busy; },
      /** For hosts: on = a phone can reach Wizard; setting up = signed in halfway; available = Phone Setup exists here. */
      /** The last answer is stale: Wizard hasn't answered the last checks. Hosts hide what depends on it. */
      get lost() { return lost(); },
      get on() { return !lost() && !!S.view && ON.has(S.view.step); },
      get settingUp() { return !lost() && !!S.view && ['signin', 'https'].includes(S.view.step); },
      get available() { return S.status === 'ok' && !!S.view && S.view.step !== 'unavailable'; },
    };
    return api;
  }

  window.WizPhoneConnect = { create, serviceApi, norm, connectPayload, tailscaleLink, version: 1 };
})();
