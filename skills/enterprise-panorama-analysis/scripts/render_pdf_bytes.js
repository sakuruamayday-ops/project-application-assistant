const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

async function main() {
  const input = process.argv[2];
  if (!input) throw new Error("missing HTML path");
  const options = { headless: true };
  if (process.env.REPORT_CHROMIUM_SINGLE_PROCESS === "1") {
    options.args = ["--single-process", "--no-zygote"];
  }
  const contents = input === "-" ? fs.readFileSync(0, "utf8") : null;
  const browser = await chromium.launch(options);
  try {
    const page = await browser.newPage();
    if (contents === null) {
      await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "networkidle" });
    } else {
      await page.setContent(contents, { waitUntil: "load" });
    }
    await page.evaluate(async () => { await document.fonts.ready; });
    const pdf = await page.pdf({
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
      displayHeaderFooter: false,
    });
    process.stdout.write(pdf.toString("base64"));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});

