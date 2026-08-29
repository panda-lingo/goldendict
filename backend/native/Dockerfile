# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04 AS build

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      cmake \
      git \
      libbz2-dev \
      libfmt-dev \
      liblzma-dev \
      liblzo2-dev \
      qt6-base-dev \
      qt6-svg-dev \
      zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Keep provenance arguments after the dependency layer so local-source digest
# changes do not force apt packages to reinstall.
ARG GOLDENDICT_NG_COMMIT=5ad66765aa423d381025566bff990f7d8007be84
ARG GOLDENDICT_NG_DIRTY=
ARG GOLDENDICT_NG_DIFF_SHA256=
ARG GOLDENDICT_NG_REQUIRE_CLEAN=OFF

WORKDIR /src/worker
COPY . .
COPY --from=goldendict-ng . /src/goldendict-ng

RUN cmake -S . -B /build \
      -DCMAKE_BUILD_TYPE=Release \
      -DGOLDENDICT_NG_SOURCE=/src/goldendict-ng \
      -DGOLDENDICT_NG_COMMIT="${GOLDENDICT_NG_COMMIT}" \
      -DGOLDENDICT_NG_DIRTY="${GOLDENDICT_NG_DIRTY}" \
      -DGOLDENDICT_NG_DIFF_SHA256="${GOLDENDICT_NG_DIFF_SHA256}" \
      -DGOLDENDICT_NG_REQUIRE_CLEAN="${GOLDENDICT_NG_REQUIRE_CLEAN}" \
    && cmake --build /build --parallel "$(nproc)" \
    && ctest --test-dir /build --output-on-failure \
    && cmake --install /build --prefix /opt/native

FROM ubuntu:24.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      libbz2-1.0 \
      libfmt9 \
      liblzma5 \
      liblzo2-2 \
      libqt6concurrent6 \
      libqt6core6t64 \
      libqt6gui6 \
      libqt6svg6 \
      libqt6widgets6 \
      libqt6xml6 \
      zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/native/bin/goldendict-native-worker /usr/local/bin/goldendict-native-worker

RUN useradd --system --uid 10001 --create-home --home-dir /var/lib/goldendict goldendict \
    && install -d -o goldendict -g goldendict /var/lib/goldendict/indices /dictionaries

USER 10001
ENTRYPOINT ["goldendict-native-worker"]
CMD ["--dictionary-root", "/dictionaries", "--index-dir", "/var/lib/goldendict/indices"]
