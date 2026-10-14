import AppKit

/// Exact supplied designer hat; never reconstruct the brand with a glyph or SF Symbol.
enum WizardBrand {
    static func image(_ name: String = "wizard-mark-purple", template: Bool = false) -> NSImage {
        guard let url = Bundle.main.url(forResource: name, withExtension: "png"),
              let image = NSImage(contentsOf: url) else {
            preconditionFailure("Missing required Wizard brand asset: \(name)")
        }
        image.accessibilityDescription = "Wizard"
        image.isTemplate = template
        return image
    }

    static func menuBarImage() -> NSImage {
        let mark = image("wizard-mark-white", template: true)
        let ratio = mark.size.width / mark.size.height
        mark.size = NSSize(width: 18, height: 18 / ratio)
        return mark
    }
}
