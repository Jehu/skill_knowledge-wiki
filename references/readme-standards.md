# README Standards (Mai 2026)

The `README.md` in the skill root is the **human-facing** document — aimed at
anyone who clones this skill and wants to use it standalone or via an AI agent.

## Hard rules

1. **English only.** No German example prompts, no German prose. The README is
   for a global audience.

2. **No personal references.** Example topics must be generic (transformers,
   vector databases, Kubernetes, RAG, Docker). Never use the maintainer's actual
   wiki content (Coolify, lexoffice, provenexpert, Infomaniak, n8n).

3. **No companion-skill dependencies.** Do not reference `video-to-wiki` or any
   other personal skill that is not included in the `knowledge-wiki` package.
   The README must work as-is after cloning only this repository.

4. **Explain concepts inline.** When the user can override a default (e.g. manual
   `--category` vs auto-categorisation), explain WHY they would do it, not just
   that they can. The README should teach.

5. **Dual audience:** The README has two usage sections:
   - "Usage via AI Agent" (primary) — natural-language prompts for agent users
   - "Usage" (secondary) — console commands for CLI users without an agent
   Lead with the agent path; the console path is for setup, scripting, and
   non-agent users.

6. **Keep examples generic.** Use `https://example.com/...`, `docs.docker.com`,
   `~/Downloads/meeting-notes.md` — never real URLs or actual file paths from
   the maintainer's system.

## Enforcement

These rules were established May 2026 when the README was rewritten for
shareability. A future agent updating the README should check against this list.
