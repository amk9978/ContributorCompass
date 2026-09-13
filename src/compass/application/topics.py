import datetime
import logging

from compass.adapters import GitHubClient
from compass.application.personal_info import get_topic_projects, get_topics_frequencies
from compass.domain import PersonalTopicsFile, ProjectTopicsFile
from compass.infra import TopicCache, format_github_handle

logger = logging.getLogger(__name__)


def load_fresh_personal_topics(
    github_handle: str,
    cache: TopicCache,
    stale_after: datetime.timedelta,
) -> PersonalTopicsFile | None:
    cached = cache.load_personal()

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
    cache: TopicCache,
    stale_after: datetime.timedelta,
) -> PersonalTopicsFile:
    formatted_github_handle = format_github_handle(github_handle)
    cached = load_fresh_personal_topics(
        github_handle=formatted_github_handle,
        cache=cache,
        stale_after=stale_after,
    )

    if cached is not None:
        return cached

    logger.info("Fetching topics for %s", formatted_github_handle)

    topics = get_topics_frequencies(
        github_handle=formatted_github_handle,
        github=github,
    )
    personal_topics = PersonalTopicsFile(
        github_handle=formatted_github_handle,
        topics_frequency=topics,
    )
    cache.save_personal(personal_topics)

    return personal_topics


def collect_project_topics(
    topic: str,
    github: GitHubClient,
    cache: TopicCache,
    stale_after: datetime.timedelta,
) -> ProjectTopicsFile:
    cached = cache.load_projects(topic)

    if cached is not None and not cached.is_stale(stale_after):
        return cached

    logger.info("Fetching projects for %s", topic)

    collection = get_topic_projects(topic=topic, github=github)
    project_topics = ProjectTopicsFile(
        projects=collection.projects,
        stop_reason=collection.stop_reason,
        pages_fetched=collection.pages_fetched,
    )
    cache.save_projects(topic, project_topics)

    logger.info(
        "%s: %s projects, %s pages, stopped on %s",
        topic,
        len(collection.projects),
        collection.pages_fetched,
        collection.stop_reason,
    )

    return project_topics


def stale_topics_oldest_first(
    topics_frequency: list[tuple[str, int]],
    cache: TopicCache,
    stale_after: datetime.timedelta,
) -> list[str]:
    never_fetched = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    stale: list[tuple[datetime.datetime, int, str]] = []

    for topic, frequency in topics_frequency:
        cached = cache.load_projects(topic)

        if cached is not None and not cached.is_stale(stale_after):
            continue

        update_date = never_fetched if cached is None else cached.update_date
        stale.append((update_date, -frequency, topic))

    return [topic for _, _, topic in sorted(stale)]


def collect_topic_pages(
    github_handle: str,
    github: GitHubClient,
    cache: TopicCache,
    personal_stale_after: datetime.timedelta,
    project_stale_after: datetime.timedelta,
    max_topics: int | None,
) -> None:
    personal_topics = collect_topics(
        github_handle=github_handle,
        github=github,
        cache=cache,
        stale_after=personal_stale_after,
    )
    topics = stale_topics_oldest_first(
        topics_frequency=personal_topics.topics_frequency,
        cache=cache,
        stale_after=project_stale_after,
    )

    for topic in topics[:max_topics]:
        collect_project_topics(
            topic=topic,
            github=github,
            cache=cache,
            stale_after=project_stale_after,
        )
