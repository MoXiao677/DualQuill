"""Create a fresh, fictional S1 navigation fixture using the existing data contracts.

This is intentionally one project save with one entity snapshot per chapter. It
measures S1 loaded navigation, not the cumulative storage benchmark planned in S2.
The caller owns the temporary database and must remove it after the browser exits.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from novel_writer.application import projects, versions
from novel_writer.application.service import NovelService
from novel_writer.domain.models import Chapter
from novel_writer.storage.json_codec import document_from_dict, document_to_dict
from novel_writer.storage.sqlite_repository import SQLiteRepository


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: s1-performance.py <fresh temporary database path>")
    database = Path(sys.argv[1]).resolve()
    if database.exists() or database == ROOT or ROOT in database.parents:
        raise SystemExit("Fixture requires a new database outside the repository")

    state = projects.create({"title": "S1 虚构性能验收·" + "雾港来信与远方灯塔的故事" * 9})
    document = document_from_dict(state["document"])
    chinese = "海风吹过虚构港湾少年沿着石阶走向灯塔纸上的字迹在晨光里渐渐清晰"
    body = (chinese * (2000 // len(chinese) + 1))[:2000]
    duplicate_title = "同名章节：雨夜来信"
    long_index = 49
    filter_index = 72
    for index in range(100):
        title = f"虚构章节 {index + 1:03d}：雾港回声"
        if index in (11, 78):
            title = duplicate_title
        elif index == long_index:
            title = "长标题样本：" + "灯塔守望者收到来自远方群岛的匿名来信" * 9
        elif index == filter_index:
            title = "定位样本：潮汐中的手稿"
        chapter = Chapter(
            project_id=document.project.id,
            number=index + 1,
            title=title,
            content=f"虚构性能样本·第 {index + 1:03d} 章\n\n{body}\n",
        )
        document.chapters.append(chapter)
        versions.record(document, "chapter", chapter, "S1 虚构夹具：初始正文")
    state["document"] = document_to_dict(document)
    repository = SQLiteRepository(database)
    saved = repository.create(state)

    # Reopen through the existing application/storage boundary before reporting.
    reopened = NovelService(SQLiteRepository(database)).get(document.project.id)
    assert reopened == saved
    counts = Counter(
        version["entity_id"] for version in reopened["document"]["versions"]
        if version["entity_type"] == "chapter"
    )
    assert counts == Counter({chapter.id: 1 for chapter in document.chapters})
    with sqlite3.connect(database) as connection:
        database_version = connection.execute("PRAGMA user_version").fetchone()[0]
        snapshot_count = connection.execute("SELECT COUNT(*) FROM project_snapshots").fetchone()[0]
    assert database_version == 1 and snapshot_count == 1
    result = {
        "fictional": True,
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "project_id": document.project.id,
        "project_title": document.project.title,
        "chapter_count": len(document.chapters),
        "chinese_characters_per_body": len(body),
        "chapter_snapshots": sum(counts.values()),
        "project_snapshots": snapshot_count,
        "schema_version": document.schema_version,
        "workspace_version": reopened["workspace_version"],
        "database_version": database_version,
        "database_bytes": database.stat().st_size,
        "long_title_chapter_id": document.chapters[long_index].id,
        "filter_chapter_id": document.chapters[filter_index].id,
        "duplicate_title": duplicate_title,
        "duplicate_chapter_ids": [document.chapters[index].id for index in (11, 78)],
        "chapters": [
            {"id": chapter.id, "number": chapter.number, "title": chapter.title,
             "content_characters": len(chapter.content),
             "content_sha256": hashlib.sha256(chapter.content.encode("utf-8")).hexdigest()}
            for chapter in document.chapters
        ],
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
