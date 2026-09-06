import logging
from collections.abc import Iterator
from typing import Any, TypedDict

from githubkit import GitHub

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL_API = "https://api.github.com/graphql"

REPOS_PER_PAGE = 100


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
query ($topic: String!, $cursor: String) {
  topic(name: $topic) {
    repositories(
      first: 100
      after: $cursor
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
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

    def iter_repositories(
        self,
        query: str,
        variables: dict[str, Any],
        container: str,
        max_pages: int,
    ) -> Iterator[list[TopicRepoRecord]]:
        cursor: str | None = None

        for _ in range(max_pages):
            data = self.github.graphql(query, {**variables, "cursor": cursor})
            container_data = data[container]

            if container_data is None:
                return

            repositories = container_data["repositories"]

            yield [build_topic_repo_record(node) for node in repositories["nodes"]]

            page_info = repositories["pageInfo"]

            if not page_info["hasNextPage"]:
                return

            cursor = page_info["endCursor"]

    def user_repos(self, github_handle: str, max_pages: int = 5) -> list[TopicRepoRecord]:
        records: list[TopicRepoRecord] = []

        for page in self.iter_repositories(
            query=USER_REPOS_QUERY,
            variables={"login": github_handle},
            container="user",
            max_pages=max_pages,
        ):
            records.extend(page)

        return records

    def iter_topic_repos(
        self,
        topic: str,
        max_pages: int = 5,
    ) -> Iterator[list[TopicRepoRecord]]:
        yield from self.iter_repositories(
            query=TOPIC_REPOS_QUERY,
            variables={"topic": topic},
            container="topic",
            max_pages=max_pages,
        )
