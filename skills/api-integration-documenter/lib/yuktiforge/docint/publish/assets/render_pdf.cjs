// Render a LOCAL html file to an A4 PDF with the installed Playwright Chromium. Only file:// pages; every other request is blocked; JavaScript is disabled.
//   node render_pdf.cjs <playwright-node_modules> <page.html> <out.pdf> <header-text> <footer-left>
const [root, page, out, headerText, footerLeft] = process.argv.slice(2);
if (!/^[^:]+$/.test(page)) { console.error("only local files"); process.exit(2); }
const { chromium } = require(`${root}/@playwright/test`);
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const p = await ctx.newPage();
  p.on("request", r => { if (!r.url().startsWith("file:")) { console.error("BLOCKED non-file request:", r.url()); r.abort(); } });
  await p.goto("file://" + page, { waitUntil: "load" });
  const style = "font-family: Helvetica, Arial, sans-serif; font-size: 8px; color: #6B7280; width: 100%; padding: 0 16mm;";
  await p.pdf({
    path: out, format: "A4", printBackground: true, displayHeaderFooter: true, preferCSSPageSize: false,
    margin: { top: "22mm", bottom: "20mm", left: "16mm", right: "16mm" },
    headerTemplate: `<div style="${style} text-align: left; border-bottom: 0.5px solid #CBD5E1; padding-bottom: 3px;">${esc(headerText)}</div>`,
    footerTemplate: `<div style="${style} display: flex; justify-content: space-between;"><span>${esc(footerLeft)}</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>`,
  });
  await browser.close();
  console.log("saved", out);
})().catch(e => { console.error(e.message); process.exit(1); });
