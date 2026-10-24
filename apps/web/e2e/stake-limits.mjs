// Local UI regression: no production requests or account writes. Start Next on :3011 first.
import { chromium, expect } from '@playwright/test';

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const base = process.argv[2] ?? 'http://localhost:3011';
try {
  for (const width of [390, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const lines = [
      ['blood', 'First blood', 1000], ['tower', 'First tower', 424], ['gold', 'Gold at 15', 1000],
    ].map(([marketId, marketTitle, stake]) => ({ marketId, marketTitle, stake, outcomeId: `${marketId}-t1`,
      outcomeLabel: 'T1', eventLabel: 'LOS vs T1', odds: '2.00', oddsVersion: 1 }));
    await page.addInitScript(lines => localStorage.setItem('rift.slip.v1', JSON.stringify(lines)), lines);
    let quotes = 0;
    let lastItems;
    const violation = (id, placed) => ({ market_id: id, cap_rc: 1000, placed_rc: placed,
      max_stake_rc: 1000 - placed, requested_stake_rc: 1000 });
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body = {};
      if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
      if (path.endsWith('/quotes')) {
        quotes++;
        lastItems = route.request().postDataJSON().items;
        if (quotes === 1) return route.fulfill({ status: 409, json: { error: { code: 'STAKE_LIMIT',
          message: 'Two picks exceed their limits.', details: { violations: [violation('blood', 700), violation('gold', 1000)] } } } });
        const items = lastItems.map(item => ({ ...item, market_id: item.outcome_id.split('-')[0],
          odds: '2.00', odds_version: 1, potential_return_rc: item.stake_rc * 2, outcome_label: 'T1' }));
        return route.fulfill({ json: { quote_id: `quote-${quotes}`, items,
          total_stake_rc: items.reduce((sum, i) => sum + i.stake_rc, 0) } });
      }
      if (path.endsWith('/tickets')) return route.fulfill({ status: 409, json: { error: { code: 'STAKE_LIMIT',
        message: 'Another bet used some room.', details: violation('blood', 800) } } });
      const wallet = { available_rc: 4424, open_stake_rc: 0, granted_rc: 4424, recovery_due_rc: 0, realized_net_rc: 0 };
      if (path.endsWith('/me')) body = { user: { id: 'tester', display_name: 'Tester' }, wallet };
      else if (path.endsWith('/season/current')) body = { match_days: [], timezone: 'America/Phoenix' };
      else if (path.endsWith('/me/wallet')) body = { ...wallet, ledger: [] };
      else if (path.includes('/me/picks')) body = { picks: [] };
      return route.fulfill({ json: body });
    });
    await page.goto(`${base}/profile`);
    let panel;
    if (width < 1000) {
      await page.locator('.slipbar').click();
      panel = page.getByRole('dialog', { name: 'Your slip' });
    } else panel = page.getByRole('complementary', { name: 'Slip', exact: true });
    await panel.getByRole('button', { name: 'Review picks', exact: true }).click();
    await expect(panel.locator('[data-stake-error]')).toHaveCount(2);
    await expect(panel.getByText('No bets were placed.', { exact: true })).toBeVisible();
    const blood = panel.locator('.slip-line').filter({ hasText: 'First blood' });
    await expect(blood).toContainText('700 RC staked');
    await expect(blood).toContainText('300 RC more');
    await expect(panel.getByRole('button', { name: 'Fix highlighted stakes to continue' })).toBeDisabled();
    await blood.getByRole('button', { name: 'Use 300 RC', exact: true }).click();
    await panel.getByRole('button', { name: 'Remove this pick — limit reached' }).click();
    await expect(panel.locator('[data-stake-error]')).toHaveCount(0);
    await expect(panel.locator('.slip-line').filter({ hasText: 'First tower' })).toContainText('424');
    await panel.getByRole('button', { name: 'Review picks', exact: true }).click();
    await expect(panel.getByRole('button', { name: /Place 2 picks/ })).toBeVisible();
    expect(lastItems).toEqual([{ outcome_id: 'blood-t1', stake_rc: 300 }, { outcome_id: 'tower-t1', stake_rc: 424 }]);
    // A concurrent placement can consume room after review; legacy one-market details still work.
    await panel.getByRole('button', { name: /Place 2 picks/ }).click();
    await expect(blood.getByRole('button', { name: 'Use 200 RC', exact: true })).toBeVisible();
    await expect(panel.locator('[data-stake-error]')).toHaveCount(1);
    await blood.getByRole('button', { name: 'Use 200 RC', exact: true }).click();
    await expect(panel.getByRole('button', { name: 'Review picks', exact: true })).toBeEnabled();
    await expect(panel).toBeVisible();
    expect(errors).toEqual([]);
    console.log(`PASS ${width}px: all offending picks identified, remaining room, fix/remove, retry and acceptance-time errors`);
    await context.close();
  }
} finally {
  await browser.close();
}
