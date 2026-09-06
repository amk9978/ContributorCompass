import datetime
from enum import StrEnum
from uuid import UUID

import pydantic


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class DomainModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")


class TopicProject(DomainModel):
    owner: str
    name: str
    url: str

    description: str | None = None
    language: str | None = None
    language_bytes: dict[str, int] = {}
    topics: list[str] = []

    stars: int = 0
    forks: int = 0

    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    pushed_at: datetime.datetime | None = None

    is_archived: bool = False
    latest_release_at: datetime.datetime | None = None

    open_pr_count: int | None = None
    open_prs_older_than_90_days: int | None = None

    has_external_prs: bool | None = None
    external_commit_ratio: float | None = None
    watchers_count: int | None = None

    default_branch: str | None = None

    license_spdx_id: str | None = None

    last_commit_at: datetime.datetime | None = None

    releases_count: int | None = None

    commits_last_90_days: int | None = None
    merged_prs_last_90_days: int | None = None
    external_merged_prs_last_90_days: int | None = None
    closed_unmerged_prs_last_90_days: int | None = None

    median_pr_merge_days: float | None = None
    median_pr_first_response_days: float | None = None

    has_issues_enabled: bool = True
    open_issues_count: int | None = None
    open_good_first_issue_count: int | None = None

    has_contributing_guide: bool | None = None
    has_pr_template: bool | None = None
    has_code_of_conduct: bool | None = None

    contributor_concentration: float | None = None


class ProjectIssue(DomainModel):
    project_name: str
    project_url: str

    title: str
    url: str
    body: str | None = None

    language: str | None = None
    topics: list[str] = []

    state: str
    labels: list[str] = []

    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    participants_count: int = 0
    comments_count: int = 0

    has_assignee: bool = False
    has_linked_pr: bool = False
    assignees_count: int = 0

    author_association: str | None = None
    linked_pr_count: int = 0

    reactions_count: int = 0

    is_locked: bool = False
    is_good_first_issue: bool = False
    is_help_wanted: bool = False


class RecommendationFeedback(StrEnum):
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    UNANSWERED = "unanswered"


class RecommendationGroupFeedback(StrEnum):
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    UNANSWERED = "unanswered"


class Bucket(StrEnum):
    CAREER_SIGNAL = "career_signal"
    FRESH_BREEZE = "fresh_breeze"
    ALIGNED = "aligned"


class BucketThresholds(DomainModel):
    bucket: Bucket
    min_stars: int
    min_forks: int
    max_days_since_push: int
    requires_outside_merges: bool = True


class CareerSignalBucketThresholds(BucketThresholds):
    bucket: Bucket = Bucket.CAREER_SIGNAL
    min_stars: int = 5000
    min_forks: int = 500


class FreshAirBucketThresholds(BucketThresholds):
    bucket: Bucket = Bucket.FRESH_BREEZE
    min_stars: int = 500
    min_forks: int = 100


class AlignedBucketThresholds(BucketThresholds):
    bucket: Bucket = Bucket.ALIGNED
    min_stars: int = 500
    min_forks: int = 50


class Evaluation(DomainModel):
    fit: float | None = None
    absorption: float | None = None
    upside: float | None = None


class Recommendation(DomainModel):
    id: UUID
    project: TopicProject
    bucket: Bucket
    evaluation: Evaluation
    explanation: str
    policy_version: str
    as_of: datetime.datetime
    feedback_at: datetime.datetime | None = None
    feedback: RecommendationFeedback = RecommendationFeedback.UNANSWERED


class RecommendationGroup(DomainModel):
    id: UUID
    recommendations: list[Recommendation]
    as_of: datetime.datetime
    feedback: RecommendationGroupFeedback = RecommendationGroupFeedback.UNANSWERED


class CacheFile(DomainModel):
    creation_date: pydantic.AwareDatetime = pydantic.Field(default_factory=utc_now)
    update_date: pydantic.AwareDatetime = pydantic.Field(default_factory=utc_now)

    def is_stale(self, stale_after: datetime.timedelta) -> bool:
        return self.update_date < utc_now() - stale_after


class PersonalTopicsFile(CacheFile):
    github_handle: str
    topics_frequency: list[tuple[str, int]]


class ProjectTopicsFile(CacheFile):
    projects: list[TopicProject]
