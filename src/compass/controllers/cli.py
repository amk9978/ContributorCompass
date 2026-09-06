import datetime
import json
import os
from pathlib import Path
from typing import Annotated

import pydantic
import typer
from dotenv import load_dotenv

from compass.adapters import GitHubClient
from compass.application import get_topic_projects, get_topics_frequencies
from compass.domain import CacheFile, PersonalTopicsFile, TopicProject

app = typer.Typer()

TOPICS_FILE = Path("topics.json")
PERSONAL_TOPIC_FILE = Path("personal_topics.json")
PROJECT_TOPIC_FILE = Path("project_topics.json")
TEST_TOPIC = "github-actions"
PERSONAL_TOPICS_STALE_AFTER = datetime.timedelta(days=30)
PROJECT_TOPICS_STALE_AFTER = datetime.timedelta(days=7)


def resolve_github_token() -> str:
    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")

    if not token:
        typer.echo("GITHUB_TOKEN is not set", err=True)
        raise typer.Exit(code=1)

    return token


def format_github_handle(github_handle: str) -> str:
    formatted_handle = github_handle.replace("https://github.com/", "")
    formatted_handle = formatted_handle.replace("http://github.com/", "")
    formatted_handle = formatted_handle.replace("github.com/", "")
    formatted_handle = formatted_handle.replace("@", "")
    return formatted_handle.lower()


def load_cache_file[CachedT: CacheFile](
    model: type[CachedT],
    file_path: Path,
) -> CachedT | None:
    try:
        return model.model_validate_json(file_path.read_bytes())
    except FileNotFoundError:
        return None
    except pydantic.ValidationError:
        typer.echo(f"Discarding unreadable cache at {file_path}", err=True)
        return None


def write_cache_file(cache_file: CacheFile, file_path: Path) -> None:
    temp_file = file_path.with_suffix(".json.tmp")

    with temp_file.open("w") as file:
        file.write(cache_file.model_dump_json(indent=4))
        file.flush()
        os.fsync(file.fileno())

    os.replace(temp_file, file_path)


def load_fresh_personal_topics(github_handle: str) -> PersonalTopicsFile | None:
    cached = load_cache_file(PersonalTopicsFile, PERSONAL_TOPIC_FILE)

    if cached is None:
        return None

    if cached.github_handle != github_handle:
        return None

    if cached.is_stale(PERSONAL_TOPICS_STALE_AFTER):
        return None

    return cached


def collect_topics(
    github_handle: str,
    github: GitHubClient,
) -> PersonalTopicsFile:
    formatted_github_handle = format_github_handle(github_handle)
    cached = load_fresh_personal_topics(github_handle=formatted_github_handle)

    if cached is not None:
        return cached

    typer.echo(f"Fetching your topics at {formatted_github_handle}...")

    topics = get_topics_frequencies(
        github_handle=formatted_github_handle,
        github=github,
    )
    personal_topics = PersonalTopicsFile(
        github_handle=formatted_github_handle,
        topics_frequency=topics,
    )
    write_cache_file(personal_topics, PERSONAL_TOPIC_FILE)

    return personal_topics


@app.command()
def get_topics(
    github_handle: Annotated[str, typer.Argument()],
) -> list[tuple[str, int]]:
    with GitHubClient(token=resolve_github_token()) as github:
        return collect_topics(github_handle=github_handle, github=github).topics_frequency


def load_existing_pages() -> dict[str, list[dict[str, object]]]:
    if not TOPICS_FILE.exists():
        return {}

    with TOPICS_FILE.open() as file:
        pages: dict[str, list[dict[str, object]]] = json.load(file)

    return pages


def write_into_file(topics: dict[str, list[dict[str, object]]]) -> None:
    temp_file = TOPICS_FILE.with_suffix(".json.tmp")

    with temp_file.open("w") as file:
        json.dump(topics, file, indent=4)
        file.flush()
        os.fsync(file.fileno())

    os.replace(temp_file, TOPICS_FILE)


@app.command()
def get_topics_pages(
    github_handle: Annotated[str, typer.Argument()],
) -> dict[str, list[dict[str, object]]]:
    pages = load_existing_pages()

    with GitHubClient(token=resolve_github_token()) as github:
        personal_topics = collect_topics(github_handle=github_handle, github=github)

        for topic, _ in personal_topics.topics_frequency:
            if topic in pages:
                continue
            if topic != TEST_TOPIC:
                continue

            result: list[TopicProject] = get_topic_projects(
                topic=topic,
                github=github,
                max_pages=10,
            )

            pages[topic] = [project.model_dump(mode="json") for project in result]
            write_into_file(pages)

    return pages


def main() -> None:
    app()


if __name__ == "__main__":
    main()
