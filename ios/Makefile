.PHONY: api api-check generate generate-check resolve build test

DEVELOPER_DIR ?= /Applications/Xcode.app/Contents/Developer
PACKAGE_CLONE_DIR ?= ../.local/xcode-packages
GENERATOR_PACKAGE_DIR ?= ../.local/openapi-generator-packages
GENERATOR_BUILD_DIR ?= ../.local/openapi-generator-build
GENERATOR := $(GENERATOR_BUILD_DIR)/release/swift-openapi-generator
API_OUTPUT := IlliniCover/API/Generated
XCODEGEN ?= xcodegen

$(GENERATOR): Tools/OpenAPIGeneratorBootstrap/Package.swift
	DEVELOPER_DIR="$(DEVELOPER_DIR)" swift package \
	  --package-path Tools/OpenAPIGeneratorBootstrap \
	  --scratch-path "$(GENERATOR_PACKAGE_DIR)" resolve
	DEVELOPER_DIR="$(DEVELOPER_DIR)" swift build \
	  --package-path "$(GENERATOR_PACKAGE_DIR)/checkouts/swift-openapi-generator" \
	  --product swift-openapi-generator --configuration release --jobs 2 \
	  --scratch-path "$(GENERATOR_BUILD_DIR)"

api: $(GENERATOR)
	@mkdir -p "$(API_OUTPUT)"
	"$(GENERATOR)" generate ../api/openapi.json \
	  --config IlliniCover/API/openapi-generator-config.yaml \
	  --output-directory "$(API_OUTPUT)"

api-check: $(GENERATOR)
	@mkdir -p ../.local/api-contract-check
	"$(GENERATOR)" generate ../api/openapi.json \
	  --config IlliniCover/API/openapi-generator-config.yaml \
	  --output-directory ../.local/api-contract-check >/dev/null
	diff -u "$(API_OUTPUT)/Types.swift" ../.local/api-contract-check/Types.swift
	diff -u "$(API_OUTPUT)/Client.swift" ../.local/api-contract-check/Client.swift

generate:
	$(XCODEGEN) generate

generate-check:
	./scripts/verify-project.sh

resolve: generate
	derived_data_path="$$(./scripts/xcode-derived-data-path.sh)"; \
	DEVELOPER_DIR="$(DEVELOPER_DIR)" xcodebuild -resolvePackageDependencies \
	  -project IlliniCover.xcodeproj -scheme IlliniCover \
	  -derivedDataPath "$$derived_data_path" \
	  -clonedSourcePackagesDirPath "$(PACKAGE_CLONE_DIR)"

build: generate
	./scripts/build.sh

test:
	./scripts/test.sh
