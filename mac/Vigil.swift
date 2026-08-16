// Vigil — the menu bar face.
//
// The whole point of this app is the state you see 90% of the time: a small,
// quiet, hollow dot that says nothing is wrong. It only fills and turns amber
// when a session literally cannot proceed without you.
//
// Menu bar icons are conventionally monochrome templates that adapt to the bar.
// The alarm deliberately breaks that convention -- that is what makes it
// register in peripheral vision without being read.

import AppKit
import Foundation

// MARK: - state coming off the daemon

struct Session: Decodable {
    let id: String
    let sessionId: String
    let repo: String
    let title: String
    let state: String
    let quiet_s: Double
    let asked: String?
    let claude: String?
}

struct Fleet: Decodable {
    let lamp: Bool
    let headline: String
    let focus: Session?
    let sessions: [Session]
    let repos: [String]
}

func human(_ s: Double) -> String {
    if s < 60 { return "\(Int(s.rounded()))s" }
    if s < 3600 { return "\(Int((s / 60).rounded()))m" }
    if s < 86400 {
        let h = s / 3600
        return h < 10 ? String(format: "%.1fh", h) : "\(Int(h.rounded()))h"
    }
    return "\(Int((s / 86400).rounded()))d"
}

// MARK: - logging

/// A menu bar app has nowhere to print, so it writes here.
/// Tail it with:  tail -f ~/Library/Logs/Vigil.log
let logURL = URL(fileURLWithPath: NSHomeDirectory() + "/Library/Logs/Vigil.log")

func vlog(_ message: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    let line = "\(stamp)  \(message)\n"
    guard let data = line.data(using: .utf8) else { return }
    if let fh = try? FileHandle(forWritingTo: logURL) {
        defer { try? fh.close() }
        _ = try? fh.seekToEnd()
        try? fh.write(contentsOf: data)
    } else {
        try? data.write(to: logURL)
    }
}

// MARK: - the app

final class Vigil: NSObject, NSApplicationDelegate {

    private var item: NSStatusItem!
    private var timer: Timer?
    private var fleet: Fleet?
    private var reachable = false
    private var startedDaemon = false

    private let endpoint = URL(string: "http://127.0.0.1:7717/api/state")!
    private let faceURL = URL(string: "http://127.0.0.1:7717/")!
    private let whereURL = URL(string: "http://127.0.0.1:7717/#where")!

    private let amber = NSColor(calibratedRed: 0.94, green: 0.66, blue: 0.23, alpha: 1)

    func applicationDidFinishLaunching(_ note: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.imagePosition = .imageOnly
        paintIcon()

        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu

        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            self?.poll()
        }

        vlog("launched; menu bar item installed")

