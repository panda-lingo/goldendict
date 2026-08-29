# Updating GoldenDict-ng rendering compatibility

Vendored upstream files have an explicit boundary:

- `src/styles/vendor/` contains unmodified GoldenDict-ng article CSS.
- `src/assets/icons/` contains the upstream icons used by that CSS and article HTML.
- `compatibility/goldendict-ng.json` pins the repository commit and SHA-256 of every copied file.
- Hand-written browser adapters live elsewhere in `src/` and are never overwritten by sync.

To adopt a newer or modified local GoldenDict-ng checkout:

```sh
npm run sync:goldendict --workspace @goldendict-web/frontend -- \
  --source /path/to/goldendict-ng
npm test
npm run build
```

The sync command copies only manifest-listed files, records their new checksums,
and pins the checkout's origin, current Git commit, relevant dirty state, and
diff hash. This also makes an intentional local modification visible instead of
mislabeling it as an unmodified upstream commit. Review the vendor and manifest diff.
If upstream adds a stylesheet or required icon, add its source/target mapping to
the manifest and expose it from `styles/fidelity.ts` or `assets.ts`; the
compatibility contract test is intended to make omissions visible.

CI and local builds run the target-only checksum check automatically. To also
verify a checkout matches the currently pinned version:

```sh
npm run check:goldendict --workspace @goldendict-web/frontend -- \
  --source /path/to/goldendict-ng
```
