import datetime
import logging
from collections import defaultdict

from compass.adapters import GitHubClient, TopicRepoRecord
from compass.domain import CollectionStop, TopicCollection, TopicProject

logger = logging.getLogger(__name__)

ACTIVITY_WINDOW_DAYS = 3 * 365

STAR_FLOOR = 500
FORK_GATE = 50
SATURATION_YIELD = 25
SATURATION_PAGES = 2
EXTENSION_YIELD = 50
EXTENSION_WINDOW = 2
DEFAULT_MAX_PAGES = 10
HARD_MAX_PAGES = 20


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


def count_gate_passers(records: list[TopicRepoRecord]) -> int:
    return sum(1 for record in records if record["forks"] >= FORK_GATE)


def above_star_floor(records: list[TopicRepoRecord]) -> list[TopicRepoRecord]:
    return [record for record in records if record["stars"] >= STAR_FLOOR]


def extension_earned(recent_yields: list[int]) -> bool:
    if len(recent_yields) < EXTENSION_WINDOW:
        return False

    return all(page_yield >= EXTENSION_YIELD for page_yield in recent_yields)


def resolve_stop(
    pages_fetched: int,
    low_yield_streak: int,
    recent_yields: list[int],
    page_floor_stars: int,
) -> CollectionStop | None:
    if low_yield_streak >= SATURATION_PAGES:
        return CollectionStop.SATURATED

    if page_floor_stars < STAR_FLOOR:
        return CollectionStop.STAR_FLOOR

    if pages_fetched == DEFAULT_MAX_PAGES and not extension_earned(recent_yields):
        return CollectionStop.DEFAULT_DEPTH

    return None


def get_topic_projects(topic: str, github: GitHubClient) -> TopicCollection:
    projects: list[TopicProject] = []
    seen: set[str] = set()
    recent_yields: list[int] = []
    low_yield_streak = 0
    pages_fetched = 0
    stop = CollectionStop.EXHAUSTED

    for records in github.iter_topic_repos(topic=topic, max_pages=HARD_MAX_PAGES):
        pages_fetched += 1

        fresh = [record for record in records if record["url"] not in seen]
        seen.update(record["url"] for record in fresh)
        projects.extend(build_topic_project(record=record) for record in above_star_floor(fresh))

        page_yield = count_gate_passers(records)
        recent_yields = [*recent_yields, page_yield][-EXTENSION_WINDOW:]
        low_yield_streak = low_yield_streak + 1 if page_yield < SATURATION_YIELD else 0

        reason = resolve_stop(
            pages_fetched=pages_fetched,
            low_yield_streak=low_yield_streak,
            recent_yields=recent_yields,
            page_floor_stars=min(record["stars"] for record in records),
        )

        if reason is not None:
            stop = reason
            break
    else:
        stop = (
            CollectionStop.PAGE_BUDGET
            if pages_fetched >= HARD_MAX_PAGES
            else CollectionStop.EXHAUSTED
        )

    logger.info(
        "Collected %s projects for topic %s over %s pages, stopped on %s",
        len(projects),
        topic,
        pages_fetched,
        stop,
    )

    return TopicCollection(projects=projects, stop_reason=stop, pages_fetched=pages_fetched)
