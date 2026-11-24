import Foundation
#if canImport(CoreGraphics)
import CoreGraphics
#endif
import XCTest
@testable import WizardDragRegions

/// try-wizard#160: the Mac title-bar drag strip moves the window only from blank top-bar space.
final class DragRegionsTests: XCTestCase {
    typealias D = WizardDragRegions
    let view = CGSize(width: 1440, height: 900)
    // The AI apps view at 1440 px: #bar over the main area, the chat's Centred button in it.
    let regions = D.Regions(header: CGRect(x: 288, y: 0, width: 952, height: 44),
                            controls: [CGRect(x: 1076, y: 9, width: 26, height: 26)])

    func testBlankBarSpaceMovesTheWindowAndControlsDoNot() {
        XCTAssertTrue(D.drags(regions, at: CGPoint(x: 400, y: 20), pageZoom: 1, viewSize: view))
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 1089, y: 22), pageZoom: 1, viewSize: view))
        // a click on a control's very edge still reaches it
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 1075, y: 22), pageZoom: 1, viewSize: view))
        // below the bar and outside it: the page's
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 400, y: 60), pageZoom: 1, viewSize: view))
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 1300, y: 20), pageZoom: 1, viewSize: view))
    }

    func testPageZoomScalesTheReport() {
        // At 110% the Centred button is drawn at 1.1 times its CSS place: the click there reaches it.
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 1089 * 1.1, y: 22 * 1.1), pageZoom: 1.1, viewSize: view))
        // and the bar's blank space still drags at its zoomed place
        XCTAssertTrue(D.drags(regions, at: CGPoint(x: 400 * 1.1, y: 44 * 1.1 - 2), pageZoom: 1.1, viewSize: view))
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 400 * 0.8, y: 44 * 0.8 + 2), pageZoom: 0.8, viewSize: view))
        // a broken zoom counts as 100%
        XCTAssertFalse(D.drags(regions, at: CGPoint(x: 1089, y: 22), pageZoom: 0, viewSize: view))
    }

    func testWindowButtonsAreNeverTheStrips() {
        let whole = D.Regions(header: CGRect(x: 0, y: 0, width: 1440, height: 44), controls: [])
        XCTAssertFalse(D.drags(whole, at: CGPoint(x: 20, y: 14), pageZoom: 1, viewSize: view))
        XCTAssertFalse(D.drags(whole, at: CGPoint(x: 95, y: 31), pageZoom: 1, viewSize: view))
        XCTAssertTrue(D.drags(whole, at: CGPoint(x: 120, y: 14), pageZoom: 1, viewSize: view))
    }

    func testNoVisibleBarMeansNothingDrags() {
        // A full-screen chat: the page reports an empty bar, so every click goes to the page.
        let none = D.Regions(header: .zero, controls: [])
        for x in stride(from: 100.0, to: 1440.0, by: 50.0) {
            XCTAssertFalse(D.drags(none, at: CGPoint(x: x, y: 20), pageZoom: 1, viewSize: view))
        }
        // the bar's box is cut to the page
        let wide = D.Regions(header: CGRect(x: 0, y: 0, width: 3000, height: 44), controls: [])
        XCTAssertFalse(D.drags(wide, at: CGPoint(x: 1500, y: 20), pageZoom: 1, viewSize: view))
    }

    func testParseTakesOnlyATopStrip() {
        let ok = D.parse(["header": [0.0, 0.0, 1440.0, 34.0], "controls": [[10.0, 4.0, 20.0, 20.0], [1.0, 2.0], "x"]])
        XCTAssertEqual(ok?.header, CGRect(x: 0, y: 0, width: 1440, height: 34))
        XCTAssertEqual(ok?.controls, [CGRect(x: 10, y: 4, width: 20, height: 20)])
        XCTAssertEqual(D.parse(["header": [0.0, 0.0, 0.0, 0.0], "controls": [Any]()])?.header, .zero)
        XCTAssertNil(D.parse(["header": [0.0, 300.0, 1440.0, 34.0], "controls": [Any]()]), "not at the top")
        XCTAssertNil(D.parse(["header": [0.0, 0.0, 1440.0, 400.0], "controls": [Any]()]), "too tall")
        XCTAssertNil(D.parse(["header": [0.0, 0.0, Double.nan, 34.0], "controls": [Any]()]))
        XCTAssertNil(D.parse(["controls": [Any]()]))
        let many = (0..<500).map { [Double($0), 0, 1, 1] }
        XCTAssertEqual(D.parse(["header": [0.0, 0.0, 1440.0, 34.0], "controls": many])?.controls.count, D.maxControls)
    }

    func testTheScriptReportsControlsAnywhereInTheStrip() {
        let s = D.script
        XCTAssertTrue(s.contains("document.querySelectorAll(PAGE)"), "controls outside #bar are reported too")
        XCTAssertTrue(s.contains("getComputedStyle(bar).visibility === 'hidden'"), "a hidden bar reports no strip")
        XCTAssertTrue(s.contains("addEventListener('pointermove',near"), "reports again while the pointer is over the top rows")
        XCTAssertTrue(s.contains("own.observe(document.documentElement,{attributes:true})"), "follows the shell's layout attributes")
        XCTAssertTrue(s.contains("method:'chrome.regions'"))
    }
}
