// Regenerate native vector assets and the macOS application icon from the SVG.
// Supports only the SVG primitives used by this mark; rejects unsupported input.
import AppKit
import Foundation

final class MarkReader: NSObject, XMLParserDelegate {
    let context: CGContext
    let foreground: CGColor
    var failure: String?

    init(context: CGContext, foreground: CGColor) {
        self.context = context
        self.foreground = foreground
    }

    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?,
                qualifiedName: String?, attributes: [String: String]) {
        switch name {
        case "svg":
            if attributes["viewBox"] != "0 0 160 160" { failure = "Unexpected viewBox" }
        case "g": break
        case "circle":
            guard let cx = Double(attributes["cx"] ?? ""),
                  let cy = Double(attributes["cy"] ?? ""),
                  let radius = Double(attributes["r"] ?? ""),
                  attributes["fill"] == "#c9e879" else {
                failure = "Unsupported circle"; return
            }
            context.setFillColor(CGColor(red: 201/255, green: 232/255, blue: 121/255, alpha: 1))
            context.fillEllipse(in: CGRect(x: cx-radius, y: cy-radius, width: radius*2, height: radius*2))
        case "path":
            guard let data = attributes["d"] else { failure = "Missing path"; return }
            let scanner = Scanner(string: data)
            scanner.charactersToBeSkipped = .whitespacesAndNewlines.union(CharacterSet(charactersIn: ","))
            let path = CGMutablePath()
            var command: Character = "M"
            var point = CGPoint.zero
            var start = point
            while !scanner.isAtEnd {
                if let token = scanner.scanCharacters(from: .letters) {
                    guard token.count == 1, let next = token.first else {
                        failure = "Unsupported path command"; return
                    }
                    command = next
                }
                let relative = command.isLowercase
                if command == "z" || command == "Z" {
                    path.closeSubpath(); point = start
                    command = "?"
                    continue
                }
                guard let first = scanner.scanDouble() else { failure = "Missing coordinate"; return }
                switch command {
                case "M", "m", "L", "l":
                    guard let second = scanner.scanDouble() else { failure = "Missing y coordinate"; return }
                    point = CGPoint(x: first + (relative ? point.x : 0), y: second + (relative ? point.y : 0))
                    if command == "M" || command == "m" {
                        path.move(to: point); start = point
                        command = relative ? "l" : "L"
                    } else { path.addLine(to: point) }
                case "H", "h":
                    point.x = first + (relative ? point.x : 0); path.addLine(to: point)
                case "V", "v":
                    point.y = first + (relative ? point.y : 0); path.addLine(to: point)
                default: failure = "Unsupported path command: \(command)"; return
                }
            }
            context.setFillColor(foreground)
            context.addPath(path)
            context.fillPath()
        default: failure = "Unsupported SVG element: \(name)"
        }
    }
}

let resources = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    .deletingLastPathComponent().appendingPathComponent("Sources/ASRDesktopApp/Resources")
let source = try Data(contentsOf: resources.appendingPathComponent("karakuri-mark.svg"))
for (name, shade) in [("light", 0.12), ("dark", 0.95)] {
    let output = NSMutableData()
    var bounds = CGRect(x: 0, y: 0, width: 160, height: 160)
    let consumer = CGDataConsumer(data: output)!
    let context = CGContext(consumer: consumer, mediaBox: &bounds, nil)!
    context.beginPDFPage(nil)
    context.translateBy(x: 0, y: 160)
    context.scaleBy(x: 1, y: -1)
    let reader = MarkReader(context: context, foreground: CGColor(gray: shade, alpha: 1))
    let parser = XMLParser(data: source)
    parser.delegate = reader
    guard parser.parse(), reader.failure == nil else {
        fatalError(reader.failure ?? "Invalid SVG")
    }
    context.endPDFPage()
    context.closePDF()
    try (output as Data).write(to: resources.appendingPathComponent("karakuri-mark-\(name).pdf"))
}

let iconset = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: iconset) }
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        let context = NSGraphicsContext(bitmapImageRep: bitmap)!.cgContext
        context.scaleBy(x: CGFloat(pixels)/1024, y: CGFloat(pixels)/1024)
        context.setFillColor(CGColor(gray: 0.98, alpha: 1))
        context.addPath(CGPath(roundedRect: CGRect(x: 64, y: 64, width: 896, height: 896),
                               cornerWidth: 196, cornerHeight: 196, transform: nil))
        context.fillPath()
        context.translateBy(x: 123, y: 880)
        context.scaleBy(x: 4.6, y: -4.6)
        let reader = MarkReader(context: context, foreground: CGColor(gray: 0.12, alpha: 1))
        let parser = XMLParser(data: source)
        parser.delegate = reader
        guard parser.parse(), reader.failure == nil else { fatalError(reader.failure ?? "Invalid SVG") }
        let suffix = scale == 2 ? "@2x" : ""
        let png = bitmap.representation(using: .png, properties: [:])!
        try png.write(to: iconset.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}
let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["--convert", "icns", "--output", resources.appendingPathComponent("ASRDesktop.icns").path, iconset.path]
try iconutil.run()
iconutil.waitUntilExit()
precondition(iconutil.terminationStatus == 0, "iconutil failed")
