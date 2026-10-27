const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto('http://localhost:3000/dashboard');
  await page.waitForURL(/\/login/);
  await page.getByText('No account? Register').click();
  await page.getByLabel('Email').fill('wayne@example.com');
  await page.getByLabel('Password').fill('password123');
  await page.getByRole('button', { name: 'Register' }).click();
  await page.waitForURL(/\/dashboard/);
  assert.ok(await page.getByRole('heading', { name: 'Dashboard' }).isVisible());

  await page.getByLabel('Product URL').fill('https://www.jbhifi.com.au/products/sony-wh1000xm6');
  await page.getByRole('button', { name: 'Track product' }).click();
  await page.waitForURL(/\/products\//);
  await page.getByRole('heading', { level: 1 }).waitFor();
  const name = await page.getByRole('heading', { level: 1 }).innerText();
  console.log('product:', name);
  assert.match(await page.locator('.stats').innerText(), /A\$549/);
  await page.getByLabel('Target price').fill('400');
  await page.getByRole('button', { name: 'Track', exact: true }).click();
  await page.getByText('Now tracking this product.').waitFor();

  await page.getByRole('link', { name: 'War Room' }).click();
  await page.waitForURL(/war-room/);
  await page.getByText('Live', { exact: true }).waitFor({ timeout: 10000 });
  const scan = await (await fetch('http://localhost:8000/__scan/jbhifi_sale.html')).json();
  console.log('scan:', scan);
  await page.locator('section', { hasText: 'TARGET HIT' }).getByText('A$399').waitFor({ timeout: 10000 });
  console.log('last scan label:', await page.getByText(/Last scan:/).innerText());
  await page.screenshot({ path: '/tmp/e2e/war-room.png', fullPage: true });

  await page.getByRole('link', { name: 'Dashboard' }).click();
  await page.getByRole('heading', { name: /Target Hits/ }).waitFor();
  await page.locator('main .tag', { hasText: 'Target hit' }).first().waitFor({ timeout: 10000 });
  await page.screenshot({ path: '/tmp/e2e/dashboard.png', fullPage: true });
  await page.locator('.title').first().click();
  await page.waitForURL(/\/products\//);
  await page.locator('svg[aria-label="Price history"]').waitFor({ timeout: 10000 });
  await page.screenshot({ path: '/tmp/e2e/product.png', fullPage: true });

  for (const path of ['/watchlist', '/deals', '/settings']) {
    await page.goto('http://localhost:3000' + path);
    await page.locator('h1').waitFor();
    console.log(path, 'ok:', await page.locator('h1').innerText());
  }
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.waitForURL(/\/login/);
  console.log('errors:', errors);
  await browser.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
