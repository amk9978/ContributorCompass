import logging
import time
from collections.abc import Iterator
from typing import Any, TypedDict

import pydantic
from githubkit import GitHub
from githubkit.exception import GitHubException

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL_API = "https://api.github.com/graphql"

REPOS_PER_PAGE = 100
SEARCH_RESULT_LIMIT = 1000
HYDRATION_BATCH_SIZE = 50
HYDRATION_MIN_BATCH_SIZE = 25
HYDRATION_FAILURES = (GitHubException, pydantic.ValidationError)
EMPTY_BODY_BACKOFF_SECONDS = (1, 4, 9)


class TopicRepoRecord(TypedDict):
    node_id: str
    owner: str
    name: str
    url: str
    description: str | None
    stars: int
    forks: int
    language: str | None
    topics: list[str]
    updated_at: str | None


class RepositoryEvidence(TypedDict):
    created_at: str
    pushed_at: str | None
    is_archived: bool
    has_issues_enabled: bool
    license_spdx_id: str | None
    default_branch: str | None
    last_commit_at: str | None
    latest_release_at: str | None
    watchers_count: int
    open_issues_count: int
    open_good_first_issue_count: int
    open_pr_count: int
    language_bytes: dict[str, int]
    has_contributing_guide: bool


REPOSITORY_FRAGMENT = """
fragment RepositoryFields on Repository {
  id
  owner {
    login
  }
  name
  url
  description
  stargazerCount
  forkCount
  primaryLanguage {
    name
  }
  repositoryTopics(first: 100) {
    nodes {
      topic {
        name
      }
    }
  }
  updatedAt
}
"""

