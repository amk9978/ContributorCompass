import datetime
import os
from pathlib import Path

from dotenv import load_dotenv

PERSONAL_TOPIC_FILE = Path("personal_topics.json")
PROJECT_TOPICS_DIR = Path("project_topics")

PERSONAL_TOPICS_STALE_AFTER = datetime.timedelta(days=30)
PROJECT_TOPICS_STALE_AFTER = datetime.timedelta(days=7)

PERSONAL_TOPICS_REFRESH_AFTER = datetime.timedelta(days=25)
PROJECT_TOPICS_REFRESH_AFTER = datetime.timedelta(days=5)


def resolve_github_token() -> str | None:
    load_dotenv()

    return os.environ.get("GITHUB_TOKEN") or None
