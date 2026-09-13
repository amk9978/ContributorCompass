import logging
from typing import Annotated

import typer

from compass.adapters import GitHubClient
from compass.application.topics import collect_topic_pages, collect_topics
from compass.infra import (
    PERSONAL_TOPIC_FILE,
    PERSONAL_TOPICS_REFRESH_AFTER,
    PERSONAL_TOPICS_STALE_AFTER,
    PROJECT_TOPICS_DIR,
    PROJECT_TOPICS_REFRESH_AFTER,
    PROJECT_TOPICS_STALE_AFTER,
    TopicCache,
    resolve_github_token,
)

app = typer.Typer()
cache = TopicCache(personal_file=PERSONAL_TOPIC_FILE, project_dir=PROJECT_TOPICS_DIR)


def require_github_token() -> str:
    token = resolve_github_token()

    if token is None:
        typer.echo("GITHUB_TOKEN is not set", err=True)
        raise typer.Exit(code=1)

    return token


@app.command()
def get_topics(
    github_handle: Annotated[str, typer.Argument()],
) -> list[tuple[str, int]]:
    with GitHubClient(token=require_github_token()) as github:
        return collect_topics(
            github_handle=github_handle,
            github=github,
            cache=cache,
            stale_after=PERSONAL_TOPICS_STALE_AFTER,
        ).topics_frequency


@app.command()
def get_topics_pages(
    github_handle: Annotated[str, typer.Argument()],
    max_topics: Annotated[int | None, typer.Option()] = None,
) -> None:
    with GitHubClient(token=require_github_token()) as github:
        collect_topic_pages(
            github_handle=github_handle,
            github=github,
            cache=cache,
            personal_stale_after=PERSONAL_TOPICS_STALE_AFTER,
            project_stale_after=PROJECT_TOPICS_STALE_AFTER,
            max_topics=max_topics,
        )


@app.command()
def refresh(
    max_topics: Annotated[int | None, typer.Option()] = None,
) -> None:
    cached = cache.load_personal()

    if cached is None:
        typer.echo(f"No cached handle in {PERSONAL_TOPIC_FILE}", err=True)
        raise typer.Exit(code=1)

    with GitHubClient(token=require_github_token()) as github:
        collect_topic_pages(
            github_handle=cached.github_handle,
            github=github,
            cache=cache,
            personal_stale_after=PERSONAL_TOPICS_REFRESH_AFTER,
            project_stale_after=PROJECT_TOPICS_REFRESH_AFTER,
            max_topics=max_topics,
        )


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("compass").setLevel(logging.INFO)
    app()


if __name__ == "__main__":
    main()
