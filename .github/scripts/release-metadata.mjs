import { appendFileSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const readJson = (path) =>
  JSON.parse(readFileSync(resolve(repositoryRoot, path), "utf8"));
const rootPackage = readJson("package.json");
const frontendPackage = readJson("packages/frontend/package.json");
const demoPackage = readJson("demo/package.json");
const pyproject = readFileSync(
  resolve(repositoryRoot, "backend/pyproject.toml"),
  "utf8",
);
const backendInit = readFileSync(
  resolve(repositoryRoot, "backend/app/__init__.py"),
  "utf8",
);

function fail(message) {
  throw new Error(`Release metadata: ${message}`);
}

const version = frontendPackage.version;
if (
  typeof version !== "string" ||
  !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?$/u.test(
    version,
  )
) {
  fail(`frontend version is not release SemVer: ${String(version)}`);
}

const backendProjectVersion = /^version = "([^"]+)"$/mu.exec(pyproject)?.[1];
const backendRuntimeVersion = /^__version__ = "([^"]+)"$/mu.exec(
  backendInit,
)?.[1];
for (const [name, candidate] of [
  ["root package", rootPackage.version],
  ["demo package", demoPackage.version],
  ["backend project", backendProjectVersion],
  ["backend runtime", backendRuntimeVersion],
]) {
  if (candidate !== version) {
    fail(`${name} version ${String(candidate)} does not match ${version}`);
  }
}
if (rootPackage.private !== true || demoPackage.private !== true) {
  fail("the workspace root and demo must remain private npm packages");
}
if (frontendPackage.private === true) {
  fail("the frontend package is marked private");
}
if (
  frontendPackage.publishConfig?.access !== "public" ||
  frontendPackage.publishConfig?.registry !== "https://registry.npmjs.org"
) {
  fail("frontend publishConfig must target the public npm registry");
}

const githubRepository = process.env.GITHUB_REPOSITORY;
if (!githubRepository) fail("GITHUB_REPOSITORY is required");
const configuredRepository = String(frontendPackage.repository?.url ?? "")
  .replace(/^git\+/u, "")
  .replace(/\.git$/u, "");
const expectedRepository = `https://github.com/${githubRepository}`;
if (configuredRepository !== expectedRepository) {
  fail(
    `frontend repository.url must be ${expectedRepository}, got ${configuredRepository}`,
  );
}

const releaseTag = process.env.RELEASE_TAG;
if (releaseTag !== `v${version}`) {
  fail(`release tag must be v${version}, got ${String(releaseTag)}`);
}
const versionIsPrerelease = version.includes("-");
const releaseIsPrerelease = process.env.RELEASE_PRERELEASE === "true";
if (versionIsPrerelease !== releaseIsPrerelease) {
  fail("the GitHub prerelease flag must match the package version");
}
const npmDistTag = versionIsPrerelease ? "next" : "latest";

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    `version=${version}\npackage_name=${frontendPackage.name}\nnpm_dist_tag=${npmDistTag}\n`,
  );
}

process.stdout.write(
  `${JSON.stringify({ version, packageName: frontendPackage.name, npmDistTag })}\n`,
);
