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
    await page.setViewportSize({ width: 1360, height: 1050 });
    await page.goto('/');
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.getByRole('combobox', { name: 'Input', exact: true }).selectOption('disassembly');
    await page.getByRole('combobox', { name: 'Format', exact: true }).selectOption('fromelf');

    const fromelfDisasm = `** Section #1 '.text' (SHT_PROGBITS) [SHF_ALLOC + SHF_EXECINSTR]
    Size   : 20 bytes
    Address: 0x08000100

    $a.0
    calc_sum
        0x08000100:    e3a00000    ....    MOV      r0,#0
        0x08000104:    e3a01005    ....    MOV      r1,#5
        0x08000108:    e0800001    ....    ADD      r0,r0,r1
        0x0800010c:    e2511001    ....    SUBS     r1,r1,#1
        0x08000110:    1afffffc    ....    BNE      0x08000108`;

    await page.getByLabel('Disassembly text', { exact: true }).fill(fromelfDisasm);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();

    const stepBtn = page.getByRole('button', { name: 'Step', exact: true });
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.screenshot({
      path: path.join(ASSETS_DIR, 'feature_disassembly.png'),
      fullPage: true,
    });
  });

  test('capture 3. Memory Fault & Deterministic Rollback', async ({ page }) => {
    await page.setViewportSize({ width: 1360, height: 1050 });
    await page.goto('/');
    await page.locator('main[aria-busy="false"]').waitFor();

    const faultCode = `mov r1, #0x20000000
ldr r0, [r1, #4]`;
    await page.getByLabel('Assembly source', { exact: true }).fill(faultCode);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();

    const stepBtn = page.getByRole('button', { name: 'Step', exact: true });
    // Step 1: mov r1, #0x20000000
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    // Step 2: ldr r0, [r1, #4] -> triggers unmapped memory fault at 0x20000004
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();

    await page.screenshot({
      path: path.join(ASSETS_DIR, 'feature_fault_rollback.png'),
      fullPage: true,
    });
  });
});
