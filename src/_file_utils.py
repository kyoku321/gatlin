"""Internal file-system utilities."""

import os
import tempfile
from pathlib import Path


def _atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Write text via a same-directory temporary file and atomic replacement.

    Args:
        path: Destination path.
        content: Text content to write.
        mode: Final POSIX mode of the written file. tempfile.NamedTemporaryFile
            creates files as 0o600; pass 0o644 for content that must be
            readable by other users (e.g. the viewer pod's non-root nginx
            worker reading summary markdown off a shared PVC).
    """
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            os.chmod(temp_path, mode)
            temp_file.write(content)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