USER_REPOS_QUERY = (
    REPOSITORY_FRAGMENT
    + """
query ($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER) {
      nodes {
        ...RepositoryFields
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""
)

TOPIC_REPOS_QUERY = (
    REPOSITORY_FRAGMENT
    + """
query ($searchQuery: String!, $cursor: String) {
  search(query: $searchQuery, type: REPOSITORY, first: 100, after: $cursor) {
    nodes {
      ...RepositoryFields
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""
)

REPOSITORY_EVIDENCE_QUERY = """
query ($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Repository {
      id
      createdAt
      pushedAt
      isArchived
      hasIssuesEnabled
      licenseInfo {
        spdxId
      }
      defaultBranchRef {
        name
        target {
          ... on Commit {
            committedDate
          }
        }
      }
      latestRelease {
        publishedAt
      }
      watchers {
        totalCount
      }
      openIssues: issues(states: OPEN) {
        totalCount
      }
      goodFirstIssues: issues(states: OPEN, labels: ["good first issue"]) {
        totalCount
      }
      openPullRequests: pullRequests(states: OPEN) {
        totalCount
      }
      languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
        edges {
          size
          node {
            name
          }
        }
      }
      contributingGuide: object(expression: "HEAD:CONTRIBUTING.md") {
        id
      }
    }
  }
}
"""


def topic_search_query(topic: str, star_ceiling: int | None = None) -> str:
    query = f"topic:{topic} sort:stars-desc"

    if star_ceiling is None:
        return query

    return f"{query} stars:<={star_ceiling}"


def build_topic_repo_record(node: dict[str, Any]) -> TopicRepoRecord:
    language = node["primaryLanguage"]
    topic_nodes = node["repositoryTopics"]["nodes"]

    return TopicRepoRecord(
        node_id=node["id"],
        owner=node["owner"]["login"],
        name=node["name"],
        url=node["url"],
        description=node["description"],
        stars=node["stargazerCount"],
        forks=node["forkCount"],
        language=language["name"] if language else None,
        topics=[entry["topic"]["name"] for entry in topic_nodes],
        updated_at=node["updatedAt"],
    )


def build_repository_evidence(node: dict[str, Any]) -> RepositoryEvidence:
    license_info = node["licenseInfo"]
    default_branch = node["defaultBranchRef"]
    last_commit = default_branch["target"] if default_branch else None
    latest_release = node["latestRelease"]

    return RepositoryEvidence(
        created_at=node["createdAt"],
        pushed_at=node["pushedAt"],
        is_archived=node["isArchived"],
        has_issues_enabled=node["hasIssuesEnabled"],
        license_spdx_id=license_info["spdxId"] if license_info else None,
        default_branch=default_branch["name"] if default_branch else None,
        last_commit_at=last_commit.get("committedDate") if last_commit else None,
        latest_release_at=latest_release["publishedAt"] if latest_release else None,
        watchers_count=node["watchers"]["totalCount"],
        open_issues_count=node["openIssues"]["totalCount"],
        open_good_first_issue_count=node["goodFirstIssues"]["totalCount"],
        open_pr_count=node["openPullRequests"]["totalCount"],
        language_bytes={edge["node"]["name"]: edge["size"] for edge in node["languages"]["edges"]},
        has_contributing_guide=node["contributingGuide"] is not None,
    )


class GitHubClient:
    def __init__(self, token: str, timeout: float = 30) -> None:
        self.token = token
        self.timeout = timeout
        self.github = GitHub(token, timeout=timeout)

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        for backoff in EMPTY_BODY_BACKOFF_SECONDS:
            try:
                return self.github.graphql(query, variables)
            except pydantic.ValidationError:
                logger.warning("GitHub returned an empty GraphQL body, retrying in %ss", backoff)
                time.sleep(backoff)

        return self.github.graphql(query, variables)

    def fetch_connection(
        self,
        query: str,
        variables: dict[str, Any],
        connection_path: tuple[str, ...],
    ) -> Any:
        connection: Any = self.graphql(query, variables)

        for key in connection_path:
            if connection is None:
                return None

            connection = connection[key]

        return connection

    def iter_repositories(
        self,
        query: str,
        variables: dict[str, Any],
        connection_path: tuple[str, ...],
        max_pages: int,
    ) -> Iterator[list[TopicRepoRecord]]:
        cursor: str | None = None

        for _ in range(max_pages):
            connection = self.fetch_connection(
                query=query,
                variables={**variables, "cursor": cursor},
                connection_path=connection_path,
            )

            if connection is None:
                return

            yield [build_topic_repo_record(node) for node in connection["nodes"]]

            page_info = connection["pageInfo"]

            if not page_info["hasNextPage"]:
                return

            cursor = page_info["endCursor"]

    def user_repos(self, github_handle: str, max_pages: int = 5) -> list[TopicRepoRecord]:
        records: list[TopicRepoRecord] = []

        for page in self.iter_repositories(
            query=USER_REPOS_QUERY,
            variables={"login": github_handle},
            connection_path=("user", "repositories"),
            max_pages=max_pages,
        ):
            records.extend(page)

        return records

    def iter_topic_repos(
        self,
        topic: str,
        max_pages: int = 5,
    ) -> Iterator[list[TopicRepoRecord]]:
        star_ceiling: int | None = None
        cursor: str | None = None
        pages_yielded = 0

        while pages_yielded < max_pages:
            connection = self.fetch_connection(
                query=TOPIC_REPOS_QUERY,
                variables={
                    "searchQuery": topic_search_query(topic=topic, star_ceiling=star_ceiling),
                    "cursor": cursor,
                },
                connection_path=("search",),
            )

            if connection is None or not connection["nodes"]:
                return

            pages_yielded += 1
            records = [build_topic_repo_record(node) for node in connection["nodes"]]
            yield records

            page_info = connection["pageInfo"]

            if page_info["hasNextPage"]:
                cursor = page_info["endCursor"]
                continue

            next_ceiling = min(record["stars"] for record in records)

            if star_ceiling is not None and next_ceiling >= star_ceiling:
                return

            logger.debug(
                "Topic %s exhausted a search window, continuing below %s stars", topic, next_ceiling
            )
            star_ceiling = next_ceiling
            cursor = None

    def fetch_evidence_batch(self, node_ids: list[str]) -> dict[str, RepositoryEvidence]:
        response: Any = self.graphql(REPOSITORY_EVIDENCE_QUERY, {"ids": node_ids})

        return {node["id"]: build_repository_evidence(node) for node in response["nodes"] if node}

    def hydrate_batch(self, node_ids: list[str]) -> dict[str, RepositoryEvidence]:
        try:
            return self.fetch_evidence_batch(node_ids)
        except HYDRATION_FAILURES as exc:
            if len(node_ids) <= HYDRATION_MIN_BATCH_SIZE:
                logger.warning(
                    "Leaving %s repositories without evidence after a failed batch: %s",
                    len(node_ids),
                    exc,
                )
                return {}

        half = len(node_ids) // 2
        logger.debug("Splitting a failed hydration batch of %s repositories", len(node_ids))

        return {**self.hydrate_batch(node_ids[:half]), **self.hydrate_batch(node_ids[half:])}

    def hydrate_repositories(self, node_ids: list[str]) -> dict[str, RepositoryEvidence]:
        evidence: dict[str, RepositoryEvidence] = {}

        for start in range(0, len(node_ids), HYDRATION_BATCH_SIZE):
            evidence.update(self.hydrate_batch(node_ids[start : start + HYDRATION_BATCH_SIZE]))

        return evidence
