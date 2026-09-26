import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

async function ready(page: Page) {
  await expect(page.locator('main')).toHaveAttribute('aria-busy', 'false');
}
async function click(page: Page, name: string) {
  await page.getByRole('button', { name, exact: true }).click();
  await ready(page);
}
async function load(page: Page, source: string, mode = 'arm') {
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption(mode);
  await page.getByLabel('Assembly source', { exact: true }).fill(source);
  await click(page, 'Load');
  await expect(page.getByLabel('R0', { exact: true })).toBeVisible();
}
async function edit(page: Page, register: string, value: string) {
  await page.getByLabel(register, { exact: true }).fill(value);
  await click(page, `Apply ${register}`);
}
async function patch(page: Page, type: string, value: string, address = '0x20000000') {
  await page.getByLabel('Patch address', { exact: true }).fill(address);
  await page.getByRole('combobox', { name: 'Patch type', exact: true }).selectOption(type);
  await page.getByLabel(type === 'word' ? 'Word value' : type === 'zero' ? 'Zero-fill length (bytes)' : 'Hex bytes', { exact: true }).fill(value);
  await click(page, type === 'zero' ? 'Zero-fill memory' : 'Apply memory patch');
}
const memoryRow = (page: Page, address: string) => page.getByRole('region', { name: 'Memory', exact: true }).locator(`tr[data-address="${address}"]`);

for (const mode of ['arm', 'thumb']) for (const kind of ['assembly', 'disassembly']) {
  test(`${mode} ${kind}: packaged Load/edit/Step/Reset and file input`, async ({ page }) => {
    await page.goto('/');
    await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption(mode);
    await page.getByRole('combobox', { name: 'Input', exact: true }).selectOption(kind);
    const source = mode === 'arm' ? 'mov r0, #5\nadd r1, r0, #3' : 'movs r0, #5\nmovw r1, #8';
    const imported = mode === 'arm' ? '1000: E3A00005 MOV r0,#5\n1004: E2801003 ADD r1,r0,#3' : '1000: 2005 MOVS r0,#5\n1002: F240 0108 MOVW r1,#8';
    await page.getByLabel('Read local text file').setInputFiles({ name: 'snippet.s', mimeType: 'text/plain', buffer: Buffer.from(kind === 'assembly' ? source : imported) });
    await click(page, 'Load');
    await edit(page, 'R0', '7');
    await click(page, 'Step');
    await expect(page.getByLabel('R0', { exact: true })).toHaveValue('0x00000005');
    await expect(page.locator('[aria-current="step"]')).toHaveAttribute('data-address', mode === 'arm' ? '4100' : '4098');
    await click(page, 'Step');
    await expect(page.getByLabel('R1', { exact: true })).toHaveValue('0x00000008');
    await click(page, 'Reset');
    await expect(page.getByLabel('R0', { exact: true })).toHaveValue('0x00000007');
    await expect(page.locator('.changed')).toHaveCount(0);
    await expect(page.locator('.toolbar')).toContainText('step_seq 2');
  });
}

for (const mode of ['arm', 'thumb']) test(`${mode}: partial memory fault, repair, store, baseline and stack`, async ({ page }) => {
  await load(page, 'ldr r0, [r1]\nstr r0, [r2]\npush {r0}\npop {r3}', mode);
  await edit(page, 'R1', '0x20000000');
  await edit(page, 'R2', '0x20000004');
  await click(page, 'Step');
  await expect(page.getByRole('region', { name: 'Status & diagnostics' })).toContainText('Previous state restored');
  await expect(page.locator('.toolbar')).toContainText('step_seq 0');
  await patch(page, 'bytes', '78');
  await expect(memoryRow(page, '0x20000000')).toContainText('??');
  await click(page, 'Step');
  await expect(page.locator('.toolbar')).toContainText('step_seq 0');
  await patch(page, 'word', '0x12345678');
  await expect(memoryRow(page, '0x20000000')).toContainText('0x12345678');
  await expect(memoryRow(page, '0x20000004')).toContainText('unknown');
  await click(page, 'Step');
  await expect(page.getByLabel('R0', { exact: true })).toHaveValue('0x12345678');
  await click(page, 'Step');
  await expect(page.locator('.toolbar')).toContainText('step_seq 1');
  await patch(page, 'zero', '4', '0x20000004');
  await click(page, 'Step');
  await expect(memoryRow(page, '0x20000004').locator('.changed')).toHaveCount(4);
  await patch(page, 'bytes', 'aa', '0x20000005');
  await expect(page.locator('.changed')).toHaveCount(0);
  await click(page, 'Step');
  const stack = page.getByRole('region', { name: 'Stack', exact: true });
  await expect(stack.locator('tr.current')).toContainText('0x12345678');
  await expect(stack.locator('tr.current')).toContainText('synthetic stack');
  await expect.poll(() => stack.locator('tr.current').evaluate(row => {
    const pane = row.closest('.memory-table')!.getBoundingClientRect();
    const marker = row.getBoundingClientRect();
    return marker.top >= pane.top && marker.bottom <= pane.bottom;
  })).toBe(true);
  await expect(stack.locator('.changed')).toHaveCount(4);
  await page.screenshot({ path: test.info().outputPath('workspace.png'), fullPage: true });
  await click(page, 'Lower addresses');
  await click(page, 'Follow SP');
  await click(page, 'Step');
  await expect(page.getByLabel('R3', { exact: true })).toHaveValue('0x12345678');
  await expect(stack.locator('tr.current')).toContainText('??');
  await click(page, 'Reset');
  await expect(memoryRow(page, '0x20000004')).toContainText('0x0000aa00');
  await expect(page.locator('.changed')).toHaveCount(0);
  await expect(stack.locator('tr[data-address="0x200ffffc"]')).toContainText('0x00000000');
  await patch(page, 'bytes', '00', '0x1000');
  await expect(page.getByRole('alert')).toContainText('cannot overlap code');
  await expect(page.getByLabel('Start / current PC')).toHaveValue('0x00001000');
});

