# Exception Handling Inventory

Scope: U6 from `docs/plans/2026-07-11-ingest-safety-portability-plan.md`.

| Location | Classification | Disposition | Regression proof |
|---|---|---|---|
| `scripts/auto_ingest.py::_fetch_video_transcript` | Intentional provider fallback | Preserve fallback order; add warning when YouTube yt-dlp and API fallback both yield no transcript. Description-only source ingest may still proceed in `process_youtube`. | `tests.test_auto_ingest.TranscriptFallbackTests.test_all_transcript_providers_unavailable_returns_empty_with_warning` |
| `scripts/auto_ingest.py::_ytdlp_transcript` | Intentional provider fallback | Preserve `FileNotFoundError`/timeout fallback and debug-only unexpected errors; no false success observed. | Reviewed; no changed handler. |
| `scripts/auto_ingest.py::_yt_transcript_api_fallback` inner language fetch | Intentional multi-language fallback with previously silent provider failure | Preserve language fallback, but warn when one provider/language raises so API incompatibility is observable while later language success still wins. | `tests.test_auto_ingest.TranscriptFallbackTests.test_transcript_api_provider_failure_is_observable_and_later_language_can_succeed` |
| `scripts/auto_ingest.py::process_youtube` transcript-missing branch | Success/skip recording boundary | Preserve behavior: if transcript is unavailable, use description or explicit placeholder content, then only mark processed when `run_ingest()` returns true. | Existing control flow reviewed; no changed handler. |
| `scripts/auto_ingest.py::run_ingest` subprocess timeout/non-zero | Ingest subprocess boundary | Preserve false return for timeout, non-zero exit, and unexpected exceptions; callers only mark processed after true. | Existing control flow reviewed; no changed handler. |
