// Test-only: run the raw capture.js the way Claude in Chrome's javascript tool would, then poll.
const { chromium } = require('playwright'); const fs = require('fs');
(async () => {
  const [port, js] = process.argv.slice(2);
  const b = await chromium.launch(); const ctx = await b.newContext({ acceptDownloads: true }); const page = await ctx.newPage();
  await page.goto(`http://127.0.0.1:${port}/chat/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee`);
  const dl = page.waitForEvent('download');
  await page.evaluate(fs.readFileSync(js, 'utf8'));
  let s; for (let i = 0; i < 60; i++) { s = await page.evaluate(() => JSON.stringify({done: window.__sessionExport.done, summary: window.__sessionExport.summary, error: window.__sessionExport.error})); if (JSON.parse(s).done) break; await new Promise(r => setTimeout(r, 500)); }
  console.log(s.slice(0, 300), '| download:', (await dl).suggestedFilename()); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
