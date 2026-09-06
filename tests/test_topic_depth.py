from collections.abc import Iterator

from compass.adapters import GitHubClient, TopicRepoRecord
from compass.application.personal_info import get_topic_projects
from compass.domain import CollectionStop


def make_page(page_number: int, stars: int, forks: int, gate_passers: int) -> list[TopicRepoRecord]:
    records: list[TopicRepoRecord] = []

    for index in range(100):
        records.append(
            TopicRepoRecord(
                owner="owner",
                name=f"repo-{page_number}-{index}",
                url=f"https://github.com/owner/repo-{page_number}-{index}",
                description=None,
                stars=stars,
                forks=forks if index < gate_passers else 1,
                language=None,
                topics=[],
                updated_at=None,
            )
        )

    return records


class FakeGitHub(GitHubClient):
    def __init__(self, pages: list[list[TopicRepoRecord]]) -> None:
        self.pages = pages
        self.pages_served = 0

    def iter_topic_repos(
        self,
        topic: str,
        max_pages: int = 5,
    ) -> Iterator[list[TopicRepoRecord]]:
        for page in self.pages[:max_pages]:
            self.pages_served += 1
            yield page


def test_saturation_needs_two_consecutive_low_pages() -> None:
    pages = [
        make_page(1, stars=5000, forks=200, gate_passers=100),
        make_page(2, stars=4000, forks=200, gate_passers=20),
        make_page(3, stars=3000, forks=200, gate_passers=90),
        make_page(4, stars=2000, forks=200, gate_passers=10),
        make_page(5, stars=1500, forks=200, gate_passers=10),
        make_page(6, stars=1400, forks=200, gate_passers=90),
    ]
    github = FakeGitHub(pages)

    collection = get_topic_projects(topic="anything", github=github)

    assert collection.stop_reason is CollectionStop.SATURATED
    assert collection.pages_fetched == 5
    assert github.pages_served == 5


def test_star_floor_stops_on_the_first_crossing_page() -> None:
    pages = [
        make_page(1, stars=5000, forks=200, gate_passers=100),
        make_page(2, stars=499, forks=200, gate_passers=100),
        make_page(3, stars=400, forks=200, gate_passers=100),
    ]
    github = FakeGitHub(pages)

    collection = get_topic_projects(topic="anything", github=github)

    assert collection.stop_reason is CollectionStop.STAR_FLOOR
    assert collection.pages_fetched == 2
    assert len(collection.projects) == 100


def test_default_depth_stops_at_ten_when_extension_is_not_earned() -> None:
    pages = [make_page(number, stars=5000, forks=200, gate_passers=40) for number in range(1, 21)]
    github = FakeGitHub(pages)

    collection = get_topic_projects(topic="anything", github=github)

    assert collection.stop_reason is CollectionStop.DEFAULT_DEPTH
    assert collection.pages_fetched == 10


def test_strong_yield_extends_to_the_page_budget() -> None:
    pages = [make_page(number, stars=5000, forks=200, gate_passers=100) for number in range(1, 21)]
    github = FakeGitHub(pages)

    collection = get_topic_projects(topic="anything", github=github)

    assert collection.stop_reason is CollectionStop.PAGE_BUDGET
    assert collection.pages_fetched == 20
    assert len(collection.projects) == 2000


def test_extension_is_judged_once_and_saturation_governs_afterwards() -> None:
    strong = [make_page(number, stars=5000, forks=200, gate_passers=100) for number in range(1, 11)]
    weak = [make_page(number, stars=4000, forks=200, gate_passers=40) for number in range(11, 21)]
    github = FakeGitHub([*strong, *weak])

    collection = get_topic_projects(topic="anything", github=github)

    assert collection.stop_reason is CollectionStop.PAGE_BUDGET
    assert collection.pages_fetched == 20


def test_running_out_of_results_reads_as_exhausted() -> None:
    pages = [
        make_page(1, stars=5000, forks=200, gate_passers=100),
        make_page(2, stars=4000, forks=200, gate_passers=100),
    ]
    github = FakeGitHub(pages)

    collection = get_topic_projects(topic="anything", github=github)

    assert collection.stop_reason is CollectionStop.EXHAUSTED
    assert collection.pages_fetched == 2


def test_projects_below_the_star_floor_are_not_kept() -> None:
    page = make_page(1, stars=5000, forks=200, gate_passers=100)
    page[0]["stars"] = 100
    github = FakeGitHub([page])

    collection = get_topic_projects(topic="anything", github=github)

    assert len(collection.projects) == 99
