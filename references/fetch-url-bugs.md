# fetch_url() Bugs — Mai 2026

## Beispiel-Datei

`raw/business/2026-04-27-eu-ai-act-die-wichtigsten-anderungen-ab-2026-website-check.md`

Source: https://website-check.de/blog/der-eu-ai-act-warum-der-august-2026-das-schicksalsjahr-fuer-ki-compliance-wird/

## Bug 1: HTML-Chrome im Body

`fetch_url()` (Zeile 203) ruft `markdownify(html, heading_style="ATX")` auf, ohne vorher
Nicht-Content-Elemente zu entfernen. Der Fallback `_naive_html_to_text()` filtert
`<script>`, `<style>`, `<nav>`, `<footer>`, `<header>` — wird aber nie verwendet,
weil `markdownify` installiert ist.

**Symptome:**
- Website-Footer-Links, Share-Buttons, Newsletter-Forms landen im Body
- CSS-Whitespace (leere `<div>`-Container mit nur Tabs) erzeugt dutzende Leerzeilen
- "Ähnliche Beiträge", Tag-Listen, Autor-Boxen als Markdown

**Betroffene Datei:** 290 Zeilen, davon ~150 Zeilen Website-Müll, ~60 Zeilen verwertbarer Content.

**Fix-Ansatz:**
1. Vor `markdownify`: HTML mit BeautifulSoup reinigen
2. `soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form'])` → decompose
3. Oder: `trafilatura.extract(html)` statt `markdownify` (trafilatura ist installiert)
4. Nach Konvertierung: Leerzeilen mit nur Whitespace entfernen (`re.sub(r'\n[\t ]+\n', '\n', md)`)

## Bug 2: Encoding

`requests.get().text` errät den Charset via `resp.apparent_encoding`. Bei falsch
deklarierten Seiten (ISO-8859-1 als UTF-8 gemeldet, oder umgekehrt) entsteht Müll.

**Symptome:**
- `Ã` statt `Ä`
- `Ã` statt `ß`
- `fÃ¼r` statt `für`
- `â` statt `–`

Betrifft sowohl Frontmatter-Titel als auch Body.

**Fix-Ansatz:**
1. `resp.encoding` aus HTTP-Headern (`Content-Type: text/html; charset=...`)
2. Fallback: `<meta charset="...">` aus HTML parsen
3. Notfalls: `chardet.detect(resp.content)` → `resp.encoding = detected`
4. Oder: `resp.content.decode('utf-8', errors='replace')`

## Betroffener Code

```python
# ingest_source.py, Zeile 191-206
def fetch_url(url: str) -> Tuple[str, str]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WikiBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    html = resp.text  # ← Bug 2: encoding

    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Untitled"

    from markdownify import markdownify as md
    markdown = md(html, heading_style="ATX")  # ← Bug 1: kein HTML-Cleaning
    return title, markdown
```

## Betroffene Dateien

Nur Dateien, die via `ingest_source.py --url` ingestiert wurden. Die meisten Wiki-Sources
kommen via `--text` (E-Mail) oder `--file` (RSS/YouTube) — diese sind nicht betroffen.
