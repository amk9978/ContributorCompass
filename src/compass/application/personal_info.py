import datetime
from collections import defaultdict

from compass.adapters import GitHubClient, TopicRepoRecord
from compass.domain import TopicProject

ACTIVITY_WINDOW_DAYS = 3 * 365


def rank_frequencies(frequencies: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(
        frequencies.items(),
        key=lambda item: item[1],
        reverse=True,
    )


def parse_timestamp(value: str | None) -> datetime.datetime | None:
    if not value:
        return None

    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_topics_frequencies(
    github_handle: str,
    github: GitHubClient,
) -> list[tuple[str, int]]:
    frequencies: defaultdict[str, int] = defaultdict(int)

    now = datetime.datetime.now(datetime.UTC)
    cutoff = now - datetime.timedelta(days=ACTIVITY_WINDOW_DAYS)

    for repo in github.user_repos(github_handle=github_handle):
        updated_at = parse_timestamp(repo.get("updated_at"))

        if updated_at is None:
            continue

        if updated_at < cutoff:
            continue

        for topic in repo.get("topics", []):
            frequencies[topic] += 1

    return rank_frequencies(frequencies)


def build_topic_project(record: TopicRepoRecord) -> TopicProject:
    return TopicProject(
        owner=record["owner"],
        name=record["name"],
        url=record["url"],
        description=record["description"],
        stars=record["stars"],
        forks=record["forks"],
        language=record["language"],
        topics=record["topics"],
        updated_at=parse_timestamp(record["updated_at"]),
    )


def get_topic_projects(
    topic: str,
    github: GitHubClient,
    max_pages: int = 5,
) -> list[TopicProject]:
    projects: list[TopicProject] = []
    seen: set[str] = set()

    for records in github.iter_topic_repos(topic=topic, max_pages=max_pages):
        fresh = [record for record in records if record["url"] not in seen]

        if not fresh:
            break

        seen.update(record["url"] for record in fresh)
        projects.extend(build_topic_project(record=record) for record in fresh)

    return projects
