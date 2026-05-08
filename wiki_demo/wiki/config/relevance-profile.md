---
# Demo / Template — adapt to your interests
# Full documentation: ../../README.md

min_content_length: 500
min_keyword_matches: 1

professional:
  always_relevant:
    - "web-development"
    - "ai-agents"
    - "python"
    - "seo"

  never_relevant:
    - "cryptocurrency"
    - "bitcoin"
    - "celebrity"

  trusted_sources:
    - "docs.example.com/**"

personal:
  always_relevant:
    - "photography"
    - "psychology"

  never_relevant:
    - "reality-tv"
    - "clickbait"

  trusted_sources: []

rules:
  professional_auto: "filter"
  personal_auto: "accept_all"
  manual: "accept_all"
---
