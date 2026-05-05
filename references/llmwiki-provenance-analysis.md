# llm-wiki-compiler: Provenance-Analyse (April 2026)

**Repo:** https://github.com/atomicmemory/llm-wiki-compiler (886 Stars, MIT, TypeScript)
**Analyse-Datum:** 30. April 2026
**Branch:** main, Commit 707b6b3

## Kern-Findings

### 1. Provenance ist ZWEISCHICHTIG (nicht Satz-fuer-Satz)

**Ebene A — Frontmatter-Metadaten (pro Seite):**
```yaml
confidence: 0.8                    # 0-1, LLM-reported
provenanceState: extracted        # extracted | merged | inferred | ambiguous
contradictedBy:                   # [{slug: "other-concept", reason: "..."}]
  - slug: openai-codex
    reason: "Claims 50% faster, source says 30%"
inferredParagraphs: 2             # estimated count of uncited paragraphs
```

**Ebene B — Paragraph-Level Citations (im Body):**
```markdown
Das System nutzt eine zwei-Phasen-Pipeline. ^[architecture-notes.md]
```

### 2. Paragraph-Level ist der DEFAULT, Claim-Level die AUSNAHME

Aus `src/compiler/prompts.ts` (buildPagePrompt, Zeilen 177-192):

> "Source attribution: at the end of each **prose paragraph**, append a citation
> marker showing which source file(s) the paragraph drew from.
> Format: ^[filename.md] for single-source, ^[source-a.md, source-b.md] for multi-source.
> When a single sentence makes a specific factual claim and you can identify the
> exact line range it came from, you may use the claim-level form
> ^[filename.md:START-END] ... only switch to claim-level form
> when it materially improves verifiability and the line range is unambiguous.
> Place citations only at the end of prose paragraphs or sentences — **not on
> headings, list items, or code blocks**."

### 3. Inferierte Absaetze bleiben bewusst UNZITIERT

> "If a paragraph is your inference rather than a direct extraction, leave it
> uncited — downstream lint rules will count uncited paragraphs as 'inferred'"

### 4. Linter validiert Citations maschinell (`src/linter/rules.ts`)

| Regel | Prueft |
|---|---|
| `checkBrokenCitations` | Quelldatei existiert? Zeilenbereich plausibel? Multi-Source `^[a.md, b.md]` unterstuetzt |
| `checkInferredWithoutCitations` | Zaehlt uncited prose paragraphs, warnt wenn > MAX_INFERRED_PARAGRAPHS_WITHOUT_CITATIONS |
| `checkLowConfidencePages` | confidence < LOW_CONFIDENCE_THRESHOLD (0.5?) |
| `checkContradictedPages` | contradictedBy nicht leer → Warnung |

### 5. Provenance-Metadaten kommen aus Extraction-Phase

In `src/compiler/prompts.ts` (buildExtractionPrompt, Zeilen 129-138):
- `confidence`: 0..1 — "how certain you are the source supports this concept"
- `provenance_state`: extracted/merged/inferred/ambiguous
- `contradicted_by`: slugs of conflicting concepts
- `inferred_paragraphs`: estimated count of paragraphs that will be inference

Diese Metadaten werden in der Extraktions-Phase (tool_use) erhoben und dann via `addProvenanceMeta()` (provenance.ts) in das Frontmatter der generierten Wiki-Seite kopiert.

## Implementierung in unserem Wiki

### Was wir FALSCH gemacht haben
- Per-Satz `^[...]` Annotationen an JEDEN Bulletpoint und Satz → Rauschen, keine Information
- Bei Single-Source-Seiten ist jede Annotation redundant ( Quelle steht schon im Frontmatter)
- Ollama kann nicht intelligent zwischen mehreren Quellen unterscheiden

### Was wir UEBERNEHMEN sollten
1. **Paragraph-Level Citations**: Ein `^[source.md]` am Ende von Prose-Absaetzen
2. **NIE auf List Items, Headings, Code Blocks**
3. **Epistemische Metadaten im Frontmatter**: confidence, provenanceState, contradictedBy
4. **Inferenzen unmarkiert lassen** — Linter zaehlt sie

### Was NICHT uebernommen werden muss
- Zeilenbereiche (`^[source.md:42-58]`) — zu fragil fuer unsere Pipeline
- Multi-Source `^[a.md, b.md]` — nice-to-have, nicht essenziell
- inferredParagraphs-Zaehlung — kann der Linter auch statisch
