import { appendFileSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

function fail(message) {
  throw new Error(`GoldenDict-ng metadata: ${message}`);
}

function parseLock(contents) {
  const values = new Map();
  for (const rawLine of contents.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) fail(`invalid upstream.lock line: ${rawLine}`);
    const key = line.slice(0, separator);
    const value = line.slice(separator + 1);
    if (values.has(key)) fail(`duplicate upstream.lock key: ${key}`);
    values.set(key, value);
  }
  return values;
}

function normalizeRepository(value) {
  let parsed;
  try {
    parsed = new URL(value.replace(/^git\+/u, ""));
  } catch {
    fail(`invalid repository URL: ${value}`);
  }
  if (parsed.protocol !== "https:" || parsed.hostname !== "github.com") {
    fail("the upstream repository must be an https://github.com URL");
  }
  const parts = parsed.pathname.replace(/\.git$/u, "").split("/").filter(Boolean);
  if (
    parts.length !== 2 ||
    parts.some((part) => !/^[A-Za-z0-9_.-]+$/u.test(part))
  ) {
    fail(`invalid GitHub repository path: ${parsed.pathname}`);
  }
  return {
    slug: parts.join("/"),
    url: `https://github.com/${parts.join("/")}`,
  };
}

const lock = parseLock(
  readFileSync(resolve(repositoryRoot, "backend/native/upstream.lock"), "utf8"),
);
const lockedRepository = normalizeRepository(lock.get("repository") ?? "");
const commit = lock.get("commit") ?? "";
if (!/^[0-9a-f]{40}$/u.test(commit)) {
  fail("upstream.lock commit must be 40 lowercase hexadecimal characters");
}

const frontendManifest = JSON.parse(
  readFileSync(
    resolve(
      repositoryRoot,
      "packages/frontend/compatibility/goldendict-ng.json",
    ),
    "utf8",
  ),
);
const compatibilityYaml = readFileSync(
  resolve(repositoryRoot, "backend/upstream-compatibility.yaml"),
  "utf8",
);
const compatibilityRepository = /^  repository: (\S+)$/mu.exec(
  compatibilityYaml,
)?.[1];
const compatibilityCommit = /^  commit: ([0-9a-f]+)$/mu.exec(
  compatibilityYaml,
)?.[1];

for (const [source, repository, sourceCommit] of [
  [
    "frontend compatibility manifest",
    frontendManifest.sourceRepository,
    frontendManifest.sourceCommit,
  ],
  [
    "backend compatibility manifest",
    compatibilityRepository,
    compatibilityCommit,
  ],
]) {
  if (normalizeRepository(repository ?? "").url !== lockedRepository.url) {
    fail(`${source} repository does not match upstream.lock`);
  }
  if (sourceCommit !== commit) {
    fail(`${source} commit does not match upstream.lock`);
  }
}

const metadata = {
  repository: lockedRepository.slug,
  repositoryUrl: lockedRepository.url,
  commit,
};

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    `repository=${metadata.repository}\nrepository_url=${metadata.repositoryUrl}\ncommit=${metadata.commit}\n`,
  );
}

process.stdout.write(`${JSON.stringify(metadata)}\n`);
