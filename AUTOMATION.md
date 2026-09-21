# Daily news automation

`Generate daily news brief` runs at **01:05 UTC (09:05 Singapore time)** every
day and can also be started with **Run workflow** in GitHub Actions. It collects
recent items from English BBC, Guardian, NPR and UN feeds plus seven broad
Google News searches. A failure from one feed is recorded in the generated
quality section and does not stop the other feeds.

After collection and event-level deduplication, the workflow sends batches of
English titles and feed descriptions to the official **GitHub Models** inference
API using `openai/gpt-4.1-mini`. The model is instructed to produce a concise,
natural Simplified Chinese title and a two-to-three-sentence Chinese summary
based only on the supplied source text. Publisher names and original links are
never translated or replaced. The generated file is rejected if conversion is
incomplete or if any title/summary is not Chinese-dominant; an English-only
brief can therefore never be committed as a successful run.

The generator applies a 36-hour freshness window, rejects obviously low-value
formats and non-English titles, categorises relevant stories, and merges highly
similar headlines at event level. It does not impose a per-category quota or a
global maximum. When an event has multiple reports, links from reliable,
generally free publishers are ordered first; up to three distinct sources are
retained. The first ten reliability/recency-ranked events form “今日最重要”; all
remaining events appear in the existing topical sections.

The workflow validates the Singapore date, external links, duplicate titles and
all required HTML sections before committing only that day's
`私人AI新闻简报-YYYY-MM-DD.html`. Historical briefs are never removed. The static
`index.html` resolves the visitor's current Singapore date and loads that dated
file.

## Repository settings

No user-created API key or repository secret is required. The workflow uses the
ephemeral standard `GITHUB_TOKEN` with `contents: write` and `models: read`.
GitHub Models has included, rate-limited usage; this implementation does not
enable paid usage or attach a billing credential. Availability and rate limits
remain subject to the repository/organisation's GitHub plan and Models policy.
In **Settings → Actions → General →
Workflow permissions**, allow read and write permissions if the organisation
overrides workflow-level permissions. Any branch protection on `main` must also
allow GitHub Actions to push, or the commit step must be adapted to use a pull
request.

A commit pushed with `GITHUB_TOKEN` does not emit a second workflow run, so the
unchanged Pages job is additionally triggered by a successful
`workflow_run` completion of the generator. Existing direct pushes to `main`
and manual Pages deployments continue to work.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/generate_news.py
```

The last command needs outbound access to the configured publishers.