        // Opening an app and getting no feedback at all is not "conventional
        // for a menu bar app", it is just bad. Drop the menu open once on
        // launch so it is obvious the click worked and where the icon lives.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { [weak self] in
            self?.revealMenu()
        }
    }

    /// Clicking the app in Spotlight while it is already running otherwise does
    /// nothing at all -- macOS just re-activates it. Show the menu instead.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        vlog("reopened from Finder/Spotlight")
        revealMenu()
        return true
    }

    private func revealMenu() {
        item.button?.performClick(nil)
    }

    // MARK: icon

    private func paintIcon() {
        guard let button = item.button else { return }

        // not watching: an explicit slash. A vigil that has fallen asleep must
        // never look the same as a vigil reporting all clear.
        if !reachable {
            let img = NSImage(systemSymbolName: "circle.slash",
                              accessibilityDescription: "Vigil is not running")
            img?.isTemplate = true
            button.image = img
            button.contentTintColor = nil
            button.toolTip = "Vigil is not running"
            return
        }

        let blocked = fleet?.lamp ?? false

        if blocked {
            // The menu bar forces template images monochrome and ignores
            // contentTintColor, so the alarm has to be drawn as real pixels.
            // That is the point: breaking the monochrome convention is what
            // makes it catch the eye without being read.
            let side: CGFloat = 12
            let dot = NSImage(size: NSSize(width: side, height: side), flipped: false) { rect in
                self.amber.setFill()
                NSBezierPath(ovalIn: rect.insetBy(dx: 2, dy: 2)).fill()
                return true
            }
            dot.isTemplate = false
            button.image = dot
            button.contentTintColor = nil
            button.toolTip = fleet?.headline ?? "A session needs you"
            button.setAccessibilityLabel("Vigil: a session needs you")
            return
        }

        // resting: a hollow template circle, so it adapts to the bar's theme
        let img = NSImage(systemSymbolName: "circle", accessibilityDescription: "Clear")
        let config = NSImage.SymbolConfiguration(pointSize: 10, weight: .regular)
        button.image = img?.withSymbolConfiguration(config)
        button.image?.isTemplate = true
        button.contentTintColor = nil
        button.toolTip = fleet?.headline ?? "Vigil"
        button.setAccessibilityLabel("Vigil: clear")
    }

    // MARK: polling

    private func poll() {
        var req = URLRequest(url: endpoint)
        req.timeoutInterval = 2.5
        req.cachePolicy = .reloadIgnoringLocalCacheData

        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let self else { return }
            let parsed: Fleet? = data.flatMap { try? JSONDecoder().decode(Fleet.self, from: $0) }
            DispatchQueue.main.async {
                let was = self.reachable
                let wasLamp = self.fleet?.lamp ?? false
                if let parsed {
                    self.fleet = parsed
                    self.reachable = true
                    if !was { vlog("daemon reachable") }
                    if parsed.lamp != wasLamp {
                        vlog(parsed.lamp ? "LAMP ON  -- \(parsed.headline)" : "lamp off -- clear")
                    }
                } else {
                    if was { vlog("lost the daemon") }
                    self.reachable = false
                    self.autostartOnce()
                }
                self.paintIcon()
            }
        }.resume()
    }

    /// Launch the daemon once per app run, so opening the app is enough.
    private func autostartOnce() {
        guard !startedDaemon else { return }
        startedDaemon = true
        vlog("daemon not reachable; starting it")
        let root = Bundle.main.object(forInfoDictionaryKey: "VigilRepoPath") as? String ?? ""
        let python = Bundle.main.object(forInfoDictionaryKey: "VigilPython") as? String ?? "/usr/bin/python3"
        guard !root.isEmpty, FileManager.default.fileExists(atPath: root) else {
            vlog("cannot start daemon: package missing at \(root)")
            return
        }

        // Never send this to /dev/null. A daemon that fails to start silently
        // is indistinguishable from one that started, and cost two debug rounds.
        let logPath = "/tmp/vigil-daemon.log"
        FileManager.default.createFile(atPath: logPath, contents: nil)
        let log = FileHandle(forWritingAtPath: logPath)

        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["-u", "-m", "vigil"]   // -u: unbuffered, or the log stays empty
        p.currentDirectoryURL = URL(fileURLWithPath: root)
        // `-m` resolves the package from the working directory, which a GUI
        // process does not inherit the way a shell does.
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = root
        // never let Python write bytecode into a signed bundle
        env["PYTHONPYCACHEPREFIX"] = NSHomeDirectory() + "/Library/Caches/vigil"
        p.environment = env
        if let log {
            p.standardOutput = log
            p.standardError = log
        }
        do {
            try p.run()
        } catch {
            try? log?.write(contentsOf: Data("vigil: could not launch daemon: \(error)\n".utf8))
        }
    }

    // MARK: actions

    @objc private func openFace() { NSWorkspace.shared.open(faceURL) }

    @objc private func openWhere() { NSWorkspace.shared.open(whereURL) }

    @objc private func copyFocusId() {
        guard let sid = fleet?.focus?.sessionId else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(sid, forType: .string)
    }

    @objc private func copySession(_ sender: NSMenuItem) {
        guard let sid = sender.representedObject as? String else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(sid, forType: .string)
    }

    @objc private func quit() {
        vlog("quit")
        NSApp.terminate(nil)
    }
}

