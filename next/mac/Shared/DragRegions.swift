import Foundation
#if canImport(CoreGraphics)
import CoreGraphics
#endif

/// The Mac window's title-bar drag strip (try-wizard#160, earlier wizard-os#548). Wizard's own top bar sits where a
/// title bar would be, so a mouse-down on its blank space moves the window, and a mouse-down on anything the owner can
/// click there goes to the page. The page reports both in CSS px with `script` (message `chrome.regions`); the window
/// asks `drags(at:pageZoom:viewSize:)` for every mouse-down.
///
/// What #160 fixed: the old report listed only the controls inside `#bar`, so a chat's own header buttons over the bar
/// (Chats list, Centred, Side by side, Full screen, Back to tiled, close) and a full-screen chat's top buttons under a
/// hidden bar were taken as window drags; it was resent only on a change inside `#bar`, so it could be stale; and the
/// CSS px were used as view points, so with View › Zoom away from 100% every spot was off.
enum WizardDragRegions {
    /// At most this many control rectangles are kept from one report.
    static let maxControls = 200
    /// A control's spot is this much larger on each side (a click on its edge still reaches it).
    static let controlSlop: CGFloat = 2

    struct Regions: Equatable {
        /// The top bar's box in CSS px; empty when the page has no visible bar (full screen): nothing drags then.
        var header: CGRect = .zero
        /// Every control in the bar's box, in CSS px.
        var controls: [CGRect] = []
    }

    /// The window's own buttons (close, minimise, zoom) and their hover target, in view points: never the strip's.
    static func inWindowButtons(_ point: CGPoint) -> Bool { point.x < 96 && point.y < 32 }

    /// Reads one `chrome.regions` report. Nil when it is not a report of a strip at the top of the page.
    static func parse(_ params: [String: Any]) -> Regions? {
        func rect(_ any: Any?) -> CGRect? {
            guard let v = any as? [Double], v.count == 4, v.allSatisfy({ $0.isFinite }), v[2] >= 0, v[3] >= 0 else { return nil }
            return CGRect(x: v[0], y: v[1], width: v[2], height: v[3])
        }
        guard let header = rect(params["header"]), let list = params["controls"] as? [Any] else { return nil }
        // Only the top header may move the window, never the desktop or a composer.
        guard header.minY >= 0, header.minY < 2, header.height <= 100 else { return nil }
        return Regions(header: header, controls: list.prefix(maxControls).compactMap(rect))
    }

    /// True when a mouse-down at `point` (view points, origin top left) should move the window. The page's CSS px are
    /// view points divided by the page zoom.
    static func drags(_ regions: Regions, at point: CGPoint, pageZoom: CGFloat, viewSize: CGSize) -> Bool {
        if inWindowButtons(point) { return false }
        let zoom = pageZoom > 0 && pageZoom.isFinite ? pageZoom : 1
        let p = CGPoint(x: point.x / zoom, y: point.y / zoom)
        let page = CGRect(x: 0, y: 0, width: viewSize.width / zoom, height: viewSize.height / zoom)
        let header = regions.header.intersection(page)
        guard !header.isNull, header.width > 0, header.height > 0, header.contains(p) else { return false }
        return !regions.controls.contains { $0.insetBy(dx: -controlSlop, dy: -controlSlop).contains(p) }
    }

    /// Injected at document start in the main frame. Reports the bar's box and every visible control that reaches into
    /// it, anywhere on the page; reports again whenever the pointer is over the top rows (it always moves there before
    /// it clicks), after the page's own layout state changes, and on resize, scroll, fonts and finished animations.
    static let script = """
    (() => {
      let pending = false, band = 0, last = 0, trail = 0;
      const rect = e => { const r=e.getBoundingClientRect(); return [r.x,r.y,r.width,r.height]; };
      const OWN = 'button,a,input,select,textarea,summary,[role="button"],[tabindex],[contenteditable],[data-ws],#voicePill';
      const PAGE = 'button,a[href],input,select,textarea,summary,label,iframe,[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="checkbox"],[role="switch"],[role="option"],[contenteditable]:not([contenteditable="false"]),[tabindex]:not([tabindex="-1"]),[onclick]';
      const update = () => {
        pending=false;
        const bar=document.querySelector('header#bar.bar');
        const hidden = bar && (!bar.getClientRects().length || getComputedStyle(bar).visibility === 'hidden');
        const header = !bar ? [0,0,innerWidth,28] : hidden ? [0,0,0,0] : rect(bar);
        const [hx,hy,hw,hh]=header, bottom=hy+hh, right=hx+hw, controls=[];
        band = bottom;
        if (hw > 0 && hh > 0) {
          const reaches = r => r.width > 0 && r.height > 0 && r.top < bottom && r.bottom > hy && r.left < right && r.right > hx;
          if (bar) for (const e of document.querySelectorAll(PAGE)) {
            if (bar.contains(e) || controls.length >= 150) continue;
            const r=e.getBoundingClientRect();
            if (reaches(r) && getComputedStyle(e).visibility !== 'hidden') controls.push([r.x,r.y,r.width,r.height]);
          }
          for (const e of (bar || document).querySelectorAll(OWN))
            if (e.getClientRects().length && e.getBoundingClientRect().top < bottom) controls.push(rect(e));
        }
        window.webkit.messageHandlers.wizardNative.postMessage({method:'chrome.regions',params:{header,controls}});
      };
      // RAF can be suspended while the native window is occluded/headless.
      // Geometry is an input contract and must not depend on compositor frames.
      const schedule = () => { if (!pending) { pending=true; setTimeout(update,0); } };
      // The pointer reaches a button before it clicks it: report again while it moves over the top rows (at most every
      // 60 ms, and once more after it stops), so a layout change nobody announced is never older than that.
      const near = e => {
        if (band && e.clientY > band + 8) return;
        const now = Date.now();
        if (now - last >= 60) { last = now; schedule(); return; }
        clearTimeout(trail); trail = setTimeout(() => { last = Date.now(); schedule(); }, 60);
      };
      addEventListener('DOMContentLoaded', () => {
        const bar=document.querySelector('header#bar.bar');
        if (bar) new MutationObserver(schedule).observe(bar,{subtree:true,childList:true,attributes:true});
        // The shell switches its layouts (full screen, sidebar, arrangement) with attributes on <html> and <body>.
        const own = new MutationObserver(schedule);
        own.observe(document.documentElement,{attributes:true});
        if (document.body) own.observe(document.body,{attributes:true,childList:true});
        const ro = new ResizeObserver(schedule);
        ro.observe(document.documentElement); if (bar) ro.observe(bar);
        document.fonts.ready.then(schedule);
        schedule();
      }, {once:true});
      addEventListener('resize',schedule); addEventListener('scroll',schedule,true);
      addEventListener('pointermove',near,{capture:true,passive:true});
      for (const t of ['transitionend','animationend']) addEventListener(t,schedule,true);
      addEventListener('focus',schedule); document.addEventListener('visibilitychange',schedule);
    })();
    """
}
