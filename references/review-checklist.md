# Review-Checkliste für Wiki-Skripte

Systematische Review-Methodik, angewendet am 30.04.2026 auf `wiki_query.py`.

## Prüfpunkte

### Code-Qualität
- [ ] Doppelter Code? (UMLAUT_MAP existierte 2x — `ingest_source.py` + `wiki_query.py`)
- [ ] Hardcodierte Werte die veralten? (Pfade, Modellnamen, Ports)
- [ ] Rückgabewerte werden korrekt getypt? (Tuple-Länge, None-Checks)

### Fehlerbehandlung
- [ ] Leere Antworten abgefangen (Ollama `done_reason: length`)
- [ ] Timeouts und ConnectionErrors behandelt
- [ ] Keine leeren Dateien geschrieben (exit 1 statt write)

### Ollama-Integration
- [ ] `done_reason` wird ausgewertet (nicht nur `response` lesen)
- [ ] `num_predict` groß genug für erwartete Antwortlänge
- [ ] Prompt-Länge begrenzt (< 60k Zeichen oder Context-Window des Modells)

### Suche
- [ ] Keyword-Filter-Grenze sinnvoll (≥ 2 Zeichen fängt KI/AI/SEO)
- [ ] Sigma-Kurzschläge: `search_files` findet auch ohne exakte Keywords
- [ ] Synthesis-Seiten werden mit durchsucht (nicht nur raw/)

### Datenkonsistenz
- [ ] Frontmatter-Felder vollständig (question, source_refs, confidence, provenance_state, inferred_paragraphs)
- [ ] `truncated: true` bei abgeschnittenen Antworten
- [ ] Alle Index-Dateien werden regeneriert (7 Stück + pro Kategorie)

### Skill-Dokumentation
- [ ] SKILL.md Parameter stimmen mit Code überein (num_predict, max_files, Keyword-Limit)
- [ ] Einschränkungen sind dokumentiert
- [ ] Cross-Referenzen zu shared Komponenten (ingest_source.py, regen_index.py)

## Angewendet auf wiki_query.py (Ergebnisse)

| Check | Status | Fix |
|-------|--------|-----|
| Doppelter Code | ✅ Gefixt | UMLAUT_MAP importiert statt dupliziert |
| Leere Antworten | ✅ Gefixt | exit 1 + Warnung + keine Datei |
| done_reason | ✅ Gefixt | Wird aus response.json() extrahiert |
| num_predict | ✅ Gefixt | 2048 → 4096 |
| Keyword-Filter | ✅ Gefixt | ≥ 4 → ≥ 2 Zeichen |
| Confidence fake | ❌ Offen | Keine echte Coverage-Berechnung |
| Retry bei length | ❌ Offen | Automatischer Prompt-Shorten nicht implementiert |
