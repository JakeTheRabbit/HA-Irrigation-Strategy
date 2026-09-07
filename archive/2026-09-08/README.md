# Historical files archived 8 September 2026

These files preserve the old full dashboards, superseded instructions and one-off developer tools. They are not active product pages or validated installation instructions.

- manifest.json records original paths and SHA-256 hashes for the main archive operation.
- configuration-manifest.json records the old root facility config.yaml, renamed configuration.legacy.yaml so Home Assistant does not discover it as an app.
- README-previous.md preserves the previous README.

Old dashboard URLs in the active web folders are small redirects into the modern workspace. The original interfaces remain here for reference, including unsupported or unvalidated claims/controls. Use the root README and docs/INSTALL.md for current instructions.

Stable runtime entities and the controller slug were preserved. User-owned aigrow-ops.html files were left untouched.

Obsolete screenshots are in img/ with hashes in screenshot-manifest.json. duplicate-manifest.json maps redundant archived copies to the retained identical file; duplicate payloads are not published twice. The completed one-off archive script is retained under tools/.

Unused generated shadcn components are retained under frontend/ and indexed by unused-ui-manifest.json. The active frontend no longer installs their unused cn and next-themes packages.

The final root cleanup archives 36 additional files: original facility dashboards and package/deploy YAML, old environment templates, generated Lovelace sample, unused root demo entry, legacy controller packages, disabled/nested workflows and redundant guide redirect pages. repository-cleanup-manifest.json records their original paths and SHA-256 hashes. Current reference documentation lives in docs/. Archived thresholds and instructions are historical examples.
