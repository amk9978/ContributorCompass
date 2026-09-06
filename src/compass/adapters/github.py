import logging
from collections.abc import Iterator
from typing import Any, TypedDict

from githubkit import GitHub

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL_API = "https://api.github.com/graphql"

REPOS_PER_PAGE = 100
SEARCH_RESULT_LIMIT = 1000


class TopicRepoRecord(TypedDict):
    owner: str
    name: str
    url: str
    description: str | None
    stars: int
    forks: int
    language: str | None
    topics: list[str]
    updated_at: str | None


REPOSITORY_FRAGMENT = """
fragment RepositoryFields on Repository {
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


def topic_search_query(topic: str, star_ceiling: int | None = None) -> str:
    query = f"topic:{topic} sort:stars-desc"

    if star_ceiling is None:
        return query

    return f"{query} stars:<={star_ceiling}"


def build_topic_repo_record(node: dict[str, Any]) -> TopicRepoRecord:
    language = node["primaryLanguage"]
    topic_nodes = node["repositoryTopics"]["nodes"]

    return TopicRepoRecord(
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


class GitHubClient:
    def __init__(self, token: str, timeout: float = 30) -> None:
        self.token = token
        self.timeout = timeout
        self.github = GitHub(token, timeout=timeout)

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch_connection(
        self,
        query: str,
        variables: dict[str, Any],
        connection_path: tuple[str, ...],
    ) -> Any:
        connection: Any = self.github.graphql(query, variables)

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
