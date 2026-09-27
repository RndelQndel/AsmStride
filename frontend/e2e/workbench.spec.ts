import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';

async function ready(page: import('@playwright/test').Page) {
  await expect(page.locator('main')).toHaveAttribute('aria-busy', 'false');
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await ready(page);
});
test.afterEach(async ({ page }) => {
  await page.evaluate(() => (window as unknown as { __armstride_session: { dispose(): void } }).__armstride_session.dispose());
});

test('light viewport workbench keeps code visible while switching tools and editor tabs', async ({ page }) => {
  await expect(page.getByRole('complementary', { name: 'Primary Sidebar' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Run and Debug' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Source', exact: true })).toHaveAttribute('aria-selected', 'true');
  const source = page.getByLabel('Assembly source', { exact: true });
  await source.fill('mov r0, #7\nadd r1, r0, #2');
  await page.getByRole('button', { name: 'Load', exact: true }).click();
  await ready(page);
  await expect(page.getByRole('tab', { name: 'Disassembly', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByLabel('R0', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Source', exact: true }).click();
  await expect(source).toHaveValue('mov r0, #7\nadd r1, r0, #2');
  await source.press('F7');
  await ready(page);
  await expect(page.getByLabel('R0', { exact: true })).toHaveValue('0x00000007');
  await expect(page.getByRole('status')).toContainText('PC 0x00001004');
  await expect(page.getByRole('status')).toContainText('history 1');
  await page.getByRole('tab', { name: 'Source', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Disassembly', exact: true })).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.getByRole('tab', { name: 'Split', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(source).toBeVisible();
  await expect(page.locator('.code-pane')).toBeVisible();
  for (const tab of ['Problems', 'Output', 'Memory', 'Stack', 'Execution']) {
    await page.getByRole('tab', { name: tab, exact: true }).click();
    await expect(page.getByRole('tab', { name: tab, exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('.code-pane')).toBeVisible();
  }
  await page.getByRole('button', { name: 'Close bottom panel' }).click();
  await expect(page.locator('.bottom-panel')).toBeHidden();
  await page.getByRole('button', { name: 'Toggle bottom panel' }).click();
  await expect(page.locator('.bottom-panel')).toBeVisible();
  await page.getByRole('button', { name: 'Debug tools' }).click();
  await expect(page.getByLabel('Limit steps')).toBeVisible();
  await expect(page.getByLabel('Time limit (ms)')).toHaveValue('2000');
  await page.getByRole('button', { name: 'Memory tools' }).click();
  await page.getByRole('button', { name: 'Inspect stack', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Stack', exact: true })).toBeVisible();
  const geometry = await page.evaluate(() => ({
    bodyHeight: document.documentElement.scrollHeight,
    height: innerHeight,
    editorWidth: document.querySelector('.editor-group')!.getBoundingClientRect().width,
    light: getComputedStyle(document.documentElement).colorScheme,
  }));
  expect(geometry.bodyHeight).toBe(geometry.height);
  expect(geometry.editorWidth).toBeGreaterThan(720);
  expect(geometry.light).toBe('light');
});

test('watchpoint, breakpoint, memory patch and Step Back remain reachable', async ({ page }) => {
  await page.getByLabel('Assembly source', { exact: true }).fill('mov r0, #9\npush {r0}\npop {r1}');
  await page.getByRole('button', { name: 'Load', exact: true }).click();
  await ready(page);
  await page.getByRole('button', { name: 'Toggle breakpoint at 0x00001004' }).click();
  await ready(page);
  await expect(page.getByRole('button', { name: 'Remove breakpoint at 0x00001004' })).toBeVisible();
  await page.getByLabel('Watchpoint address').fill('0x200ffffc');
  await page.getByLabel('Watchpoint access').selectOption('write');
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await ready(page);
  await expect(page.getByRole('button', { name: 'Remove watchpoint at 0x200ffffc' })).toBeVisible();
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  await ready(page);
  await expect(page.getByRole('region', { name: 'execution', exact: true })).toContainText('breakpoint');
  await page.getByRole('button', { name: 'Step', exact: true }).click();
  await ready(page);
  await expect(page.getByText('Watchpoint Hit!', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Stack', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Stack', exact: true }).locator('tr.current')).toContainText('0x00000009');
  await page.getByRole('button', { name: /Step Back/ }).click();
  await ready(page);
  await expect(page.getByRole('status')).toContainText('PC 0x00001004');
  await page.getByRole('tab', { name: 'Memory', exact: true }).click();
  await page.getByLabel('Hex bytes', { exact: true }).fill('01 02 03 04');
  await page.getByRole('button', { name: 'Apply memory patch' }).click();
  await ready(page);
  await expect(page.getByRole('region', { name: 'Memory', exact: true })).toContainText('0x04030201');
  await expect(page.locator('.code-pane')).toBeVisible();
});

test('RV32I registers and stack use ABI state without ARM flags', async ({ page }) => {
  await page.getByLabel('Architecture').selectOption('rv32i-le');
  await page.getByLabel('Assembly source', { exact: true }).fill('addi sp, sp, -16\nli t0, 66\nsw t0, 0(sp)\nlw a0, 0(sp)\nebreak');
  await page.getByRole('button', { name: 'Load', exact: true }).click();
  await ready(page);
  await expect(page.getByLabel('x0 (zero)', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('x31 (t6)', { exact: true })).toBeAttached();
  await expect(page.getByLabel('CPSR', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('RV32I');
  await expect(page.getByRole('status')).not.toContainText('ARM');
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: 'Step', exact: true }).click();
    await ready(page);
  }
  await page.getByRole('tab', { name: 'Stack', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Stack', exact: true }).locator('tr.current')).toContainText('0x00000042');
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  await ready(page);
  await expect(page.getByLabel('x10 (a0)', { exact: true })).toHaveValue('0x00000042');
  await page.getByRole('tab', { name: 'Execution', exact: true }).click();
  await expect(page.getByRole('region', { name: 'execution', exact: true })).toContainText('breakpoint_trap');
});


test('ELF import selects Disassembly and retains symbols and execution', async ({ page }) => {
  const binary = execFileSync('../.venv/bin/python', ['-c', `
import sys
sys.path.insert(0, '..')
from tests.elf.elf_builder import make_elf
sys.stdout.buffer.write(make_elf(
    code=bytes.fromhex('2a00a0e3 1eff2fe1'), entry_point=0x8000,
    mapping_symbols=[(0x8000, 'arm')],
    symbols=[{'name': 'main', 'address': 0x8000, 'size': 8, 'type': 'func', 'bind': 'global'}],
))
`]);
  await page.getByRole('combobox', { name: 'Input', exact: true }).selectOption('elf');
  await page.getByLabel('Select ELF binary').setInputFiles({ name: 'example.elf', mimeType: 'application/octet-stream', buffer: binary });
  await page.getByRole('button', { name: 'Load', exact: true }).click();
  await ready(page);
  await expect(page.getByRole('tab', { name: 'Disassembly', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.symbol-label').filter({ hasText: 'main' })).toBeVisible();
  await page.getByRole('tab', { name: 'Source', exact: true }).click();
  await expect(page.getByText(/ELF source is unavailable/)).toBeVisible();
  await page.getByRole('tab', { name: 'Disassembly', exact: true }).click();
  await page.getByRole('button', { name: 'Step', exact: true }).click();
  await ready(page);
  await expect(page.getByLabel('R0', { exact: true })).toHaveValue('0x0000002a');
});
