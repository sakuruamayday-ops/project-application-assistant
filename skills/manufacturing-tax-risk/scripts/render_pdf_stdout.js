#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

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
  if (!input) throw new Error('Usage: render_pdf_stdout.js /absolute/path/report.html | -');
  const { chromium } = loadPlaywright();
  const singleProcess = process.env.REPORT_CHROMIUM_SINGLE_PROCESS === '1';
  const chromeCandidates = [process.env.CHROME_PATH];
  if (!singleProcess) {
    chromeCandidates.push(
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    );
  }
  const executablePath = chromeCandidates.find((candidate) => candidate && fs.existsSync(candidate));
  const options = { headless: true, ...(executablePath ? { executablePath } : {}) };
  if (singleProcess) {
    options.args = ['--single-process', '--no-zygote'];
  }
  const contents = input === '-' ? fs.readFileSync(0, 'utf8') : null;
  const browser = await chromium.launch(options);
  try {
    const page = await browser.newPage();
    if (contents === null) {
      await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: 'networkidle' });
    } else {
      await page.setContent(contents, { waitUntil: 'load' });
    }
    await page.evaluate(async () => { await document.fonts.ready; });
    const pdf = await page.pdf({
      format: 'A4', printBackground: true, preferCSSPageSize: true,
      displayHeaderFooter: false, margin: { top: 0, right: 0, bottom: 0, left: 0 },
    });
    process.stdout.write(pdf);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
