// Draws Vigil's app icon: the instrument, reduced to one mark on a rail.
//
// At small sizes the rail and the dim marks turn to mush, so they are dropped
// and only the amber mark survives, larger. An icon that is illegible at 16pt
// is not a smaller icon, it is a worse one.

import AppKit
import Foundation

let ground = NSColor(calibratedRed: 0.086, green: 0.106, blue: 0.129, alpha: 1) // #161B22
let rail   = NSColor(calibratedRed: 0.157, green: 0.192, blue: 0.235, alpha: 1) // #28313C
let dim    = NSColor(calibratedRed: 0.467, green: 0.510, blue: 0.557, alpha: 1) // #77828E
let amber  = NSColor(calibratedRed: 0.941, green: 0.663, blue: 0.231, alpha: 1) // #F0A93B

func dot(_ cx: CGFloat, _ cy: CGFloat, _ r: CGFloat, _ color: NSColor) {
    color.setFill()
    NSBezierPath(ovalIn: CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2)).fill()
}

func render(_ px: Int) -> Data? {
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    let s = CGFloat(px)
    // macOS icons sit inside their canvas rather than filling it
    let inset = s * 0.085
    let box = CGRect(x: inset, y: inset, width: s - inset * 2, height: s - inset * 2)
    let radius = box.width * 0.2237          // the standard squircle-ish corner
    ground.setFill()
    NSBezierPath(roundedRect: box, xRadius: radius, yRadius: radius).fill()

    let mid = s / 2

    if px >= 64 {
        // the rail, with the fleet on it: quiet marks, then the one that is lit
        let line = NSBezierPath()
        line.move(to: CGPoint(x: box.minX + box.width * 0.16, y: mid))
        line.line(to: CGPoint(x: box.maxX - box.width * 0.16, y: mid))
        line.lineWidth = max(1, s * 0.014)
        rail.setStroke()
        line.stroke()

        dot(box.minX + box.width * 0.26, mid, s * 0.030, dim)
        dot(box.minX + box.width * 0.45, mid, s * 0.030, dim)

        // No halo. A flat translucent disc is not a glow -- it renders as a
        // brown coin around the mark. The amber against the dim marks already
        // carries the hierarchy; the ring was decoration.
        dot(box.minX + box.width * 0.71, mid, s * 0.068, amber)
    } else {
        // small: the mark alone, sized to still read
        dot(mid, mid, s * 0.19, amber)
    }

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "./Vigil.iconset"
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)

// (logical point size, @2x?) -> the filenames iconutil expects
let plan: [(Int, Bool)] = [(16, false), (16, true), (32, false), (32, true),
                           (128, false), (128, true), (256, false), (256, true),
                           (512, false), (512, true)]

for (pt, retina) in plan {
    let px = retina ? pt * 2 : pt
    guard let data = render(px) else { continue }
    let name = retina ? "icon_\(pt)x\(pt)@2x.png" : "icon_\(pt)x\(pt).png"
    try? data.write(to: URL(fileURLWithPath: "\(out)/\(name)"))
}
print("iconset written to \(out)")