test('keyboard controls, pending exclusion, lost Step recovery and isolated pages', async ({ page, context }) => {
  await load(page, 'loop: b loop');
  const second = await context.newPage();
  await load(second, 'mov r0, #9');
  await click(second, 'Step');
  let count = 0;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/step', async route => {
    count++;
    await route.fetch();
    await gate;
    await route.abort('failed');
  });
  const step = page.getByRole('button', { name: 'Step', exact: true });
  await step.focus();
  await page.keyboard.press('Enter');
  await expect(step).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Apply memory patch' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Inspect memory' })).toBeDisabled();
  release();
  await ready(page);
  await expect(page.getByRole('region', { name: 'Status & diagnostics' })).toContainText('completion confirmed');
  expect(count).toBe(1);
  await expect(page.locator('.toolbar')).toContainText('step_seq 1');
  await expect(page.getByLabel('Start / current PC')).toHaveValue('0x00001000');
  await expect(second.getByLabel('R0', { exact: true })).toHaveValue('0x00000009');
  await page.close();
  await click(second, 'Reset');
  await expect(second.getByLabel('R0', { exact: true })).toHaveValue('0x00000000');
  await second.close();
});

test('rejected replacement and limits preserve state; Go, custom stack and narrow layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByText('Scratch stack setup', { exact: true }).click();
  await page.getByLabel('Use custom scratch stack').check();
  await page.getByLabel('Stack base', { exact: true }).fill('0x3000');
  await page.getByLabel('Stack size (bytes)').fill('64');
  await page.getByLabel('Assembly source', { exact: true }).fill('mov r0, #5\nmov r1, #8');
  await click(page, 'Load');
  await expect(page.getByLabel('SP / R13', { exact: true })).toHaveValue('0x00003040');
  await page.getByLabel('Assembly source', { exact: true }).fill('not_an_instruction');
  await click(page, 'Load');
  await expect(page.locator('.instruction')).toHaveCount(2);
  await expect(page.getByRole('region', { name: 'Status & diagnostics' })).toContainText('assembly_error');
  await page.getByLabel('Start / current PC').fill('0x1004');
  await page.getByLabel('Start / current PC').press('Enter');
  await ready(page);
  await expect(page.locator('.toolbar')).toContainText('step_seq 0');
  await expect(page.locator('[aria-current="step"]')).toHaveAttribute('data-address', '4100');
  await page.getByLabel('Inspection bytes').fill('4097');
  await click(page, 'Inspect memory');
  await expect(page.getByRole('alert').filter({ hasText: '4096' })).toBeVisible();
  await page.getByLabel('Inspection bytes').fill('4');
  await page.getByLabel('Memory address', { exact: true }).fill('0xfffffffc');
  await click(page, 'Inspect memory');
  await expect(memoryRow(page, '0xfffffffc')).toContainText('unknown');
  await page.getByRole('button', { name: 'Step', exact: true }).focus();
  await page.keyboard.press('Enter');
  await ready(page);
  await expect(page.getByLabel('R1', { exact: true })).toHaveValue('0x00000008');
  await expect(page.locator('[aria-current="step"]')).toHaveCount(0);
  await click(page, 'Reset');
  await expect(page.getByLabel('Start / current PC')).toHaveValue('0x00001004');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('mobile.png'), fullPage: true });
});
