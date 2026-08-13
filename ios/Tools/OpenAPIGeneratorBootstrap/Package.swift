// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "IlliniCoverOpenAPIGeneratorBootstrap",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(
            url: "https://github.com/apple/swift-openapi-generator.git",
            exact: "1.13.0"
        ),
    ],
    targets: [
        .executableTarget(name: "Bootstrap"),
    ]
)
