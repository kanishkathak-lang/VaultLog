# Standard-library dependency proof

VaultLog has **zero third-party runtime dependencies**. It runs on Python 3.10+ using only the standard library. There is no `requirements.txt`, `pyproject.toml`, package manager command, vendored dependency, or copied third-party source.

## Meaningful standard-library-for-package substitutions

| Common package / external service | VaultLog standard-library replacement | Where it is used |
| --- | --- | --- |
| TinyDB | `json` + append-only JSON Lines + replay | Embedded JSON document persistence |
| filelock / portalocker | `pathlib.Path.mkdir()` atomic directory lock | Cross-process writer exclusion |
| cryptography integrity helper | `hashlib.sha256` | Tamper-evident record hash chain |
| Flask / FastAPI | `http.server.ThreadingHTTPServer` | Concurrent HTTP API |
| Requests-style JSON decoding | `json.loads` / `json.dumps` | HTTP request and response payloads |
| Click / Typer | `argparse` | CLI, help, and argument validation |
| Pydantic | explicit validation functions | JSON, key, size, and request checks |
| python-dotenv | command-line `--token` | Explicit, deployment-safe API configuration |
| uvicorn / gunicorn (small local service) | `ThreadingHTTPServer` | Serving real concurrent clients |
| zipapp / build backend | `zipfile.ZipFile` with fixed metadata | Deterministic runnable artifact |
| pytest | built-in assertions + `tempfile` | Isolated self-test |
| platform-specific fsync helpers | `os.open`, `os.write`, `os.fsync` | Durable append before acknowledgement |
| URL router | `urllib.parse` | Percent-decoded HTTP key paths |
| shell utilities | `shutil` | Lock cleanup |

## Development dependencies

None. The shipped self-test uses only the standard library:

```sh
python3 vaultlog.py self-test
```

## Runtime declaration

- Language: Python 3.10 or newer
- Runtime packages: **none**
- Network services required: **none**
- Database required: **none**

Python's `hashlib` is used for integrity checking, not encryption. VaultLog does not claim confidentiality; sensitive data should be protected with operating-system file permissions and an appropriate encrypted storage solution when needed.
