# Contribution Compass v2 Domain Context

## Mission

Contribution Compass helps a serious software engineer identify the few open-source projects where
their skills, growth, career value, and community impact align. The scarce resource is the
developer's next several months of engineering attention.

## Domain language

### Developer Profile

An evidence-backed representation of a developer’s languages, topics, repositories, dependencies,
ecosystems, explicit interests, and desired direction. Every inferred affinity preserves its
provenance; explicit preferences may steer or override inference.

### Topic Affinity

A developer’s measured relationship to a GitHub Topic, with strength and provenance. Topics form
the primary semantic coordinate system but are not the only candidate source.

### Topic Relation

A lazily derived relationship between Topics based on evidence such as co-occurrence, specificity,
aliases, and semantic distance. No global ontology is required.

### Candidate Repository

A repository admitted to the temporary evaluation funnel through explicit Discovery Evidence. Most
Candidates are discarded and never persisted.

### Discovery Evidence

The factual reason a Candidate Repository entered the funnel, such as a topic intersection,
dependency relation, explicit seed, starred repository, curated prior, or momentum source.

### Project Evidence

The minimal public facts required to evaluate a Candidate Repository. Evidence retains source,
window, sample size, coverage, and as-of time where applicable.

### Measurement

A versioned derived fact calculated from Project Evidence. Missing or low-sample evidence remains
unknown; it is never silently imputed as average.

### Taste Policy

An explicit, versioned, inspectable set of product judgments. It applies hard floors before
comparative weighting and is regression-tested against known-good, known-bad, and ambiguous cases.
It is not a trained recommendation model.

### Project Evaluation

The result of applying a Taste Policy to peer-normalized Measurements for one Candidate Repository.
Survivors have exactly three evaluation axes: Fit, Absorption, and Upside.

### Recommendation

A personalized, evidence-backed judgment that a repository deserves serious engineering attention.
It records its policy version, profile fingerprint, measurements, explanation, provenance, bucket,
and as-of time.

### Recommendation Bucket

One disjoint portfolio role: Best Investment, Career Signal, or Fresh Breeze. Career Signal remains
provisional and should be folded into Best Investment if it cannot reliably mean accessible
prestige.

### Recommended Issue

A small, concrete call to action selected only inside an already-recommended repository. It carries
factual selection reasons and a conservative action: START, INVESTIGATE, ASK_MAINTAINER, or AVOID.

### Dependency Relation

A provenance-bearing relationship between a developer, package, and repository. It distinguishes
runtime from development use, direct from transitive evidence, and package identity from repository
identity whenever the source permits.

## Invariants

- Project first, issue second.
- Archived, deprecated, dead, inaccessible, or too-weakly-observed projects cannot buy their way
  past a hard floor with stars or popularity.
- Evidence, Measurements, Taste Policy, and Recommendations remain distinguishable.
- Missing evidence is unknown, not average.
- Exactly three axes—Fit, Absorption, and Upside—shape project evaluation after floors.
- Recommendation buckets are disjoint and the final portfolio is diversified.
- Every recommendation and Recommended Issue retains the evidence and policy that explain it.
- Bot activity is excluded before contribution-climate aggregation.
- GitHub remains the primary live source of truth.
- Collection and recommendation require no LLM inference.
- Persistence exists only for synchronization, reproducibility, explanation, outcomes, and feedback.
- CLI, MCP, and static output are adapters over application use cases, not catalog-shaped products.

## Collection constraints

These three decisions look like arbitrary choices in the code and are not. Each was
reached by hitting the failure it avoids.

**Topic candidates come from the search connection, never `Topic.repositories`.**
Adding `orderBy` to `Topic.repositories` makes GitHub return `Something went wrong
while executing your query` for any large topic. `python` failed every attempt while
`editor` and `github-actions` passed, and shrinking the page to 25 repositories did
not help, so the trigger is the sort rather than the payload size. Dropping
`orderBy` returns arbitrary order, which cannot rank anything. `search(query:
"topic:<name> sort:stars-desc", type: REPOSITORY)` sorts correctly, costs the same
one point per page, and caps at 1,000 results.

**Two staleness thresholds per cache, not one.** A reader refetches at 30 days for
personal topics and 7 days for project topics. CI refreshes at 25 and 5. The shorter
pair is what lets a scheduled run act before a reader can see a stale cache. Collapse
them into one pair and a daily cron leaves entries reaching 8 days against a 7 day
threshold, because the run that would refresh an entry only fires after it has
already gone stale.

**`TOPIC_MAX_PAGES` is 2, well below the search ceiling of 10.** Search returns 100
repositories per page where the retired scraper returned 20, so 10 pages would write
1,000 projects and 1.8 MB per topic. Two pages reproduce the 200 projects per topic
that the scraper produced. The star and fork floors discard the tail long before
result 200, so the extra pages buy nothing and cost 41 MB per sweep instead of 8 MB.
