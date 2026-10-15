import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { expect } = require('@playwright/test');
const root = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(root, 'docs', 'screenshots');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const errors = [];
const checks = [];
page.on('pageerror', error => errors.push(error.message));
const base = process.env.DEMO_BASE_URL || 'http://127.0.0.1:8765';
const check = name => checks.push(name);
const nav = name => page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: new RegExp(name) }).click();
const screenshot = async name => {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForFunction(() => {
    const content = document.querySelector('.view-content');
    return !content || getComputedStyle(content).opacity === '1';
  });
  return page.screenshot({ path: path.join(output, name), fullPage: true });
};
const evaluateResponse = () => page.waitForResponse(response => response.url().endsWith('/api/evaluate') && response.request().method() === 'POST' && response.status() === 200);
const changeScenario = async id => {
  await Promise.all([evaluateResponse(), page.getByLabel('业务场景').selectOption(id)]);
  await expect(page.locator('.updating-status')).toHaveCount(0);
};
const applyFilters = async () => {
  await Promise.all([evaluateResponse(), page.getByRole('button', { name: '应用条件', exact: true }).click()]);
  await expect(page.locator('.updating-status')).toHaveCount(0);
};

try {
  await page.goto(base, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: '风险总览', exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: /算力需求预测曲线/ })).toBeVisible();
  await expect(page.locator('.kpi-value').nth(2)).toContainText('4');
  await expect(page.locator('.kpi-value').nth(3)).toContainText('8');
  await expect(page.locator('.response-meta')).toContainText('96.00');
  check('桌面总览与主案例图表');
  await screenshot('01-风险总览.png');

  await nav('资源调度');
  await expect(page.locator('.supplier-table tbody tr')).toHaveCount(5);
  await expect(page.locator('.selected-supplier')).toContainText('澄海算力');
  await page.getByLabel('采购预算上限', { exact: true }).fill('80');
  await applyFilters();
  await expect(page.locator('.selected-supplier')).toContainText('暂无完整匹配方案');
  check('预算80实际筛选并显示未解决状态');
  await page.getByLabel('采购预算上限', { exact: true }).fill('');
  await page.getByLabel('优先排序', { exact: true }).selectOption('quality');
  await applyFilters();
  await expect(page.locator('.selected-supplier')).toContainText('恒稳云');
  await expect(page.locator('.cost-total')).toContainText('116.00');
  check('质量优先真实改变推荐');
  await page.getByLabel('优先排序', { exact: true }).selectOption('cost');
  await applyFilters();
  await screenshot('02-资源调度.png');

  await page.getByLabel('选择恒稳云', { exact: true }).check();
  const [createdResponse] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/plans') && response.request().method() === 'POST'),
    page.getByRole('button', { name: '保存资源预案', exact: true }).click(),
  ]);
  const created = await createdResponse.json();
  assert.equal(created.cost, 116);
  await nav('预案记录');
  const record = page.locator('.plan-record').filter({ hasText: created.id });
  await expect(record).toBeVisible();
  await record.getByRole('button', { name: '查看详情', exact: true }).click();
  await record.getByRole('button', { name: '模拟确认此预案', exact: true }).click();
  await expect(record.getByRole('button', { name: '已模拟确认', exact: true })).toBeDisabled();
  const [download] = await Promise.all([page.waitForEvent('download'), record.getByRole('link', { name: '下载预案', exact: true }).click()]);
  assert.equal(await download.failure(), null);
  check('手选非首位供应商、保存、模拟确认、浏览器下载');
  await screenshot('03-预案记录.png');
  await page.reload({ waitUntil: 'networkidle' });
  await expect(page.locator('.plan-record').filter({ hasText: created.id })).toBeVisible();
  check('刷新后预案记录持久化');

  await nav('智能体助手');
  await page.getByLabel('向算力智保助手提问').fill('为什么不选更便宜的B？');
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/chat') && response.status() === 200),
    page.getByRole('button', { name: '发送消息', exact: true }).click(),
  ]);
  await expect(page.locator('.chat-panel')).toContainText('北辰算力');
  await expect(page.locator('.chat-panel')).toContainText('离线规则助手');
  await expect(page.locator('.chat-panel')).toContainText('90分钟');
  check('助手调用接口、展示离线模式与B排除依据');
  await page.getByRole('button', { name: '清空对话', exact: true }).click();
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/chat') && response.status() === 200),
    page.getByRole('button', { name: '把预算改成80元，重新匹配', exact: true }).click(),
  ]);
  await expect(page.locator('.chat-panel')).toContainText('预算上限为80元');
  await expect(page.locator('.updating-status')).toHaveCount(0);
  check('实际快捷问题改变预算并同步筛选状态');
  await screenshot('04-智能体助手.png');
  await nav('资源调度');
  await page.getByLabel('采购预算上限', { exact: true }).fill('');
  await applyFilters();
  await nav('智能体助手');
  await page.getByRole('button', { name: '清空对话', exact: true }).click();
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/chat') && response.status() === 200),
    page.getByRole('button', { name: '优先选择质量更高的资源', exact: true }).click(),
  ]);
  await expect(page.locator('.assistant-snapshot')).toContainText('恒稳云');
  check('实际质量优先快捷问题改变推荐');

  await changeScenario('stale');
  await nav('风险总览');
  await expect(page.locator('.insight-banner')).toContainText('数据需要更新');
  await expect(page.locator('.chart-summary')).toContainText('无法评估');
  await expect(page.locator('.chart-summary')).not.toContainText('无短缺');
  check('失效数据界面显示未知而非无风险');
  await screenshot('05-失效数据.png');
  await changeScenario('normal');
  await expect(page.locator('.insight-banner')).toContainText('算力供需平稳');
  check('正常场景无错误预警');
  await changeScenario('insufficient');
  await nav('资源调度');
  await expect(page.locator('.selected-supplier')).toContainText('暂无完整匹配方案');
  check('供应不足界面保留未解决状态');
  await changeScenario('surge');
  await page.getByLabel('采购预算上限', { exact: true }).fill('');
  await page.getByLabel('优先排序', { exact: true }).selectOption('cost');
  await applyFilters();
  await page.getByLabel('回放分钟', { exact: true }).focus();
  await Promise.all([evaluateResponse(), page.getByLabel('回放分钟', { exact: true }).press('End')]);
  await expect(page.locator('.replay-clock')).toHaveText('17:00');
  await expect(page.locator('.selected-supplier')).toContainText('当前无需应急采购');
  check('回放到高峰结束后恢复');
  await Promise.all([evaluateResponse(), page.getByRole('button', { name: '重置回放', exact: true }).click()]);
  await expect(page.locator('.selected-supplier')).toContainText('澄海算力');
  await Promise.all([evaluateResponse(), page.getByRole('button', { name: '前进5分钟', exact: true }).click()]);
  await Promise.all([evaluateResponse(), page.getByRole('button', { name: '前进5分钟', exact: true }).click()]);
  await expect(page.locator('.selected-supplier')).toContainText('恒稳云');
  await Promise.all([evaluateResponse(), page.getByRole('button', { name: '前进5分钟', exact: true }).click()]);
  await expect(page.locator('.selected-supplier')).toContainText('暂无完整匹配方案');
  check('回放推进真实影响交付可行性');
  await Promise.all([evaluateResponse(), page.getByRole('button', { name: '重置回放', exact: true }).click()]);

  await page.setViewportSize({ width: 390, height: 844 });
  for (const view of ['风险总览', '资源调度', '智能体助手', '预案记录']) {
    await nav(view);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${view}存在横向页面溢出`);
    await expect(page.getByRole('heading', { name: view, exact: true })).toBeVisible();
  }
  await nav('风险总览');
  await screenshot('06-手机风险总览.png');
  check('390px手机四页面布局无横向溢出');
  assert.deepEqual(errors, [], '浏览器出现脚本异常');
  check('浏览器无JavaScript运行异常');
  console.log(JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
  await writeFile(path.join(root, 'docs', 'browser-qa-results.json'), JSON.stringify({ passed: checks.length, checks, errors }, null, 2));
} finally {
  await browser.close();
}
