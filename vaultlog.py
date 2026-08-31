#!/usr/bin/env python3
"""VaultLog — a dependency-free, append-only JSON key-value store.

Run ``python3 vaultlog.py --help``.  This file uses only the Python standard
library and is deliberately self-contained for the Zero Dependency hackathon.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

VERSION = "1.0.0"
ZERO_HASH = "0" * 64
MAX_KEY_BYTES = 512
MAX_VALUE_BYTES = 1_000_000


class VaultError(Exception):
    """A user-facing database or request error."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(previous: str, record: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in record.items() if key != "hash"}
    return hashlib.sha256((previous + canonical(unsigned)).encode("utf-8")).hexdigest()


def checked_key(key: str) -> str:
    if not key or len(key.encode("utf-8")) > MAX_KEY_BYTES:
        raise VaultError(f"key must be 1–{MAX_KEY_BYTES} UTF-8 bytes")
    if any(ord(char) < 32 for char in key):
        raise VaultError("key cannot contain control characters")
    return key


def checked_value(value: Any) -> Any:
    try:
        encoded = canonical(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VaultError("value must be valid JSON") from exc
    if len(encoded) > MAX_VALUE_BYTES:
        raise VaultError(f"value exceeds {MAX_VALUE_BYTES:,} bytes")
    return value


class DirectoryLock:
    """Cross-platform process lock using atomic directory creation."""

    def __init__(self, target: Path, timeout: float = 5.0) -> None:
        self.path = target.with_name(target.name + ".lock")
        self.timeout = timeout

    def __enter__(self) -> "DirectoryLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.path.mkdir()
                (self.path / "owner").write_text(str(os.getpid()), encoding="ascii")
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise VaultError(f"database is busy ({self.path}); try again shortly")
                time.sleep(0.03)

    def __exit__(self, *_: object) -> None:
        try:
            shutil.rmtree(self.path)
        except FileNotFoundError:
            pass


class VaultLog:
    """Replayable append-only store with a SHA-256 hash chain and fsync writes."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self._mutex = threading.RLock()

    def _records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        previous = ZERO_HASH
        with self.path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict) or record.get("prev") != previous:
                        raise ValueError("broken previous hash")
                    if record.get("hash") != digest(previous, record):
                        raise ValueError("invalid record hash")
                    if record.get("op") not in {"set", "delete"} or not isinstance(record.get("key"), str):
                        raise ValueError("invalid record shape")
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    raise VaultError(f"integrity error at line {number}: {exc}") from exc
                previous = record["hash"]
                yield record

    def replay(self) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        state: dict[str, Any] = {}
        history: list[dict[str, Any]] = []
        previous = ZERO_HASH
        for record in self._records() or ():
            history.append(record)
            previous = record["hash"]
            if record["op"] == "set":
                state[record["key"]] = record["value"]
            else:
                state.pop(record["key"], None)
        return state, previous, history

    def append(self, op: str, key: str, value: Any = None) -> dict[str, Any]:
        checked_key(key)
        if op == "set":
            checked_value(value)
        with self._mutex, DirectoryLock(self.path):
            _, previous, _ = self.replay()
            record: dict[str, Any] = {"v": 1, "op": op, "key": key, "at_ns": time.time_ns(), "prev": previous}
            if op == "set":
                record["value"] = value
            record["hash"] = digest(previous, record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            encoded = (canonical(record) + "\n").encode("utf-8")
            fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
            return record

    def verify(self) -> dict[str, Any]:
        state, last_hash, history = self.replay()
        return {"ok": True, "records": len(history), "keys": len(state), "head": last_hash}


def parse_json(text: str) -> Any:
    try:
        return checked_value(json.loads(text))
    except json.JSONDecodeError as exc:
        raise VaultError(f"invalid JSON: {exc.msg}") from exc


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def deterministic_build(source: Path, output: Path) -> None:
    """Build a byte-identical zipapp by pinning every ZIP metadata field."""
    source_bytes = source.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = {"__main__.py": source_bytes, "vaultlog.py": source_bytes}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100755 << 16
            archive.writestr(info, entries[name], compresslevel=9)
    print(hashlib.sha256(output.read_bytes()).hexdigest(), output)


class API(BaseHTTPRequestHandler):
    vault: VaultLog
    token: str | None

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[vaultlog] " + fmt % args + "\n")

    def _send(self, status: int, body: Any) -> None:
        raw = canonical(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _allowed(self) -> bool:
        if not self.token:
            return True
        return self.headers.get("Authorization") == "Bearer " + self.token

    def _key(self) -> str | None:
        parsed = urllib.parse.urlsplit(self.path)
        prefix = "/v1/keys/"
        if not parsed.path.startswith(prefix):
            return None
        return urllib.parse.unquote(parsed.path[len(prefix):])

    def _body(self) -> Any:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > MAX_VALUE_BYTES:
            raise VaultError("request body must be between 1 and 1,000,000 bytes")
        try:
            return checked_value(json.loads(self.rfile.read(size)))
        except json.JSONDecodeError as exc:
            raise VaultError("request body must be JSON") from exc

    def do_GET(self) -> None:
        try:
            if not self._allowed():
                self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"}); return
            parsed = urllib.parse.urlsplit(self.path)
            state, _, _ = self.vault.replay()
            if parsed.path == "/health": self._send(HTTPStatus.OK, self.vault.verify()); return
            if parsed.path == "/v1/keys": self._send(HTTPStatus.OK, {"keys": sorted(state), "count": len(state)}); return
            key = self._key()
            if key is not None:
                checked_key(key)
                if key not in state: self._send(HTTPStatus.NOT_FOUND, {"error": "key not found"}); return
                self._send(HTTPStatus.OK, {"key": key, "value": state[key]}); return
            self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})
        except VaultError as exc: self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_PUT(self) -> None:
        try:
            if not self._allowed(): self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"}); return
            key = self._key()
            if key is None: self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"}); return
            self.vault.append("set", key, self._body())
            self._send(HTTPStatus.OK, {"ok": True, "key": key})
        except VaultError as exc: self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_DELETE(self) -> None:
        try:
            if not self._allowed(): self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"}); return
            key = self._key()
            if key is None: self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"}); return
            self.vault.append("delete", key)
            self._send(HTTPStatus.OK, {"ok": True, "key": key})
        except VaultError as exc: self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        vault = VaultLog(Path(directory) / "test.vaultlog")
        vault.append("set", "user:1", {"name": "Asha", "active": True})
        vault.append("set", "count", 2)
        vault.append("delete", "count")
        state, _, history = vault.replay()
        assert state == {"user:1": {"name": "Asha", "active": True}}
        assert len(history) == 3 and vault.verify()["ok"]
        tampered = vault.path.read_text(encoding="utf-8").replace("Asha", "Evil")
        vault.path.write_text(tampered, encoding="utf-8")
        try: vault.verify()
        except VaultError: pass
        else: raise AssertionError("tampering was not detected")
    print("self-test: OK")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dependency-free append-only JSON key-value store")
    p.add_argument("--db", default="vaultlog.db.jsonl", help="database path (default: %(default)s)")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("set", "get", "delete", "history"):
        q = sub.add_parser(name)
        q.add_argument("key")
        if name == "set": q.add_argument("value", help="JSON value")
    sub.add_parser("list")
    sub.add_parser("verify")
    ex = sub.add_parser("export"); ex.add_argument("--output", default="-")
    im = sub.add_parser("import"); im.add_argument("input", help="JSON object file")
    srv = sub.add_parser("serve"); srv.add_argument("--host", default="127.0.0.1"); srv.add_argument("--port", type=int, default=8787); srv.add_argument("--token")
    b = sub.add_parser("build"); b.add_argument("--output", default="dist/vaultlog.pyz")
    sub.add_parser("self-test")
    return p


def main() -> int:
    args = parser().parse_args()
    if args.command == "build": deterministic_build(Path(__file__), Path(args.output)); return 0
    if args.command == "self-test": self_test(); return 0
    vault = VaultLog(Path(args.db))
    try:
        if args.command == "set": emit({"ok": True, "record": vault.append("set", args.key, parse_json(args.value))})
        elif args.command == "get":
            state, _, _ = vault.replay()
            if args.key not in state: raise VaultError("key not found")
            emit({"key": args.key, "value": state[args.key]})
        elif args.command == "delete": emit({"ok": True, "record": vault.append("delete", args.key)})
        elif args.command == "list":
            state, _, _ = vault.replay(); emit({"keys": sorted(state), "count": len(state)})
        elif args.command == "history":
            _, _, records = vault.replay(); emit([r for r in records if r["key"] == args.key])
        elif args.command == "verify": emit(vault.verify())
        elif args.command == "export":
            state, _, _ = vault.replay(); payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.output == "-": print(payload, end="")
            else: Path(args.output).write_text(payload, encoding="utf-8"); print(args.output)
        elif args.command == "import":
            incoming = parse_json(Path(args.input).read_text(encoding="utf-8"))
            if not isinstance(incoming, dict): raise VaultError("import file must contain a JSON object")
            for key, value in incoming.items(): vault.append("set", key, value)
            emit({"ok": True, "imported": len(incoming)})
        elif args.command == "serve":
            API.vault, API.token = vault, args.token
            server = ThreadingHTTPServer((args.host, args.port), API)
            print(f"VaultLog API listening on http://{args.host}:{args.port}")
            server.serve_forever()
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
