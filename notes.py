"""NOTES.md helper — newest entry at top."""
from datetime import datetime, timezone
from pathlib import Path

NOTES_FILE = Path("NOTES.md")
HEADER = "# Copytrade activity log\n\n_Auto-generated. Newest entry at top._\n"
_MARKER = "_Auto-generated. Newest entry at top._\n"


def append_entry(title: str, lines: list) -> None:
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")

    block = f"### {time_str} — {title}\n" + "".join(f"- {line}\n" for line in lines)

    content = NOTES_FILE.read_text() if NOTES_FILE.exists() else ""
    if not content.startswith("# Copytrade activity log"):
        content = HEADER + "\n"

    day_marker = f"## {day}\n"
    if day_marker in content:
        # Insert directly under today's header → newest entry on top within the day.
        idx = content.index(day_marker) + len(day_marker)
        content = content[:idx] + "\n" + block + content[idx:]
    elif _MARKER in content:
        # Insert a fresh day section directly under the file header → newest day on top.
        idx = content.index(_MARKER) + len(_MARKER)
        content = content[:idx] + f"\n## {day}\n\n" + block + content[idx:]
    else:
        content += f"\n## {day}\n\n" + block

    NOTES_FILE.write_text(content)
