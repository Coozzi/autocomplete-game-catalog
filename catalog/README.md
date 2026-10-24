# Public game catalog contributions

`manual.json` is the reviewed source for curated additions. Submit changes through a normal pull request; the validation workflow checks the schema and normalization rules without network access. The publisher reads only the reviewed default-branch version of this file. It never runs with a write-capable token for pull-request events.

Use a permanent ASCII ID in the `manual:<stable-slug>` namespace, for example `manual:stardew-valley`. Choose the slug from a stable product identity, not the display name, executable name, or list position. Once released, an ID and its entry are immutable. To correct or replace an entry, propose a new ID and explain the migration in the pull request. IDs are never recycled. Discord entries keep their original decimal IDs.

Each contribution needs a display name and one to sixteen Windows executable paths. Paths are relative executable suffixes, use backslashes, and must end in `.exe`. Use specific paths such as `bin\\game.exe`; bare executable names and generic launchers are rejected. Do not include user paths, URLs, arguments, or wildcards. Keep the mapping limited to executable identity; it does not grant an input provider or editor permission.

Limits: 5,000 manual entries, 16 executable patterns per entry, 128 UTF-8 bytes per name/path, and 8 MiB total normalized catalog. The publisher additionally applies the parser's path safety checks and bounds the Discord response to 16 MiB.

The publisher runs daily at 02:07 Asia/Seoul, after a reviewed `manual.json` change reaches the default branch, or through `workflow_dispatch`. It merges new records with the previous snapshot, so omission from Discord's current response never removes a prior entry. A publisher run with no additions writes no files and makes no commit.

The private feed is stored under `catalog/published/` for GitHub Contents API reads. `manifest.json` is a small pointer with this shape:

```json
{"schema_version":1,"feed":"autocomplete-public-catalog","revision":12,"entry_count":345,"snapshot":{"path":"snapshots/catalog-v00000012.json","sha256":"<sha256 of canonical snapshot JSON>"},"latest_delta":{"path":"deltas/delta-00000012.json","sha256":"<sha256 of canonical delta JSON>"}}
```

Every revision has an immutable full snapshot at `snapshots/catalog-vNNNNNNNN.json`, with `schema_version`, `feed`, `revision`, `entry_count`, sorted `entries`, and `sha256` (SHA-256 of canonical sorted entries JSON). It also has an immutable delta at `deltas/delta-NNNNNNNN.json`, with `schema_version`, `feed`, `from_revision`, `to_revision`, sorted `operations` (`{"op":"add","entry":...}` only), and `sha256` (SHA-256 of the same delta object without its `sha256` field). The pointer hashes each referenced file's canonical JSON bytes, excluding the final newline. A client can compare revisions first, fetch the snapshot only when it has no base, or fetch each missing numbered delta in order and verify its hash before applying additions. Never apply a delta with a gap or a conflicting existing ID.
