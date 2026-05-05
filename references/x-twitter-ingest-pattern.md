# X/Twitter-Ingestion Pattern

## Problem

X/Twitter-Posts können weder via `web_extract` noch via Browser-Scraping zuverlässig extrahiert werden:

- `web_extract(url)` → "Internal Server Error" (Firecrawl kann X nicht scrapen)
- `browser_navigate(url)` → Camofox nicht verfügbar (localhost:9377)
- `web_search(query)` → liefert nur Snippets (Titel + 1-2 Sätze), nicht den vollen Content

## Lösung: User liefert Markdown

Der effektivste Weg ist, den User den Post als Markdown zu kopieren. X bietet einen "Copy link"-Button, aber keinen "Copy as Markdown". Der User kann den Text manuell kopieren oder Tools wie [tweet-hunter](https://tweet-hunter.io/) nutzen.

**Format, das der User liefert:**

```markdown
---
title: "..."
source: "https://x.com/{handle}/status/{id}"
author:
  - "[[@{handle}]]"
published: YYYY-MM-DD
created: YYYY-MM-DD
description: "..."
tags:
  - "clippings"
---
![Bild](https://pbs.twimg.com/media/...)

{Content}
```

## Ingestion-Workflow

1. User postet X-Link
2. Versuche `web_extract` → erwartungsgemäß Fehler
3. Frage User: "Kannst du den Post als Markdown kopieren? X lässt sich nicht scrapen."
4. User liefert Markdown-Block
5. Speichere als `raw/{category}/{date}-{slug}.md` mit vollständigem Frontmatter
6. Extrahiere Entities/Concepts wie bei jeder anderen Quelle
7. Bilder-URLs (pbs.twimg.com) bleiben als externe Links — keine lokale Speicherung nötig, Twitter-CDN ist stabil

## Beispiel: mem0ai über Hermes Curator

**Quelle:** https://x.com/mem0ai/status/2050351798142288050  
**Kategorie:** ai-agents  
**Entities:** mem0 (company), Nous Research (company), Hermes Agent (product)  
**Concepts:** Skill Drift, Context Rot, Agent Memory Architecture, Procedural Memory

**Key Insights aus dem Post:**

- Self-improving agents horten Skills (skills-hoarding problem)
- Hermes Curator ist ein Hintergrund-Prozess für Skill-Maintenance
- Vier Speicherarten im Agent-Runtime: Working, Semantic, Episodic, Procedural
- mem0 verwaltet Semantic Memory (was der Agent weiß)
- Hermes Curator verwaltet Procedural Memory (wie der Agent arbeitet)
- Curator-Mechanismus: watch → demote (30d stale, 90d archive) → review (billiges Modell) → respect pins
- CLI: `hermes curator status/run/pause/resume/pin/unpin/restore`

**Wichtiger Unterschied zu mem0:**
- mem0 = Memory Layer (Fakten, Kontext, Konversationen)
- Hermes Curator = Skills Layer (Prozedurales Wissen, How-To-Dateien)
- Beide sind komplementär, nicht konkurrierend
