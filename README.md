# VaultLog

**A durable, inspectable local JSON store in one Python file.** VaultLog is a Track D (Data & Storage) entry for the Zero Dependency | 72-Hour Hackathon. It gives small tools and prototypes an append-only, JSON-native persistence layer without installing TinyDB, a database server, or any runtime package.

## One-command build

```sh
python3 vaultlog.py build --output dist/vaultlog.pyz
```

This produces a runnable, deterministic zipapp. Run it with `python3 dist/vaultlog.pyz --help`.

## Quick demo

```sh
python3 vaultlog.py --db demo.vaultlog set user:42 '{"name":"Asha","role":"organizer"}'
python3 vaultlog.py --db demo.vaultlog get user:42
python3 vaultlog.py --db demo.vaultlog verify
python3 vaultlog.py --db demo.vaultlog serve --port 8787
```

In a second terminal:

```sh
curl http://127.0.0.1:8787/v1/keys/user%3A42
curl -X PUT http://127.0.0.1:8787/v1/keys/status -H 'Content-Type: application/json' --data '"ready"'
```

Optional API protection: add `--token change-me` and send `Authorization: Bearer change-me`.

## What it does

- Persists JSON values in an append-only JSON Lines log.
- Replays the log for key retrieval, listing, history, export, and import.
- Uses a SHA-256 hash chain to detect edited, reordered, or broken records.
- Uses an atomic directory lock for competing processes, plus append + `fsync` before acknowledging a write.
- Serves real concurrent HTTP clients via `ThreadingHTTPServer`.
- Produces explicit, machine-readable errors and non-zero exits for invalid input.

The storage format is deliberately human-readable. A record contains an operation, a timestamp, its predecessor hash, and its own hash. VaultLog detects corruption; it does not silently repair or conceal it.

## Commands

`set KEY JSON`, `get KEY`, `delete KEY`, `list`, `history KEY`, `verify`, `export [--output FILE]`, `import FILE`, `serve`, `self-test`, and `build`.

Every command accepts `--db PATH`; the default is `vaultlog.db.jsonl`.

## Reproducible-build proof

Run the documented build command twice to two different output paths:

```sh
python3 vaultlog.py build --output dist/first.pyz
python3 vaultlog.py build --output dist/second.pyz
shasum -a 256 dist/first.pyz dist/second.pyz
```

The builder pins ZIP entry order, timestamps, permissions, compression, and contents, so the two hashes are identical on the same Python version. The final source contains no generated version timestamp.

## Why this belongs in Track D

VaultLog demonstrates persistence, retrieval, durability decisions, data integrity verification, and concurrent-access handling. It is a practical replacement for lightweight document-store dependencies where a small embedded log is enough and operational transparency matters.

## Judging alignment

| Criterion | Evidence |
| --- | --- |
| Functionality & usefulness (35%) | Complete CLI, durable persistence, history, import/export, verification, and HTTP API. |
| Zero-dependency craft (30%) | Only Python standard library; see [STDLIB.md](STDLIB.md). |
| Code quality (25%) | Typed, self-contained source; defensive input limits; clear exit behavior; self-test. |
| Innovation (10%) | Trustworthy JSONL with a hash chain, fsync durability, cross-platform locking, and a deterministic self-builder. |
| Single File (+5) | All executable project logic is in `vaultlog.py`. |
| Reproducible Build (+5) | Deterministic `.pyz` builder and verification recipe above. |
| Package Killer (+3) | Replaces the core persistence workflow commonly reached for with TinyDB. |
| STDLIB Log (+3) | 10+ documented substitutions in `STDLIB.md`. |

## Demo flow (90 seconds)

1. Show `python3 vaultlog.py --help` — it is one source file and needs no installation.
2. `set` a JSON profile, `get` it, then open the `.jsonl` file to show the legible append-only record.
3. Run `verify` and explain that each record commits to the prior record’s hash.
4. Start `serve`; use `curl` to read and update a key.
5. Run the build command twice and show the matching SHA-256 hashes.

## Submission checklist

- Push this folder to a **public GitHub repository** during the official hackathon window.
- Keep this README and `STDLIB.md` in the repository as the dependency proof.
- Run `python3 vaultlog.py self-test` before submitting.
- Add the repository URL and choose **Track D — Data & Storage** in the event form.

## License

MIT. See [LICENSE](LICENSE).
