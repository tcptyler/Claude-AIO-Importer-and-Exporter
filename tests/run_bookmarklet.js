// Test-only: open the mock chat, install the bookmark link exactly as built, click it, save the download.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [port, html, out] = process.argv.slice(2);
  const href = fs.readFileSync(html, 'utf8').match(/id="bm" href="([^"]+)"/)[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&');
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true });
  await ctx.addCookies([{ name: 'lastActiveOrg', value: '11111111-1111-4111-8111-111111111111', url: `http://127.0.0.1:${port}` }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${port}/chat/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee`);
  await page.evaluate(h => { const a = document.createElement('a'); a.id = 'bmtest'; a.href = h; a.textContent = 'bm'; document.body.appendChild(a); }, href);
  const dl = page.waitForEvent('download', { timeout: 30000 });
  await page.click('#bmtest');
  const d = await dl;
  await d.saveAs(out);
  await page.waitForFunction(() => window.__sessionExport && window.__sessionExport.done, null, { timeout: 30000 });
  const s = await page.evaluate(() => ({ summary: window.__sessionExport.summary, error: window.__sessionExport.error, status: window.__sessionExport.status }));
  console.log(JSON.stringify({ suggested: d.suggestedFilename(), errors, ...s }, null, 2));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
