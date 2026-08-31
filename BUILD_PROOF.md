# Reproducible build proof

Build command:

```sh
python3 vaultlog.py build --output dist/first.pyz
python3 vaultlog.py build --output dist/second.pyz
```

Observed SHA-256 for both artifacts:

```text
821ed4ce1b2f767f102aa345895b449b1718eb734d13cb1cd3809cc48e9654df  dist/first.pyz
821ed4ce1b2f767f102aa345895b449b1718eb734d13cb1cd3809cc48e9654df  dist/second.pyz
```

The build function fixes file order, ZIP timestamps, permissions, and compression parameters. Re-run this proof after any source change; the hash is expected to change across source revisions but match between the two builds of one revision.
