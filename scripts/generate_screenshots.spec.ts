import { test } from '@playwright/test';
import * as path from 'path';

const ASSETS_DIR = path.resolve(__dirname, '../docs/assets');

test.describe('Generate documentation screenshots', () => {
  test('capture 1. Hero Workspace', async ({ page }) => {
    await page.setViewportSize({ width: 1380, height: 860 });
    await page.goto('/');
    await page.locator('main[aria-busy="false"]').waitFor();

    // Load Mixed (Thumb -> ARM + Data) preset
    await page.getByRole('button', { name: 'Mixed (Thumb ➔ ARM + Data)', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();

    const stepBtn = page.getByRole('button', { name: 'Step', exact: true });
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.screenshot({
      path: path.join(ASSETS_DIR, 'hero_workspace.png'),
    });
  });

  test('capture 2. Disassembly Import Workflow', async ({ page }) => {
    await page.setViewportSize({ width: 1380, height: 860 });
    await page.goto('/');
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.getByRole('combobox', { name: 'Input', exact: true }).selectOption('disassembly');
    const disasm = `1000: E3A0002A  MOV  r0, #42
1004: E2801008  ADD  r1, r0, #8
1008: E58D1000  STR  r1, [sp]
100C: E59D2000  LDR  r2, [sp]`;
    await page.getByLabel('Disassembly text', { exact: true }).fill(disasm);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();

    const stepBtn = page.getByRole('button', { name: 'Step', exact: true });
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.screenshot({
      path: path.join(ASSETS_DIR, 'feature_disassembly.png'),
    });
  });

  test('capture 3. Memory Fault & Deterministic Rollback', async ({ page }) => {
    await page.setViewportSize({ width: 1380, height: 1240 });
    await page.goto('/');
    await page.locator('main[aria-busy="false"]').waitFor();

    const faultCode = `mov r1, #0x50000000
ldr r0, [r1]`;
    await page.getByLabel('Assembly source', { exact: true }).fill(faultCode);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();

    const stepBtn = page.getByRole('button', { name: 'Step', exact: true });
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    // Second step attempts to read unmapped 0x50000000
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.screenshot({
      path: path.join(ASSETS_DIR, 'feature_fault_rollback.png'),
    });
  });
});
