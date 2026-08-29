.PHONY: build build-backend-native build-backend-python check-goldendict test test-native-worker test-frontend test-backend test-backend-real typecheck verify

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

build-backend-python:
	docker build --target runtime --tag goldendict-api:python backend

test-native-worker: build-backend-native
	python3 backend/native/tests/protocol_smoke.py --image "$(GOLDENDICT_NATIVE_IMAGE)"
	python3 backend/native/tests/container_smoke.py --image "$(GOLDENDICT_NATIVE_IMAGE)"

check-goldendict:
	npm run check:goldendict --workspace @goldendict-web/frontend

test: test-frontend test-backend

test-frontend:
	npm test

test-backend:
	docker build --target test -t goldendict-api-test ./backend
	docker run --rm goldendict-api-test

test-backend-real:
	test -n "$(GOLDENDICT_TEST_DICTIONARY_PATH)"
	docker build --target test -t goldendict-api-test ./backend
	docker run --rm \
		-v "$(dir $(GOLDENDICT_TEST_DICTIONARY_PATH)):/fixtures:ro" \
		-e "GOLDENDICT_TEST_MDX=/fixtures/$(notdir $(GOLDENDICT_TEST_DICTIONARY_PATH))" \
		goldendict-api-test python -m pytest -m integration

typecheck:
	npm run typecheck

verify: check-goldendict typecheck test build
