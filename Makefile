.PHONY: build build-backend-native check-goldendict test test-native-worker test-frontend test-backend typecheck verify

GOLDENDICT_NG_SOURCE ?= ../goldendict-ng
GOLDENDICT_NATIVE_IMAGE ?= goldendict-api:native

build:
	npm run build

build-backend-native:
	GOLDENDICT_NATIVE_DOCKERFILE="$(CURDIR)/backend/Dockerfile.native" \
	GOLDENDICT_NATIVE_BUILD_CONTEXT="$(CURDIR)/backend" \
	GOLDENDICT_NATIVE_TARGET=native-runtime \
	GOLDENDICT_NATIVE_IMAGE="$(GOLDENDICT_NATIVE_IMAGE)" \
		backend/native/build.sh "$(GOLDENDICT_NG_SOURCE)"

test-native-worker: build-backend-native
	python3 backend/native/tests/protocol_smoke.py --image "$(GOLDENDICT_NATIVE_IMAGE)"
	python3 backend/native/tests/container_smoke.py --image "$(GOLDENDICT_NATIVE_IMAGE)"

check-goldendict:
	npm run check:goldendict --workspace @panda-lingo/goldendict

test: test-frontend test-backend

test-frontend:
	npm test

test-backend:
	docker build --target test -t goldendict-api-test ./backend
	docker run --rm goldendict-api-test

typecheck:
	npm run typecheck

verify: check-goldendict typecheck test build
