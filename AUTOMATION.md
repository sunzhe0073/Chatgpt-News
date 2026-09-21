# Daily news automation

`Generate daily news brief` runs at **01:05 UTC (09:05 Singapore time)** every
day and can also be started with **Run workflow** in GitHub Actions. It collects
recent items from English BBC, Guardian, NPR and UN feeds plus seven broad
Google News searches. A failure from one feed is recorded in the generated
quality section and does not stop the other feeds.

After collection and event-level deduplication, the workflow translates each
English title and publisher-supplied RSS description on the Actions runner with
the open-source **Argos Translate** English-to-Chinese neural model. OpenCC then
normalises the result to Simplified Chinese. This is translation, not generative
summarisation: the summary is a translation of the source's description, so the
pipeline does not add unsupported background or implications. If a feed omits
its description, a clearly limited Chinese rendering of the headline and the
absence of further feed detail is used instead. Publisher names and original
links are never translated or replaced. The existing Chinese-dominance checks
still reject incomplete or English output before it can be committed.

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

No user-created API key, paid API, hosted inference service, or `models: read`
permission is used. Argos Translate and OpenCC are free/open-source software;
translation runs locally on the already-provisioned GitHub Actions runner and
has no per-request quota or inference fee. On a cold cache the workflow obtains
the Python packages from PyPI and the free language-model artifact from the
Argos package index; `actions/cache` retains the model for later runs. Thus it
does depend on those download hosts when installing a cold runner, but daily
translation does not depend on the availability or policy of an external AI
API. The standard `GITHUB_TOKEN` is used only by checkout and `git push` under
the `contents: write` permission.
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
python3 -m pip install --requirement requirements-translation.txt
python3 scripts/setup_translation.py
python3 scripts/generate_news.py
```

The last command needs outbound access to the configured publishers.
