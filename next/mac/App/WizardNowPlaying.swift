import AppKit
import MediaPlayer
import WebKit

/// Now Playing and the media keys for Music and Podcasts (try-wizard#142). Off unless the `NowPlaying` switch is on
/// (enum WizardNowPlaying in main.swift). The page script below runs only in a Music or Podcasts frame: it reads the
/// app's own `navigator.mediaSession` metadata and action handlers plus the audio element that plays, and reports a
/// small state object. This class shows the owner's latest player in Control Center (title, artist/show, artwork,
/// progress) and routes play/pause, skip back 15 / forward 30 (Podcasts) or next/previous (Music) and scrubbing back
/// to that frame. Which frame may report, and what it may say, is decided in Shared/NowPlaying.swift.
final class WizardNowPlayingCenter: NSObject, WKScriptMessageHandler {
    static let name = "wizardNowPlaying"
    static let shared = WizardNowPlayingCenter()
    typealias Rule = WizardNowPlayingRule

    weak var owner: WizardWindowController?

    /// The one exception to "main frame only" (Tests/test_native_bridge_frames.py): Music and Podcasts run in the
    /// shell's app frames, so this script goes to every frame and stays idle outside those two apps. Its own handler
    /// name carries no other native power, and the receiver below admits a frame only through Shared/NowPlaying.swift.
    static func install(into controller: WKUserContentController) {
        controller.add(shared, name: name)
        controller.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: false))
    }
    /// The app now shown in Now Playing (nil: nothing shown).
    private(set) var activeApp: String?
    private var frames: [String: WKFrameInfo] = [:]
    private var states: [String: Rule.State] = [:]
    private var targets: [(MPRemoteCommand, Any)] = []
    private var commandsApp: String?
    private var artworkURL: URL?
    private var artwork: MPMediaItemArtwork?
    private var artworkLoading: URL?

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard WizardNowPlaying.isOn, let owner, let web = message.webView, owner.web === web,
              let body = message.body as? [String: Any], let state = Rule.State(body),
              let url = message.frameInfo.request.url,
              let appId = Rule.admit(switchOn: true, trustedShell: owner.isTrustedDocument,
                                     wizardAddress: owner.isWizardAppAddress(message.frameInfo.securityOrigin),
                                     path: url.path) else { return }
        activeApp = Rule.owner(current: activeApp, report: appId, playing: state.playing, gone: state.gone)
        if state.gone {
            states[appId] = nil; frames[appId] = nil
        } else {
            states[appId] = state; frames[appId] = message.frameInfo
        }
        publish()
    }

    /// A new main document (reload, other backend): every app frame is gone with it.
    func reset() {
        guard activeApp != nil || !states.isEmpty else { return }
        activeApp = nil; states = [:]; frames = [:]
        publish()
    }

    private func publish() {
        let center = MPNowPlayingInfoCenter.default()
        guard let app = activeApp, let s = states[app] else {
            center.nowPlayingInfo = nil
            center.playbackState = .stopped
            setCommands(for: nil)
            return
        }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: s.title.isEmpty ? Rule.fallbackTitle(app) : s.title,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: s.position,
            MPNowPlayingInfoPropertyPlaybackRate: s.playing ? s.rate : 0.0,
            MPNowPlayingInfoPropertyMediaType: MPNowPlayingInfoMediaType.audio.rawValue,
        ]
        if !s.artist.isEmpty { info[MPMediaItemPropertyArtist] = s.artist }
        if !s.album.isEmpty { info[MPMediaItemPropertyAlbumTitle] = s.album }
        if s.duration > 0 { info[MPMediaItemPropertyPlaybackDuration] = s.duration }
        if let art = s.artwork {
            if art == artworkURL { if let artwork { info[MPMediaItemPropertyArtwork] = artwork } } else { loadArtwork(art) }
        }
        center.nowPlayingInfo = info
        center.playbackState = s.playing ? .playing : .paused
        setCommands(for: app)
    }

    private func loadArtwork(_ url: URL) {
        guard artworkLoading != url else { return }
        artworkLoading = url
        var request = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 10)
        request.httpShouldHandleCookies = false
        URLSession.shared.dataTask(with: request) { data, _, _ in
            let image = data.flatMap { $0.count <= Rule.maxArtworkBytes ? NSImage(data: $0) : nil }
            DispatchQueue.main.async { [weak self] in
                guard let self, self.artworkLoading == url else { return }
                self.artworkLoading = nil
                // A failed download is remembered too, so a broken address is not fetched on every report.
                self.artworkURL = url
                self.artwork = image.map { img in MPMediaItemArtwork(boundsSize: img.size) { _ in img } }
                self.publish()
            }
        }.resume()
    }

    private func setCommands(for app: String?) {
        guard app != commandsApp else { return }
        let cc = MPRemoteCommandCenter.shared()
        for (command, target) in targets { command.removeTarget(target) }
        targets = []
        let all: [MPRemoteCommand] = [cc.playCommand, cc.pauseCommand, cc.togglePlayPauseCommand, cc.nextTrackCommand,
                                      cc.previousTrackCommand, cc.skipBackwardCommand, cc.skipForwardCommand,
                                      cc.changePlaybackPositionCommand]
        all.forEach { $0.isEnabled = false }
        commandsApp = app
        guard let app else { return }
        for command in Rule.commands(for: app) {
            let remote: MPRemoteCommand
            switch command {
            case .play: remote = cc.playCommand
            case .pause: remote = cc.pauseCommand
            case .toggle: remote = cc.togglePlayPauseCommand
            case .next: remote = cc.nextTrackCommand
            case .previous: remote = cc.previousTrackCommand
            case .skipBack:
                cc.skipBackwardCommand.preferredIntervals = [NSNumber(value: Rule.skipBackSeconds)]
                remote = cc.skipBackwardCommand
            case .skipForward:
                cc.skipForwardCommand.preferredIntervals = [NSNumber(value: Rule.skipForwardSeconds)]
                remote = cc.skipForwardCommand
            case .seek: remote = cc.changePlaybackPositionCommand
            }
            remote.isEnabled = true
            let target = remote.addTarget { [weak self] event in
                var value: Double?
                if let e = event as? MPChangePlaybackPositionCommandEvent { value = e.positionTime }
                if let e = event as? MPSkipIntervalCommandEvent { value = e.interval }
                DispatchQueue.main.async { self?.send(command, value: value, to: app) }
                return .success
            }
            targets.append((remote, target))
        }
    }

    /// Hands a media key / Control Center press to the playing app's own frame (its media session handler, else its
    /// audio element). Never to any other frame.
    private func send(_ command: Rule.Command, value: Double?, to app: String) {
        guard WizardNowPlaying.isOn, activeApp == app, let frame = frames[app], let web = owner?.web,
              owner?.isTrustedDocument == true else { return }
        web.evaluateJavaScript(Rule.script(command, value: value), in: frame, in: .page) { _ in }
    }

    /// Wizard was brought forward (Now Playing clicked, or the Dock icon) while Music or Podcasts holds Now Playing:
    /// show that app.
    func openPlayingApp() {
        guard WizardNowPlaying.isOn, let app = activeApp, let script = Rule.openScript(app),
              let owner, owner.isTrustedDocument else { return }
        owner.web.evaluateJavaScript(script)
    }

    /// Runs at document start in every frame; does nothing outside a Music or Podcasts page.
    static let script = """
    (() => {
      if (window.__wizardNowPlaying) return;
      if (!/^\\/(?:apps\\/)?(?:wizard-music|wizard-podcasts)(?:\\/|$)/.test(location.pathname)) return;
      const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.wizardNowPlaying;
      if (!handler) return;
      const handlers = {};
      let current = null, timer = null, last = '', beat = null;
      const seen = new WeakSet();
      // A WebKit without Media Session still gets the app's metadata and buttons.
      if (!('mediaSession' in navigator)) {
        try {
          if (!window.MediaMetadata) window.MediaMetadata = class { constructor(m = {}) { Object.assign(this, {title: '', artist: '', album: '', artwork: []}, m); } };
          const session = {metadata: null, playbackState: 'none', setActionHandler(a, fn) { handlers[a] = fn || null; }, setPositionState() {}};
          Object.defineProperty(navigator, 'mediaSession', {value: session, configurable: true});
        } catch (_) {}
      }
      const ms = navigator.mediaSession;
      const proto = window.MediaSession && window.MediaSession.prototype;
      if (proto && proto.setActionHandler) {
        const orig = proto.setActionHandler;
        proto.setActionHandler = function (action, fn) {
          handlers[action] = fn || null; schedule();
          try { return orig.call(this, action, fn); } catch (_) {}
        };
        const d = Object.getOwnPropertyDescriptor(proto, 'metadata');
        if (d && d.set && d.configurable) Object.defineProperty(proto, 'metadata', {configurable: true, enumerable: d.enumerable,
          get() { return d.get.call(this); }, set(v) { d.set.call(this, v); schedule(); }});
      }
      const meta = () => { try { return (ms && ms.metadata) || null; } catch (_) { return null; } };
      const artwork = m => {
        const list = m && m.artwork ? [...m.artwork] : [];
        const size = a => Math.max(0, ...String(a.sizes || '').split(/\\s+/).map(s => parseInt(s, 10) || 0));
        list.sort((a, b) => size(b) - size(a));
        try { return list[0] && list[0].src ? new URL(list[0].src, location.href).href : ''; } catch (_) { return ''; }
      };
      const state = () => {
        const el = current, m = meta();
        const n = x => (typeof x === 'number' && isFinite(x) ? x : 0);
        return {v: 1, playing: !!el && !el.paused && !el.ended, title: String((m && m.title) || ''), artist: String((m && m.artist) || ''),
          album: String((m && m.album) || ''), artwork: artwork(m), duration: el ? n(el.duration) : 0,
          position: el ? n(el.currentTime) : 0, rate: el ? n(el.playbackRate) || 1 : 1};
      };
      const post = force => {
        timer = null;
        const s = state(), text = JSON.stringify(s);
        if (!force && text === last) return;
        last = text;
        try { handler.postMessage(s); } catch (_) {}
        // While playing, a slow beat keeps the Mac's progress bar on the page's clock.
        if (s.playing && !beat) beat = setInterval(() => post(false), 15000);
        if (!s.playing && beat) { clearInterval(beat); beat = null; }
      };
      function schedule() { if (!timer) timer = setTimeout(() => post(false), 60); }
      const EVENTS = ['play', 'playing', 'pause', 'ended', 'seeked', 'ratechange', 'durationchange', 'loadedmetadata', 'emptied'];
      const watch = el => {
        if (!(el instanceof HTMLMediaElement) || seen.has(el)) return;
        seen.add(el);
        EVENTS.forEach(t => el.addEventListener(t, () => { if (t === 'play' || t === 'playing') current = el; schedule(); }));
      };
      const play = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function () { watch(this); current = this; schedule(); return play.apply(this, arguments); };
      document.addEventListener('play', e => { watch(e.target); current = e.target; schedule(); }, true);
      addEventListener('pagehide', () => { try { handler.postMessage({v: 1, gone: true}); } catch (_) {} last = ''; });
      addEventListener('pageshow', e => { if (e.persisted) post(true); });
      const call = (action, details) => {
        const fn = handlers[action];
        if (typeof fn !== 'function') return false;
        try { fn(Object.assign({action}, details || {})); } catch (_) {}
        return true;
      };
      const resume = el => { if (el) { const p = el.play(); if (p && p.catch) p.catch(() => {}); } };
      window.__wizardNowPlaying = Object.freeze({command(name, value) {
        const el = current;
        switch (name) {
          case 'play': call('play') || resume(el); break;
          case 'pause': call('pause') || (el && el.pause()); break;
          case 'toggle': if (el && !el.paused) { call('pause') || el.pause(); } else { call('play') || resume(el); } break;
          case 'next': call('nexttrack'); break;
          case 'previous': call('previoustrack'); break;
          case 'skipBack': call('seekbackward', {seekOffset: value}) || (el && (el.currentTime = Math.max(0, el.currentTime - value))); break;
          case 'skipForward': call('seekforward', {seekOffset: value}) || (el && (el.currentTime = el.currentTime + value)); break;
          case 'seek': call('seekto', {seekTime: value}) || (el && (el.currentTime = value)); break;
          default: return false;
        }
        schedule();
        return true;
      }});
    })();
    """
}