// MARK: - the menu, rebuilt each time it opens

extension Vigil: NSMenuDelegate {

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()

        guard reachable, let f = fleet else {
            menu.addItem(header("The vigil is not running.", bold: true))
            menu.addItem(header("Start it: python3 -m vigil", bold: false))
            menu.addItem(.separator())
            menu.addItem(action("Quit Vigil", #selector(quit), key: "q"))
            return
        }

        menu.addItem(header(f.headline, bold: true, color: f.lamp ? amber : nil))

        if f.lamp, let focus = f.focus {
            let ask = (focus.asked?.isEmpty == false ? focus.asked : focus.claude) ?? ""
            for line in wrap(ask, width: 52).prefix(4) {
                menu.addItem(header(line, bold: false))
            }
            menu.addItem(header("\(focus.repo) · waiting \(human(focus.quiet_s))", bold: false))
        }

        menu.addItem(.separator())

        if f.sessions.isEmpty {
            menu.addItem(header("Nothing is running.", bold: false))
        }
        for s in f.sessions {
            let dot = s.state == "blocked" ? "◉" : (s.state == "working" ? "●" : "○")
            let title = s.title.count > 42 ? String(s.title.prefix(41)) + "…" : s.title
            let mi = NSMenuItem(
                title: "\(dot)  \(s.repo) — \(title)   \(human(s.quiet_s))",
                action: #selector(copySession(_:)), keyEquivalent: "")
            mi.target = self
            mi.representedObject = s.sessionId
            mi.toolTip = "Copy session id"
            if s.state == "blocked" {
                mi.attributedTitle = NSAttributedString(
                    string: mi.title,
                    attributes: [.foregroundColor: amber,
                                 .font: NSFont.menuFont(ofSize: 13)])
            }
            menu.addItem(mi)
        }

        menu.addItem(.separator())
        menu.addItem(action("Open the Face", #selector(openFace), key: "o"))
        menu.addItem(action("Where was I", #selector(openWhere), key: "w"))
        if f.lamp {
            menu.addItem(action("Copy blocked session id", #selector(copyFocusId), key: "c"))
        }
        menu.addItem(.separator())
        menu.addItem(action("Quit Vigil", #selector(quit), key: "q"))
    }

    private func header(_ text: String, bold: Bool, color: NSColor? = nil) -> NSMenuItem {
        let mi = NSMenuItem(title: text, action: nil, keyEquivalent: "")
        mi.isEnabled = false
        var attrs: [NSAttributedString.Key: Any] = [
            .font: bold ? NSFont.boldSystemFont(ofSize: 13)
                        : NSFont.menuFont(ofSize: 12)
        ]
        attrs[.foregroundColor] = color ?? NSColor.secondaryLabelColor
        mi.attributedTitle = NSAttributedString(string: text, attributes: attrs)
        return mi
    }

    private func action(_ title: String, _ sel: Selector, key: String) -> NSMenuItem {
        let mi = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        mi.target = self
        return mi
    }

    /// Menu items do not wrap, so a long question has to be broken by hand.
    private func wrap(_ text: String, width: Int) -> [String] {
        var lines: [String] = []
        var line = ""
        for word in text.split(separator: " ") {
            if line.count + word.count + 1 > width {
                lines.append(line)
                line = String(word)
            } else {
                line = line.isEmpty ? String(word) : line + " " + word
            }
        }
        if !line.isEmpty { lines.append(line) }
        return lines
    }
}

// MARK: - entry point

let app = NSApplication.shared
let delegate = Vigil()
app.delegate = delegate
app.setActivationPolicy(.accessory)   // menu bar only, no Dock icon
app.run()
