# Daily news automation

`Generate daily news brief` is scheduled at **01:05 UTC (09:05 Singapore time)** every day and can also be started with **Run workflow**. Because GitHub cron jobs can be delayed, a second recovery schedule runs at **02:05 UTC (10:05 Singapore time)**. The recovery run exits after checkout when that Singapore-date brief already exists, so a successful primary run is not regenerated.

The job collects recent items from English BBC, Guardian, NPR and UN feeds plus
seven broad English Google News searches. A failure from one feed is recorded
in the generated quality section and does not stop the other feeds. If no
current candidates can be collected, the job fails rather than publishing an
empty brief.

After collection, the generator applies a 36-hour freshness window, rejects
obviously low-value formats and non-English titles, categorises relevant
stories, and merges exact canonical URLs and highly similar headlines at event
level. Each topic then selects at most ten events using freshness, source authority, topic relevance, major-event terms, description completeness, corroboration, publisher diversity and similarity to already selected events. Selection is not a quota: candidates below the deterministic quality threshold are omitted rather than used to fill a section. Obvious PR/SEO market-report material and known low-value syndication domains are excluded from the final pool, and robotics/energy/other sections require stronger core-topic evidence.
Tracking-only URL parameters are ignored for article identity, while meaningful
query parameters are preserved. Topic selection shares one global source-URL
set, so a lower-priority topic skips a URL already selected by a higher-priority
topic and continues down its ranked candidates to backfill the slot. Up to three source links are retained for a merged event. “今日最重要” is a selective maximum-seven view
drawn from this already selected pool; those items are removed from their topic
sections so every event card and source URL is rendered only once.

Only selected English titles and publisher-supplied RSS descriptions are sent
to **Google Cloud Translation v3**. The workflow authenticates with GitHub OIDC
and Google Cloud Workload Identity Federation; it does not use a service-account
key or user-created API key. OpenCC normalises returned text to Simplified Chinese. A small maintainable glossary masks important names such as OpenAI, Anthropic, NVIDIA and Google during live translation and restores them afterward. Translation is not generative summarisation: summaries remain
translations of publisher feed descriptions. If a feed has no description, the
generator translates a clearly limited headline-based notice instead.

Transient rate-limit, service and network errors use the Google client
library's bounded retry policy. An individual translation failure removes only
that item and is recorded in the quality section. Authentication/client setup
failures stop the run, and if no safely translated items remain the generator
refuses to publish an English brief. Chinese-dominance checks reject incomplete
or untranslated output before it can be committed.

The workflow validates the Singapore date, external links, duplicate titles,
reused source URLs, the declared event count, the hard ten-event maximum for
every section, Chinese titles and summaries, and all required HTML sections.
It commits only that day's `私人AI新闻简报-YYYY-MM-DD.html`; historical briefs are
never removed. The static `index.html` resolves the visitor's current Singapore
date and loads that dated file without using a stale cached response.

## Google Cloud configuration

The repository contains only public resource identifiers for the Workload
Identity Provider and service account. In Google Cloud, administrators must:

1. enable Cloud Translation API for the configured project;
2. allow the GitHub identity to impersonate only the translation service
   account with `roles/iam.workloadIdentityUser`;
3. restrict the provider attribute condition to this repository and, where
   practical, the trusted branch and workflow;
4. grant the service account only a translation role that includes
   `cloudtranslate.generalModels.predict`; and
5. avoid Owner, Editor, IAM administration or service-account-key roles.

The Google Cloud API is an external metered service with quotas. IAM denials are
not transient and should be diagnosed in the Actions log and Google Cloud Audit
Logs rather than retried.

The standard `GITHUB_TOKEN` is used by checkout and `git push` under the
workflow's `contents: write` permission. In **Settings → Actions → General →
Workflow permissions**, allow read and write permissions if organisation-level
policy overrides workflow permissions. Branch protection on `main` must either
allow GitHub Actions to push or use a pull-request based publication design.

A commit pushed with `GITHUB_TOKEN` does not start another push workflow. The
Pages workflow is therefore also triggered by successful completion of the
generator through `workflow_run`. Direct pushes to `main` and manual Pages
deployments continue to work.

## Local checks

Deterministic tests do not need Google credentials or network access:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
python3 scripts/generate_news.py \
  --date 2026-09-21 \
  --fixture tests/fixtures/news.xml \
  --translation-fixture tests/fixtures/translations.json \
  --output /tmp/news-brief.html
python3 scripts/validate_news.py /tmp/news-brief.html --date 2026-09-21
```

A live local run additionally requires the pinned packages, outbound feed
access, `GOOGLE_CLOUD_PROJECT`, and Application Default Credentials authorised
for Cloud Translation:

```bash
python3 -m pip install --requirement requirements-translation.txt
python3 scripts/generate_news.py
```
