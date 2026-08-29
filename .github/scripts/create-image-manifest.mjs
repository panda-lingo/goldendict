import { spawnSync } from "node:child_process";
import { appendFileSync, readdirSync } from "node:fs";

function fail(message) {
  throw new Error(`Container manifest: ${message}`);
}

function docker(args, capture = false) {
  const result = spawnSync("docker", args, {
    encoding: capture ? "utf8" : undefined,
    stdio: capture ? ["ignore", "pipe", "inherit"] : "inherit",
  });
  if (result.status !== 0) {
    fail(`docker ${args.slice(0, 3).join(" ")} failed with ${result.status}`);
  }
  return capture ? result.stdout.trim() : "";
}

const image = process.env.REGISTRY_IMAGE;
const digestsDirectory = process.env.DIGESTS_DIRECTORY;
const metadataJson = process.env.DOCKER_METADATA_OUTPUT_JSON;
if (!image || !digestsDirectory || !metadataJson) {
  fail("REGISTRY_IMAGE, DIGESTS_DIRECTORY, and metadata JSON are required");
}

const metadata = JSON.parse(metadataJson);
if (!Array.isArray(metadata.tags) || metadata.tags.length === 0) {
  fail("docker metadata did not produce release tags");
}
for (const tag of metadata.tags) {
  if (typeof tag !== "string" || !tag.startsWith(`${image}:`)) {
    fail(`unexpected release tag: ${String(tag)}`);
  }
}

const digestHexes = readdirSync(digestsDirectory)
  .filter((name) => /^[0-9a-f]{64}$/u.test(name))
  .sort();
if (digestHexes.length !== 2) {
  fail(`expected two platform digests, found ${digestHexes.length}`);
}

const createArguments = ["buildx", "imagetools", "create"];
for (const tag of metadata.tags) createArguments.push("--tag", tag);
for (const digest of digestHexes) {
  createArguments.push(`${image}@sha256:${digest}`);
}
docker(createArguments);

const manifestJson = docker(
  [
    "buildx",
    "imagetools",
    "inspect",
    metadata.tags[0],
    "--format",
    "{{json .Manifest}}",
  ],
  true,
);
const manifest = JSON.parse(manifestJson);
if (!/^sha256:[0-9a-f]{64}$/u.test(manifest.digest ?? "")) {
  fail("merged image did not report a valid digest");
}
const platforms = (manifest.manifests ?? [])
  .map((entry) => `${entry.platform?.os}/${entry.platform?.architecture}`)
  .sort();
const expectedPlatforms = ["linux/amd64", "linux/arm64"];
if (JSON.stringify(platforms) !== JSON.stringify(expectedPlatforms)) {
  fail(`expected ${expectedPlatforms.join(", ")}, got ${platforms.join(", ")}`);
}

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    `digest=${manifest.digest}\nreference=${metadata.tags[0]}\n`,
  );
}
process.stdout.write(
  `${JSON.stringify({ digest: manifest.digest, tags: metadata.tags, platforms })}\n`,
);
