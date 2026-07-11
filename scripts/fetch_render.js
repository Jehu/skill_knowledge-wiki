/**
 * Fetch a URL with full JS rendering via Playwright.
 * Usage: node fetch_render.js <url> [timeout_ms]
 * Outputs JSON to stdout: { html, title, text, trimmed_html }
 *
 * - html: full rendered HTML (for embed detection, ~500KB)
 * - title: document.title
 * - text: innerText of the main content area (plain text, cleaned)
 * - trimmed_html: body HTML with chrome stripped (for content extraction)
 */
const { chromium } = require('playwright');

(async () => {
  const url = process.argv[2];
  if (!url) {
    console.error('Usage: node fetch_render.js <url> [timeout_ms]');
    process.exit(1);
  }
  const timeout = parseInt(process.argv[3] || '45000', 10);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (compatible; WikiBot/1.0; +https://github.com/Jehu/knowledge-wiki)'
  });
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout });
    await page.waitForTimeout(3000);

    // Full rendered HTML (for embed detection)
    const html = await page.content();
    const title = await page.title();

    // Extract clean text content from the main area
    const extraction = await page.evaluate(() => {
      // Try to find the main content container
      const selectors = [
        '[class*="feedPermalinkUnit"]',
        '[class*="noteContent"]',
        '[class*="postContent"]',
        'article',
        '[role="main"]',
        'main',
      ];
      let container = null;
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 100) {
          container = el;
          break;
        }
      }

      // Get clean inner text
      let text = '';
      if (container) {
        text = container.innerText;
      } else {
        // Fallback: body text minus header/nav/footer
        const body = document.body.cloneNode(true);
        body.querySelectorAll('nav, header, footer, aside, [role="navigation"]').forEach(el => el.remove());
        text = body.innerText;
      }

      // Get trimmed HTML of the same container for content extraction
      let trimmed_html = '';
      if (container) {
        trimmed_html = container.innerHTML;
      }

      return { text: text || '', trimmed_html: trimmed_html || '' };
    });

    const result = {
      html,
      title,
      text: extraction.text,
      trimmed_html: extraction.trimmed_html,
    };
    console.log(JSON.stringify(result));
  } catch (err) {
    console.error('Error:', err.message);
    process.exit(2);
  } finally {
    await browser.close();
  }
})();
