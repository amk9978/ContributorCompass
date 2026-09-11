import datetime
from collections.abc import Iterator
from typing import Any, cast

import pydantic
import pytest
from githubkit import GitHub
from githubkit.exception import GitHubException

from compass.adapters import GitHubClient, TopicRepoRecord
from compass.adapters.github import build_repository_evidence
from compass.application.personal_info import get_topic_projects


class ServerError(GitHubException):
    pass


def make_record(index: int) -> TopicRepoRecord:
    return TopicRepoRecord(
        node_id=f"node-{index}",
        owner="owner",
        name=f"repo-{index}",
        url=f"https://github.com/owner/repo-{index}",
        description=None,
        stars=1000,
        forks=100,
        language=None,
        topics=[],
        updated_at=None,
    )


def make_node(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "createdAt": "2020-01-02T03:04:05Z",
        "pushedAt": "2026-09-01T00:00:00Z",
        "isArchived": False,
        "hasIssuesEnabled": True,
        "licenseInfo": {"spdxId": "MIT"},
        "defaultBranchRef": {"name": "main", "target": {"committedDate": "2026-08-31T00:00:00Z"}},
        "latestRelease": {"publishedAt": "2026-07-01T00:00:00Z"},
        "watchers": {"totalCount": 12},
        "openIssues": {"totalCount": 34},
        "goodFirstIssues": {"totalCount": 5},
        "openPullRequests": {"totalCount": 6},
        "languages": {
            "edges": [
                {"size": 1000, "node": {"name": "Python"}},
                {"size": 10, "node": {"name": "Shell"}},
            ]
        },
        "contributingGuide": {"id": "blob"},
    }


def empty_body_error() -> pydantic.ValidationError:
    try:
        pydantic.TypeAdapter(dict[str, Any]).validate_json(b"")
    except pydantic.ValidationError as exc:
        return exc

    raise AssertionError("an empty body must not validate")


class FakeGraphQL:
    def __init__(
        self,
        nodes: dict[str, dict[str, Any]],
        max_batch: int,
        empty_bodies: int = 0,
    ) -> None:
        self.nodes = nodes
        self.max_batch = max_batch
        self.empty_bodies = empty_bodies
        self.batch_sizes: list[int] = []

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        node_ids = variables["ids"]
        self.batch_sizes.append(len(node_ids))

        if self.empty_bodies:
            self.empty_bodies -= 1
            raise empty_body_error()

        if len(node_ids) > self.max_batch:
            raise ServerError("batch too large")

        return {"nodes": [self.nodes.get(node_id) for node_id in node_ids]}


class FakeGitHub(GitHubClient):
    def __init__(
        self,
        records: list[TopicRepoRecord],
        nodes: dict[str, dict[str, Any]],
        max_batch: int = 100,
        empty_bodies: int = 0,
    ) -> None:
        self.records = records
        self.server = FakeGraphQL(nodes=nodes, max_batch=max_batch, empty_bodies=empty_bodies)
        self.github = cast(GitHub[Any], self.server)

    def iter_topic_repos(
        self,
        topic: str,
        max_pages: int = 5,
    ) -> Iterator[list[TopicRepoRecord]]:
        yield self.records


