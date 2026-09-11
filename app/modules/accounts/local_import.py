from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_LOCAL_OAUTH_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LocalOAuthFile:
    name: str
    size_bytes: int


class LocalOAuthImportError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def list_local_oauth_files(directory: Path | None) -> tuple[bool, list[LocalOAuthFile]]:
    if not _is_available_directory(directory):
        return False, []

    assert directory is not None
    files: list[LocalOAuthFile] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.name.lower().endswith(".json") or entry.is_symlink():
                    continue
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(entry_stat.st_mode):
                    files.append(LocalOAuthFile(name=entry.name, size_bytes=entry_stat.st_size))
    except OSError:
        return False, []

    files.sort(key=lambda item: (item.name.casefold(), item.name))
    return True, files


def read_local_oauth_file(directory: Path | None, filename: str) -> bytes:
    _validate_filename(filename)
    if not _is_available_directory(directory):
        raise LocalOAuthImportError(
            "Default OAuth import folder is unavailable",
            code="oauth_import_directory_unavailable",
        )

    assert directory is not None
    file_descriptor = _open_regular_file_without_following_links(directory, filename)
    try:
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise LocalOAuthImportError(
                "Selected OAuth import entry is not a regular file",
                code="unsafe_oauth_import_file",
            )
        if file_stat.st_size > MAX_LOCAL_OAUTH_FILE_BYTES:
            raise LocalOAuthImportError(
                "Selected OAuth file exceeds the 2 MiB limit",
                code="oauth_import_file_too_large",
            )

        with os.fdopen(file_descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_LOCAL_OAUTH_FILE_BYTES + 1)
        if len(raw) > MAX_LOCAL_OAUTH_FILE_BYTES:
            raise LocalOAuthImportError(
                "Selected OAuth file exceeds the 2 MiB limit",
                code="oauth_import_file_too_large",
            )
        return raw
    finally:
        os.close(file_descriptor)


def _is_available_directory(directory: Path | None) -> bool:
    if directory is None:
        return False
    try:
        directory_stat = directory.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(directory_stat.st_mode) and not directory.is_symlink()


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or filename in {".", ".."}
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
        or not filename.lower().endswith(".json")
    ):
        raise LocalOAuthImportError(
            "OAuth import filename must be a top-level JSON basename",
            code="unsafe_oauth_import_filename",
        )


def _open_regular_file_without_following_links(directory: Path, filename: str) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        if os.open in os.supports_dir_fd:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            directory_descriptor = os.open(directory, directory_flags)
            try:
                return os.open(filename, flags, dir_fd=directory_descriptor)
            finally:
                os.close(directory_descriptor)

        target = directory / filename
        target_stat = target.lstat()
        if stat.S_ISLNK(target_stat.st_mode):
            raise LocalOAuthImportError(
                "Symbolic links cannot be imported",
                code="unsafe_oauth_import_file",
            )
        return os.open(target, flags)
    except LocalOAuthImportError:
        raise
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise LocalOAuthImportError(
            "Selected OAuth file was not found",
            code="oauth_import_file_not_found",
        ) from exc
    except OSError as exc:
        raise LocalOAuthImportError(
            "Selected OAuth file could not be opened safely",
            code="unsafe_oauth_import_file",
        ) from exc
