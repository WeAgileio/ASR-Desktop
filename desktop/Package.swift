// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ASRDesktop",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "ASRDesktopApp", targets: ["ASRDesktopApp"]),
        .executable(name: "asr-desktop", targets: ["ASRDesktopCLI"]),
        .executable(name: "ASRDesktopHelper", targets: ["ASRDesktopHelper"]),
    ],
    targets: [
        .target(name: "ASRDesktopCore"),
        .executableTarget(name: "ASRDesktopApp", dependencies: ["ASRDesktopCore"]),
        .executableTarget(name: "ASRDesktopCLI", dependencies: ["ASRDesktopCore"]),
        .executableTarget(name: "ASRDesktopHelper", dependencies: ["ASRDesktopCore"]),
        .testTarget(name: "ASRDesktopCoreTests", dependencies: ["ASRDesktopCore"]),
    ]
)
