from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.modules.accounts.local_import import (
    MAX_LOCAL_OAUTH_FILE_BYTES,
    LocalOAuthImportError,
    list_local_oauth_files,
    read_local_oauth_file,
)


def test_list_local_oauth_files_is_top_level_regular_json_only(tmp_path: Path) -> None:
    (tmp_path / "b.JSON").write_bytes(b"{}")
    (tmp_path / "A.json").write_bytes(b'{"tokens": {}}')
    (tmp_path / "ignore.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "hidden.json").write_bytes(b"{}")

    available, files = list_local_oauth_files(tmp_path)

    assert available is True
    assert [(item.name, item.size_bytes) for item in files] == [("A.json", 14), ("b.JSON", 2)]


def test_local_oauth_import_reports_unavailable_directory(tmp_path: Path) -> None:
    available, files = list_local_oauth_files(tmp_path / "missing")

    assert available is False
    assert files == []


@pytest.mark.parametrize(
    "filename",
    ["../auth.json", "nested/auth.json", r"nested\auth.json", ".", "auth.txt", ""],
)
def test_read_local_oauth_file_rejects_unsafe_filenames(tmp_path: Path, filename: str) -> None:
    with pytest.raises(LocalOAuthImportError, match="top-level JSON basename"):
        read_local_oauth_file(tmp_path, filename)


def test_read_local_oauth_file_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * (MAX_LOCAL_OAUTH_FILE_BYTES + 1))

    with pytest.raises(LocalOAuthImportError) as error:
        read_local_oauth_file(tmp_path, path.name)

    assert error.value.code == "oauth_import_file_too_large"


def test_read_local_oauth_file_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    link = tmp_path / "link.json"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symbolic link creation is unavailable")

    with pytest.raises(LocalOAuthImportError) as error:
        read_local_oauth_file(tmp_path, link.name)

    assert error.value.code == "unsafe_oauth_import_file"
