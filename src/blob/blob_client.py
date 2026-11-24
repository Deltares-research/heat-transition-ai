"""Azure Blob Storage client for the warmteprogramma corpus.

Blob names mirror the local ``data/`` tree, so ``data/corpus/pdfs/almelo.pdf``
is ``corpus/pdfs/almelo.pdf`` in the container. The mapping is reversible and
needs no lookup table, which is what makes push/pull round-trip cleanly.

Credentials live in ``secrets/blob.env``:

    AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
    AZURE_STORAGE_CONTAINER=nplw

Real environment variables win over the file.

Smoke-test with::

    python -m src.blob.blob_client

The class is called ``BlobStore`` rather than ``BlobClient`` so it does not
collide with ``azure.storage.blob.BlobClient`` when both are imported.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.storage.blob import BlobServiceClient, ContainerClient, ContentSettings
from dotenv import load_dotenv

from src.console import safe_console

__all__ = ["BlobStore", "BlobInfo", "SyncReport", "resolve_connection_string"]


ROOT = Path(__file__).parents[2]
ENV_PATH = ROOT / "secrets" / "blob.env"
DATA_ROOT = ROOT / "data"

DEFAULT_CONTAINER = "nplw"

# Azure's own default is 64 MiB; the embedded-chunk JSONL is already 24 MB and
# will grow with the corpus, so uploads are chunked and parallel by default.
MAX_SINGLE_PUT = 16 * 1024 * 1024
MAX_CONCURRENCY = 4
RETRY_TOTAL = 5

_MISSING_CONFIG = f"""No storage connection string found.

Create {ENV_PATH} containing:

    AZURE_STORAGE_CONNECTION_STRING=<portal > storage account > Access keys > Connection string>
    AZURE_STORAGE_CONTAINER=nplw

