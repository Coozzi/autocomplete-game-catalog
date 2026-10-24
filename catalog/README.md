# Public game catalog contributions

`manual.json` is the reviewed source for curated additions. Submit changes through a normal pull request; the validation workflow checks the schema and normalization rules without network access. The publisher reads only the reviewed default-branch version of this file. It never runs with a write-capable token for pull-request events.

Use a permanent ASCII ID in the `manual:<stable-slug>` namespace, for example `manual:stardew-valley`. Choose the slug from a stable product identity, not the display name, executable name, or list position. Once released, an ID and its entry are immutable. To correct or replace an entry, propose a new ID and explain the migration in the pull request. IDs are never recycled. Discord entries keep their original decimal IDs.

Each contribution needs a display name and one to sixteen Windows executable paths. Paths are relative executable suffixes, use backslashes, and must end in `.exe`. Use specific paths such as `bin\\game.exe`; bare executable names and generic launchers are rejected. Do not include user paths, URLs, arguments, or wildcards. Keep the mapping limited to executable identity; it does not grant an input provider or editor permission.

Limits: 5,000 manual entries, 16 executable patterns per entry, 128 UTF-8 bytes per name/path, an 8 MiB serialized snapshot, a 512 KiB serialized delta, and a 16 MiB streamed Discord response. The publisher applies the same executable path safety checks as the application parser.

The publisher runs daily at 02:07 Asia/Seoul, after a reviewed `manual.json` change reaches the default branch, or through `workflow_dispatch`. It merges new records with the previous snapshot, so omission from Discord's current response never removes a prior entry. A publisher run with no additions writes no files and makes no commit.

The private feed is stored under `catalog/published/` for GitHub Contents API reads. Revision 1 is a full bootstrap snapshot and has no delta; its manifest pointer uses `"latest_delta": null`:

```json
{"schema_version":1,"feed":"autocomplete-public-catalog","revision":1,"entry_count":345,"snapshot":{"path":"snapshots/catalog-v00000001.json","sha256":"<sha256 of canonical snapshot JSON>"},"latest_delta":null}
```

Every revision has an immutable full snapshot at `snapshots/catalog-vNNNNNNNN.json`, with `schema_version`, `feed`, `revision`, `entry_count`, sorted `entries`, and `sha256` (SHA-256 of canonical sorted entries JSON). Starting at revision 2, each revision also has an immutable delta at `deltas/delta-NNNNNNNN.json`, with `from_revision` equal to the preceding revision, `to_revision`, sorted `operations` (`{"op":"add","entry":...}` only), and `sha256` (SHA-256 of the same delta object without its `sha256` field). Thus the first delta advances 1 to 2; revision 1 has no synthetic 0-to-1 delta. The pointer hashes each referenced file's canonical JSON bytes, excluding the final newline. A client without a base fetches the snapshot. A client with an older revision fetches each missing numbered delta in order and verifies its hash before applying additions. Never apply a delta with a gap or a conflicting existing ID. If the manifest revision equals the local revision, no payload file is needed.
