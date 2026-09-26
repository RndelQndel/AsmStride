import { test } from '@playwright/test';

test.describe('Generate documentation screenshots', () => {
  test('capture all showcase screenshots', async ({ page }) => {
    // 1. Hero Workspace
    await page.setViewportSize({ width: 1360, height: 1050 });
    await page.goto('/');
    
    const heroCode = `mov r0, #42
mov r1, #10
add r2, r0, r1
str r2, [sp, #-4]!
pop {r3}`;
    await page.getByLabel('Assembly source', { exact: true }).fill(heroCode);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();

    const stepBtn = page.getByRole('button', { name: 'Step', exact: true });
    for (let i = 0; i < 4; i++) {
      await stepBtn.click();
      await page.locator('main[aria-busy="false"]').waitFor();
    }
    await page.screenshot({ path: '../docs/assets/hero_workspace.png', fullPage: true });

    // 2. Disassembly Import Workflow
    await page.goto('/');
    await page.getByRole('combobox', { name: 'Input', exact: true }).selectOption('disassembly');
    const disasm = `1000: E3A0002A  MOV  r0, #42
1004: E2801008  ADD  r1, r0, #8
1008: E58D1000  STR  r1, [sp]
100C: E59D2000  LDR  r2, [sp]`;
    await page.getByLabel('Disassembly text', { exact: true }).fill(disasm);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await page.screenshot({ path: '../docs/assets/feature_disassembly.png', fullPage: true });

    // 3. Memory Fault & Deterministic Rollback
    await page.goto('/');
    const faultCode = `mov r1, #0x50000000
ldr r0, [r1]`;
    await page.getByLabel('Assembly source', { exact: true }).fill(faultCode);
    await page.getByRole('button', { name: 'Load', exact: true }).click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    // Second step attempts to read unmapped 0x50000000
    await stepBtn.click();
    await page.locator('main[aria-busy="false"]').waitFor();
    await page.screenshot({ path: '../docs/assets/feature_fault_rollback.png', fullPage: true });
  });
});