or set AZURE_STORAGE_ACCOUNT and AZURE_STORAGE_KEY.
See secrets/blob.env.example."""

_AUTH_HINT = """Check, in this order:
  1. the connection string was copied whole (it ends with EndpointSuffix=...),
  2. the access key has not been rotated,
  3. the storage account firewall allows your client IP
     (Networking > Public network access)."""


# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────

def resolve_connection_string(env_path: Path | str = ENV_PATH) -> str:
    """Connection string from the environment, falling back to secrets/blob.env."""
    load_dotenv(env_path)

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn and conn.strip():
        return conn.strip()

    account = os.environ.get("AZURE_STORAGE_ACCOUNT")
    key = os.environ.get("AZURE_STORAGE_KEY")
    if account and key:
        return (
            "DefaultEndpointsProtocol=https;"
            f"AccountName={account};AccountKey={key};"
            "EndpointSuffix=core.windows.net"
        )

    raise RuntimeError(_MISSING_CONFIG)


def resolve_container(env_path: Path | str = ENV_PATH) -> str:
    load_dotenv(env_path)
    return os.environ.get("AZURE_STORAGE_CONTAINER", DEFAULT_CONTAINER)


def describe_connection(conn: str) -> str:
    """Account and endpoint, with the key removed."""
    parts = dict(
        piece.split("=", 1) for piece in conn.split(";") if "=" in piece
    )
    account = parts.get("AccountName", "?")
    suffix = parts.get("EndpointSuffix", "core.windows.net")
    return f"{account}.blob.{suffix}"


# ──────────────────────────────────────────────────────────────
# Value types
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BlobInfo:
    name: str
    size: int
    modified: Any
    md5: bytes | None

    @property
    def human_size(self) -> str:
        value = float(self.size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
            value /= 1024
        return f"{value:,.1f} GB"


@dataclass
class SyncReport:
    transferred: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    bytes_moved: int = 0

    def __str__(self) -> str:
        megabytes = self.bytes_moved / (1024 * 1024)
        return (
            f"{len(self.transferred)} transferred ({megabytes:,.1f} MB), "
            f"{len(self.skipped)} unchanged"
        )


def file_md5(path: Path, buffer: int = 1024 * 1024) -> bytes:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(buffer), b""):
            digest.update(block)
    return digest.digest()


def to_blob_name(path: Path, root: Path = DATA_ROOT) -> str:
    """data/corpus/pdfs/x.pdf -> corpus/pdfs/x.pdf, with forward slashes."""
    return path.resolve().relative_to(root.resolve()).as_posix()


# ──────────────────────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────────────────────

class BlobStore:
    """Container-scoped wrapper over Azure Blob Storage."""

    def __init__(
        self,
        container: str | None = None,
        connection_string: str | None = None,
        env_path: Path | str = ENV_PATH,
        create: bool = True,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        self.connection_string = connection_string or resolve_connection_string(env_path)
        self.container_name = container or resolve_container(env_path)
        self.max_concurrency = max_concurrency

        try:
            self.service = BlobServiceClient.from_connection_string(
                self.connection_string,
                max_single_put_size=MAX_SINGLE_PUT,
                retry_total=RETRY_TOTAL,
                connection_timeout=30,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Malformed connection string: {exc}\n\n{_AUTH_HINT}"
            ) from exc

        self.container: ContainerClient = self.service.get_container_client(
            self.container_name
        )
        if create:
            self.ensure_container()

    @property
    def account(self) -> str:
        return describe_connection(self.connection_string)

    def ensure_container(self) -> None:
        """Create the container if absent. Safe to call repeatedly."""
        try:
            self.container.create_container()
        except ResourceExistsError:
            pass
        except ClientAuthenticationError as exc:
            raise PermissionError(
                f"Authentication failed for {self.account}: {exc}\n\n{_AUTH_HINT}"
            ) from exc
        except AzureError as exc:
            raise ConnectionError(
                f"Could not reach {self.account}: {exc}\n\n{_AUTH_HINT}"
            ) from exc

    def close(self) -> None:
        self.service.close()

    def __enter__(self) -> "BlobStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── inspection ────────────────────────────────────────────

    def exists(self, name: str) -> bool:
        return self.container.get_blob_client(name).exists()

    def list(self, prefix: str = "") -> list[str]:
        return [blob.name for blob in self.container.list_blobs(name_starts_with=prefix)]

    def stat(self, prefix: str = "") -> list[BlobInfo]:
        """Name, size, last-modified and content MD5 for every blob under prefix."""
        return [
            BlobInfo(
                name=blob.name,
                size=blob.size or 0,
                modified=blob.last_modified,
                md5=bytes(blob.content_settings.content_md5)
                if blob.content_settings and blob.content_settings.content_md5
                else None,
            )
            for blob in self.container.list_blobs(name_starts_with=prefix)
        ]

    def delete(self, name: str) -> bool:
        try:
            self.container.delete_blob(name)
            return True
        except ResourceNotFoundError:
            return False

    # ── single blobs ──────────────────────────────────────────

    def upload_file(self, local_path: Path | str, name: str, overwrite: bool = True) -> str:
        """Upload one file, recording its MD5 so sync can detect changes."""
        local_path = Path(local_path)
        guessed, _ = mimetypes.guess_type(local_path.name)
        settings = ContentSettings(
            content_type=guessed or "application/octet-stream",
            content_md5=file_md5(local_path),
        )
        with local_path.open("rb") as handle:
            self.container.upload_blob(
                name=name,
                data=handle,
                overwrite=overwrite,
                content_settings=settings,
                max_concurrency=self.max_concurrency,
            )
        return name

    def download_file(self, name: str, local_path: Path | str) -> Path:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with local_path.open("wb") as handle:
            self.container.download_blob(
                name, max_concurrency=self.max_concurrency
            ).readinto(handle)
        return local_path

    def upload_bytes(
        self,
        data: bytes,
        name: str,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> str:
        self.container.upload_blob(
            name=name,
            data=data,
            overwrite=overwrite,
            content_settings=ContentSettings(
                content_type=content_type,
                content_md5=hashlib.md5(data).digest(),
            ),
        )
        return name

    def download_bytes(self, name: str) -> bytes:
        return self.container.download_blob(name).readall()

    def upload_text(
        self,
        text: str,
        name: str,
        content_type: str = "text/plain; charset=utf-8",
        overwrite: bool = True,
    ) -> str:
        return self.upload_bytes(text.encode("utf-8"), name, content_type, overwrite)

    def download_text(self, name: str) -> str:
        return self.download_bytes(name).decode("utf-8")

    # ── JSONL, the pipeline's working format ──────────────────

    def write_jsonl(self, records: Sequence[dict[str, Any]], name: str) -> str:
        body = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        return self.upload_text(body + "\n", name, "application/x-ndjson")

    def read_jsonl(self, name: str) -> Iterator[dict[str, Any]]:
        for line in self.download_text(name).splitlines():
            if line.strip():
                yield json.loads(line)

    # ── directory sync ────────────────────────────────────────

    def push(
        self,
        local_dir: Path | str = DATA_ROOT,
        prefix: str = "",
        pattern: str = "*",
        root: Path | str = DATA_ROOT,
        force: bool = False,
        dry_run: bool = False,
    ) -> SyncReport:
        """Upload a local tree, skipping blobs whose content already matches."""
        local_dir = Path(local_dir)
        root = Path(root)
        if not local_dir.is_dir():
            raise FileNotFoundError(f"Not a directory: {local_dir}")

        remote = {info.name: info for info in self.stat(prefix)}
        report = SyncReport()

        for path in sorted(local_dir.rglob("*")):
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue

            name = to_blob_name(path, root)
            existing = remote.get(name)
            if not force and existing is not None and self._matches(path, existing):
                report.skipped.append(name)
                continue

            size = path.stat().st_size
            if not dry_run:
                self.upload_file(path, name)
            report.transferred.append(name)
            report.bytes_moved += size

        return report

    def pull(
        self,
        prefix: str = "",
        local_dir: Path | str = DATA_ROOT,
        pattern: str = "*",
        force: bool = False,
        dry_run: bool = False,
    ) -> SyncReport:
        """Download a prefix into a local tree, skipping files that already match."""
        local_dir = Path(local_dir)
        report = SyncReport()

        for info in self.stat(prefix):
            if not fnmatch.fnmatch(Path(info.name).name, pattern):
                continue

            target = local_dir / Path(info.name)
            if not force and target.exists() and self._matches(target, info):
                report.skipped.append(info.name)
                continue

            if not dry_run:
                self.download_file(info.name, target)
            report.transferred.append(info.name)
            report.bytes_moved += info.size

        return report

    @staticmethod
    def _matches(path: Path, info: BlobInfo) -> bool:
        """True when the local file and the blob hold identical bytes.

        Falls back to size alone when the blob carries no MD5 — blobs written
        by other tools often do not.
        """
        if path.stat().st_size != info.size:
            return False
        if info.md5 is None:
            return True
        return file_md5(path) == info.md5


# ──────────────────────────────────────────────────────────────
# Smoke test
# ──────────────────────────────────────────────────────────────

def _check() -> int:
    conn = resolve_connection_string()
    container = resolve_container()
    print(f"account    {describe_connection(conn)}")
    print(f"container  {container}")

    with BlobStore() as store:
        blobs = store.stat()
        print(f"blobs      {len(blobs):,}")

        if not blobs:
            print("\nContainer is empty.")
            return 0

        groups: dict[str, list[BlobInfo]] = {}
        for info in blobs:
            top = info.name.split("/")[0] if "/" in info.name else "(root)"
            groups.setdefault(top, []).append(info)

        print()
        for top, items in sorted(groups.items()):
            total = sum(i.size for i in items)
            print(f"  {top:<16} {len(items):>5} files  {total / 1024 / 1024:>8,.1f} MB")
    return 0


def main() -> int:
    safe_console()
    parser = argparse.ArgumentParser(description="Check the blob storage connection.")
    parser.parse_args()
    try:
        return _check()
    except (RuntimeError, ConnectionError, PermissionError) as exc:
        print(f"\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
