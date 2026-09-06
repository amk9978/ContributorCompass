import datetime
import os
from pathlib import Path
from typing import Annotated

import pydantic
import typer
from dotenv import load_dotenv

from compass.adapters import GitHubClient
from compass.application import get_topic_projects, get_topics_frequencies
from compass.domain import CacheFile, PersonalTopicsFile, ProjectTopicsFile

app = typer.Typer()

PERSONAL_TOPIC_FILE = Path("personal_topics.json")
PROJECT_TOPICS_DIR = Path("project_topics")

PERSONAL_TOPICS_STALE_AFTER = datetime.timedelta(days=30)
PROJECT_TOPICS_STALE_AFTER = datetime.timedelta(days=7)

PERSONAL_TOPICS_REFRESH_AFTER = datetime.timedelta(days=25)
PROJECT_TOPICS_REFRESH_AFTER = datetime.timedelta(days=5)

TOPIC_MAX_PAGES = 2


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


def project_topics_path(topic: str) -> Path:
    return PROJECT_TOPICS_DIR / f"{topic}.json"


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
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_suffix(".json.tmp")

    with temp_file.open("w") as file:
        file.write(cache_file.model_dump_json(indent=4))
        file.flush()
        os.fsync(file.fileno())

    os.replace(temp_file, file_path)


def load_fresh_personal_topics(
    github_handle: str,
    stale_after: datetime.timedelta,
) -> PersonalTopicsFile | None:
    cached = load_cache_file(PersonalTopicsFile, PERSONAL_TOPIC_FILE)

    if cached is None:
        return None

    if cached.github_handle != github_handle:
        return None

    if cached.is_stale(stale_after):
        return None

    return cached


def collect_topics(
    github_handle: str,
    github: GitHubClient,
    stale_after: datetime.timedelta = PERSONAL_TOPICS_STALE_AFTER,
) -> PersonalTopicsFile:
    formatted_github_handle = format_github_handle(github_handle)
    cached = load_fresh_personal_topics(
        github_handle=formatted_github_handle,
        stale_after=stale_after,
    )

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


def collect_project_topics(
    topic: str,
    github: GitHubClient,
    stale_after: datetime.timedelta = PROJECT_TOPICS_STALE_AFTER,
) -> ProjectTopicsFile:
    file_path = project_topics_path(topic)
    cached = load_cache_file(ProjectTopicsFile, file_path)

    if cached is not None and not cached.is_stale(stale_after):
        return cached

    typer.echo(f"Fetching projects for {topic}...")

    projects = get_topic_projects(
        topic=topic,
        github=github,
        max_pages=TOPIC_MAX_PAGES,
    )
    project_topics = ProjectTopicsFile(projects=projects)
    write_cache_file(project_topics, file_path)

    return project_topics


def stale_topics_oldest_first(
    topics_frequency: list[tuple[str, int]],
    stale_after: datetime.timedelta,
) -> list[str]:
    never_fetched = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    stale: list[tuple[datetime.datetime, int, str]] = []

    for topic, frequency in topics_frequency:
        cached = load_cache_file(ProjectTopicsFile, project_topics_path(topic))

        if cached is not None and not cached.is_stale(stale_after):
            continue

        update_date = never_fetched if cached is None else cached.update_date
        stale.append((update_date, -frequency, topic))

    return [topic for _, _, topic in sorted(stale)]


def collect_topic_pages(
    github_handle: str,
    github: GitHubClient,
    personal_stale_after: datetime.timedelta,
    project_stale_after: datetime.timedelta,
    max_topics: int | None,
) -> None:
    personal_topics = collect_topics(
        github_handle=github_handle,
        github=github,
        stale_after=personal_stale_after,
    )
    topics = stale_topics_oldest_first(
        topics_frequency=personal_topics.topics_frequency,
        stale_after=project_stale_after,
    )

    for topic in topics[:max_topics]:
        collect_project_topics(
            topic=topic,
            github=github,
            stale_after=project_stale_after,
        )


@app.command()
def get_topics(
    github_handle: Annotated[str, typer.Argument()],
) -> list[tuple[str, int]]:
    with GitHubClient(token=resolve_github_token()) as github:
        return collect_topics(github_handle=github_handle, github=github).topics_frequency


@app.command()
def get_topics_pages(
    github_handle: Annotated[str, typer.Argument()],
    max_topics: Annotated[int | None, typer.Option()] = None,
) -> None:
    with GitHubClient(token=resolve_github_token()) as github:
        collect_topic_pages(
            github_handle=github_handle,
            github=github,
            personal_stale_after=PERSONAL_TOPICS_STALE_AFTER,
            project_stale_after=PROJECT_TOPICS_STALE_AFTER,
            max_topics=max_topics,
        )


@app.command()
def refresh(
    max_topics: Annotated[int | None, typer.Option()] = None,
) -> None:
    cached = load_cache_file(PersonalTopicsFile, PERSONAL_TOPIC_FILE)

    if cached is None:
        typer.echo(f"No cached handle in {PERSONAL_TOPIC_FILE}", err=True)
        raise typer.Exit(code=1)

    with GitHubClient(token=resolve_github_token()) as github:
        collect_topic_pages(
            github_handle=cached.github_handle,
            github=github,
            personal_stale_after=PERSONAL_TOPICS_REFRESH_AFTER,
            project_stale_after=PROJECT_TOPICS_REFRESH_AFTER,
            max_topics=max_topics,
        )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
