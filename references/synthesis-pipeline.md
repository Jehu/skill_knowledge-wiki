# Synthesis Pipeline — Implementierungsdetails

## Post-Processing in save_synthesis()

Nachdem die Ollama-Antwort generiert wurde, passiert in `save_synthesis()`:

### 1. Pfad-Korrektur
Ollama generiert Citations ohne `../` Prefix (weil der Prompt nur relative Pfade vorgibt, aber nicht weiss dass die Datei in `synthesis/` liegt).
```
(wiki/concepts/foo.md)   →   (../wiki/concepts/foo.md)
(raw/ai-agents/bar.md)   →   (../raw/ai-agents/bar.md)
```
Regex: `re.sub(r'\(((?:raw|wiki|synthesis)/)', r'(../\1', answer)`

### 2. Auto-Link-Injection
`inject_wikilinks()` verlinkt Entities/Concepts im Fliesstext. Die bereits existierenden Citation-Links werden durch `_collect_protection_ranges()` geschützt (Markdown-Link-Regex `\[([^\]]*)\]\([^)]*\)`).

### 3. inferred_paragraphs
Ein Absatz gilt als "belegt" (nicht inferiert) wenn er `^[` oder `](` enthält. Der Code splittet an `\n\n` und checkt jedes Segment.

## Bekannte Race-Condition in inject_wikilinks() (gefixt Apr 2026)

**Problem:** Kurze Entity-Namen (z.B. "AI") werden vor längeren Namen (z.B. "AI Agent") verlinkt → Nested-Links:
```
[[AI](../wiki/concepts/ai.md) Agent](../wiki/concepts/ai-agent.md)
```

**Fix (2-stufig):**
1. Index wird nach `len(title)` absteigend sortiert → längere Matches zuerst
2. Nach jeder Link-Insertion wird der Text neu geschützt (Re-Protection), so dass neu eingefügte `[...](...)` Links nie von einer späteren Iteration gematcht werden

**Retroaktive Reparatur** von bereits defekten Dateien:
```python
clean = re.sub(r'\[\[([^]]+)\]\]', lambda m: m.group(1).split('|')[0].split('/')[-1], content)
clean = re.sub(r'\[([^]]*)\]\([^)]+\)', r'\1', clean)
relinked = inject_wikilinks(clean, wiki_index, rel_path)
```

## Citation-Protection

`_collect_protection_ranges()` schützt folgende Textbereiche vor Link-Injection:
- Frontmatter (`---...---`)
- Code-Blöcke (``` ```)
- Bestehende Markdown-Links (`[text](url)`)
- Citations (`^[text]`) — inkl. Nested-Brackets via erweiterter Regex
