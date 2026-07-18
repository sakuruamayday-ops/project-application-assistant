#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    process.env.NODE_MODULES && path.join(process.env.NODE_MODULES, 'playwright'),
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return require(candidate);
  }
  return require('playwright');
}

(async () => {
  const input = process.argv[2];
  if (!input) throw new Error('Usage: render_pdf_stdout.js /absolute/path/report.html');
  const { chromium } = loadPlaywright();
  const chromeCandidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ].filter(Boolean);
  const executablePath = chromeCandidates.find((candidate) => fs.existsSync(candidate));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const page = await browser.newPage();
  await page.goto(`file://${path.resolve(input)}`, { waitUntil: 'networkidle' });
  const pdf = await page.pdf({
    format: 'A4', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: false, margin: { top: 0, right: 0, bottom: 0, left: 0 },
  });
  await browser.close();
  process.stdout.write(pdf);
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
