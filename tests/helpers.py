from __future__ import annotations

import tempfile
from pathlib import Path

from paperdesk.app import Application
from paperdesk.config import AppPaths
from paperdesk.infrastructure.secrets import MemorySecretStore
from paperdesk.infrastructure.settings_store import MemorySettingsStore
from paperdesk.platforms import LinuxPlatform
from paperdesk.ports.settings import Settings
from paperdesk.providers.registry import default_registry
from .fixtures import DemoProvider


# Turns a current library database into a real version-3 one (before conversations, preferences, jobs and paper details).
DOWNGRADE_TO_V3 = ("".join(f"ALTER TABLE documents DROP COLUMN {column}; " for column in
                           ("authors", "year", "venue", "doi", "arxiv_id", "field", "info_checked_at"))
                   + "DROP TABLE translation_jobs; DROP TABLE conversations; DROP TABLE preferences; PRAGMA user_version = 3;")


def make_pdf(lines: list[str]) -> bytes:
    """Smallest valid one-page PDF with real text (Helvetica), so pdf.js can extract it."""
    stream_lines = ["BT", "/F1 14 Tf", "72 740 Td", "18 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_lines.append(f"({safe}) Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def build_app(**overrides) -> tuple[Application, tempfile.TemporaryDirectory]:
    folder = tempfile.TemporaryDirectory()
    registry = default_registry()
    registry.register(DemoProvider)
    options = dict(
        paths=AppPaths(Path(folder.name)),
        secrets=MemorySecretStore(),
        settings_store=MemorySettingsStore(Settings(target_language="Korean")),
        platform=LinuxPlatform(),
        registry=registry,
    )
    options.update(overrides)
    return Application.build(**options), folder

