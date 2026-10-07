// Separate self-test process: owns exactly one connection, context and page.
import { loadPlaywright } from '../playwright_loader.mjs';
import { openBrowser } from '../browser_transport.mjs';

const { pw, info } = loadPlaywright();
const transport = await openBrowser(pw, info);
const context = await transport.browser.newContext();
const page = await context.newPage();

async function state() {
  return {
    cookies: (await context.cookies()).map((c) => [c.name, c.value]),
    storage: await page.evaluate(() => ({ local: localStorage.getItem('owner'), session: sessionStorage.getItem('owner') })),
  };
}

await page.goto(process.argv[2]);
process.send({ event: 'ready', initial: await state(), connected: transport.connected,
  browser_version: transport.browserVersion, playwright_client_version: transport.playwrightVersion });
process.on('message', async ({ id, op, value }) => {
  try {
    if (op === 'seed') {
      await context.addCookies([{ name: 'owner', value, url: page.url() }]);
      await page.evaluate((owner) => { localStorage.setItem('owner', owner); sessionStorage.setItem('owner', owner); }, value);
    } else if (op === 'close') {
      await transport.close([context]);
      process.send({ id, result: 'closed' }, () => process.exit(0));
      return;
    } else if (op === 'navigate') {
      await page.reload();
    } else if (op !== 'probe') throw new Error(`unknown operation ${op}`);
    process.send({ id, result: await state() });
  } catch (err) {
    process.send({ id, error: err.message });
  }
});