def timestamp(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def test_unresolved_node_keeps_discovery_fields_with_null_evidence() -> None:
    records = [make_record(index) for index in range(3)]
    nodes = {"node-0": make_node("node-0"), "node-2": make_node("node-2")}
    github = FakeGitHub(records=records, nodes=nodes)

    collection = get_topic_projects(topic="anything", github=github)

    assert [project.name for project in collection.projects] == ["repo-0", "repo-1", "repo-2"]
    unresolved = collection.projects[1]
    assert unresolved.stars == 1000
    assert unresolved.pushed_at is None
    assert unresolved.is_archived is None
    assert unresolved.has_issues_enabled is None
    assert collection.projects[0].pushed_at is not None
    assert collection.projects[2].is_archived is False


def test_evidence_fields_land_on_the_project() -> None:
    records = [make_record(0)]
    github = FakeGitHub(records=records, nodes={"node-0": make_node("node-0")})

    project = get_topic_projects(topic="anything", github=github).projects[0]

    assert project.created_at == timestamp("2020-01-02T03:04:05+00:00")
    assert project.pushed_at == timestamp("2026-09-01T00:00:00+00:00")
    assert project.last_commit_at == timestamp("2026-08-31T00:00:00+00:00")
    assert project.latest_release_at == timestamp("2026-07-01T00:00:00+00:00")
    assert project.is_archived is False
    assert project.has_issues_enabled is True
    assert project.license_spdx_id == "MIT"
    assert project.default_branch == "main"
    assert project.watchers_count == 12
    assert project.open_issues_count == 34
    assert project.open_good_first_issue_count == 5
    assert project.open_pr_count == 6
    assert project.language_bytes == {"Python": 1000, "Shell": 10}
    assert project.has_contributing_guide is True


def test_empty_repository_leaves_optional_evidence_null() -> None:
    node = make_node("node-0")
    node.update(
        pushedAt=None,
        licenseInfo=None,
        defaultBranchRef=None,
        latestRelease=None,
        contributingGuide=None,
        languages={"edges": []},
    )

    evidence = build_repository_evidence(node)

    assert evidence["pushed_at"] is None
    assert evidence["license_spdx_id"] is None
    assert evidence["default_branch"] is None
    assert evidence["last_commit_at"] is None
    assert evidence["latest_release_at"] is None
    assert evidence["language_bytes"] == {}
    assert evidence["has_contributing_guide"] is False


def test_failed_batch_is_retried_as_two_halves() -> None:
    records = [make_record(index) for index in range(50)]
    nodes = {record["node_id"]: make_node(record["node_id"]) for record in records}
    github = FakeGitHub(records=records, nodes=nodes, max_batch=25)

    collection = get_topic_projects(topic="anything", github=github)

    assert github.server.batch_sizes == [50, 25, 25]
    assert all(project.pushed_at is not None for project in collection.projects)


def test_batch_failing_at_the_floor_keeps_projects_unhydrated() -> None:
    records = [make_record(index) for index in range(50)]
    nodes = {record["node_id"]: make_node(record["node_id"]) for record in records}
    github = FakeGitHub(records=records, nodes=nodes, max_batch=10)

    collection = get_topic_projects(topic="anything", github=github)

    assert github.server.batch_sizes == [50, 25, 25]
    assert len(collection.projects) == 50
    assert all(project.pushed_at is None for project in collection.projects)


def test_projects_are_hydrated_in_batches_of_fifty() -> None:
    records = [make_record(index) for index in range(120)]
    nodes = {record["node_id"]: make_node(record["node_id"]) for record in records}
    github = FakeGitHub(records=records, nodes=nodes)

    collection = get_topic_projects(topic="anything", github=github)

    assert github.server.batch_sizes == [50, 50, 20]
    assert sum(project.pushed_at is not None for project in collection.projects) == 120


def test_empty_body_is_retried_before_the_batch_is_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("compass.adapters.github.time.sleep", lambda seconds: None)
    records = [make_record(index) for index in range(50)]
    nodes = {record["node_id"]: make_node(record["node_id"]) for record in records}
    github = FakeGitHub(records=records, nodes=nodes, empty_bodies=2)

    collection = get_topic_projects(topic="anything", github=github)

    assert github.server.batch_sizes == [50, 50, 50]
    assert all(project.pushed_at is not None for project in collection.projects)


def test_persistent_empty_bodies_fall_through_to_splitting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("compass.adapters.github.time.sleep", lambda seconds: None)
    records = [make_record(index) for index in range(50)]
    nodes = {record["node_id"]: make_node(record["node_id"]) for record in records}
    github = FakeGitHub(records=records, nodes=nodes, empty_bodies=4)

    collection = get_topic_projects(topic="anything", github=github)

    assert github.server.batch_sizes == [50, 50, 50, 50, 25, 25]
    assert all(project.pushed_at is not None for project in collection.projects)
