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

These decisions look like arbitrary choices in the code and are not. Each was reached
by hitting the failure it avoids.

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

**Depth is decided per topic, and the two stopping signals get different
discipline.** A fixed page count cannot serve both `python`, where the 200th
repository still has 22,000 stars, and `diagram-editor`, which holds 8 repositories
above 500 stars in total. Paging continues until one of these fires, whichever comes
first.

- A page whose lowest repository falls under 500 stars ends the topic immediately.
  Results are sorted by stars descending, so nothing better exists further down. This
  is a sound stop and needs no confirmation.
- Two consecutive pages yielding fewer than 25 repositories with at least 50 forks
  ends the topic. Fork counts are not monotone across pages, so this one needs
  confirming. Measured recoveries after a first sub-25 page never exceeded 24, which
  is what the two-page window covers.
- Ten pages is the default depth. Passing it requires the last two pages to each hold
  at least 50 gate-passers, judged once at page ten rather than re-checked afterwards.
- Twenty pages is the hard budget. A topic stopping here is truncated rather than
  finished, which is why `stop_reason` is stored.

The 50-fork gate is deliberately a constant rather than a per-topic percentile. It
asserts an absolute bar, that a project has enough independent interest to be worth a
serious contributor's months. Relativizing it would admit 20-fork projects wherever a
topic is thin, which is the failure it exists to prevent.

A measured sweep of 22 topics: 18 topics ended on the star floor, 2 on saturation, and
`python` and `javascript` on the page budget. 107 pages, 155 points of the 5,000 hourly
budget, 15 minutes, 9,566 projects. `cli` kept exactly the 1,565 repositories that
`topic:cli stars:>=500` reports, so the paging enumerates the qualifying set exactly.

**Search caps one query at 1,000 results, so depth past that needs a new query.**
`topic:python` matches 863,000 repositories but reports `hasNextPage: false` at result
1,000. `iter_topic_repos` hides this: when a query exhausts, it re-enters as
`stars:<=<last minimum seen>` with a fresh cursor. The bound is inclusive so ties at
the boundary are not skipped, which costs one duplicate record that URL dedup absorbs.
A tranche whose ceiling does not decrease ends the topic, otherwise a page tied at one
star count would re-issue the same query until the budget ran out.
