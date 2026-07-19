/**
 * Playwright E2E 测试 — SQL 智能分析助手核心用户流程。
 *
 * 覆盖场景：
 * 1. 页面加载布局验证
 * 2. 左侧数据源面板展开/折叠
 * 3. 数据源面板加载表列表 + 点击查看字段详情
 * 4. 输入问题并发起查询（SSE 流）
 * 5. 流式状态展示（thinking → schema_linking → executing → result）
 * 6. 结果表格渲染
 * 7. SQL 代码块展示与复制
 * 8. 右侧历史记录抽屉
 * 9. 新建会话
 *
 * 前置条件：
 * - 后端运行在 http://localhost:8000
 * - 前端运行在 http://localhost:3000
 * - 目标数据库已连接且有表数据
 *
 * Run::
 *
 *     npx playwright test e2e/query_flow.spec.ts
 *
 * Or with UI::
 *
 *     npx playwright test --ui
 */

import { test, expect } from '@playwright/test';

// ============================================================
// 辅助函数
// ============================================================

/** 等待 SSE 流式状态更新完成，直到出现 result 或 error */
async function waitForQueryComplete(page: import('@playwright/test').Page) {
  // 等待最终结果出现 — 可能是表格、错误提示或空数据提示
  await page.waitForFunction(() => {
    // 检查页面中是否出现了结果类元素
    const resultElements = document.querySelectorAll(
      // 结果表格区域、错误 Alert、空状态
      '.ant-table-wrapper, .ant-alert-error, .ant-alert-warning, .ant-empty'
    );
    return resultElements.length > 0;
  }, { timeout: 60000 });
}

// ============================================================
// 测试
// ============================================================

test.describe('核心用户流程', () => {
  test.beforeEach(async ({ page }) => {
    // 导航到首页
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
  });

  test('1. 页面布局 — 左侧面板 + 主区域 + 顶栏', async ({ page }) => {
    // 顶栏标题
    await expect(page.getByText('SQL 智能分析助手')).toBeVisible();

    // 左侧数据源面板
    await expect(page.getByText('数据源')).toBeVisible();

    // 输入框
    const textarea = page.locator('textarea');
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveAttribute('placeholder', /输入数据查询需求/);

    // 查询按钮
    await expect(page.getByText('查询')).toBeVisible();
  });

  test('2. 左侧数据源面板 — 加载表列表', async ({ page }) => {
    // 等待表列表加载（Skeleton 消失）
    await page.waitForSelector('.ant-skeleton', { state: 'detached', timeout: 15000 });

    // 应该至少有一个表名
    const tableItems = page.locator('.ant-list-item');
    const count = await tableItems.count();
    expect(count).toBeGreaterThan(0);

    // 每个表项应显示字段数和行数
    const firstItem = tableItems.first();
    await expect(firstItem).toContainText(/字段/);
  });

  test('3. 数据源面板 — 点击表名查看字段详情', async ({ page }) => {
    // 等待表列表加载
    await page.waitForSelector('.ant-skeleton', { state: 'detached', timeout: 15000 });

    // 点击第一张表
    const firstTable = page.locator('.ant-list-item').first();
    await firstTable.click();

    // Modal 弹窗应显示字段详情表格
    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();
    await expect(modal.locator('.ant-table')).toBeVisible();

    // 应包含字段名列
    await expect(modal.getByText('字段名')).toBeVisible();
    await expect(modal.getByText('类型')).toBeVisible();

    // 关闭弹窗
    await modal.locator('.ant-modal-close').click();
    await expect(modal).not.toBeVisible();
  });

  test('4. 发起查询 — SSE 流式展示状态变化', async ({ page }) => {
    // 在输入框中输入问题
    const textarea = page.locator('textarea');
    await textarea.fill('查询用户总数');

    // 点击查询按钮
    await page.getByText('查询').click();

    // 流式状态指示器应出现
    // 状态标签会包含 "正在理解语义" / "正在检索表结构" / "正在执行查询"
    await expect(page.getByText(/正在/)).toBeVisible({ timeout: 5000 });

    // 等待查询完成
    await waitForQueryComplete(page);

    // 结果展示：应有 SQL 代码块
    const sqlBlock = page.locator('text=SQL').first();
    await expect(sqlBlock).toBeVisible({ timeout: 5000 });
  });

  test('5. 结果表格渲染', async ({ page }) => {
    // 输入查询
    const textarea = page.locator('textarea');
    await textarea.fill('SELECT * FROM users LIMIT 5');
    await page.getByText('查询').click();

    // 等待完成
    await waitForQueryComplete(page);

    // 结果表格应渲染
    const table = page.locator('.ant-table-wrapper');
    await expect(table).toBeVisible({ timeout: 15000 });

    // 显示行数和耗时
    await expect(page.getByText(/共 .+ 行/)).toBeVisible();
  });

  test('6. SQL 复制功能', async ({ page }) => {
    const textarea = page.locator('textarea');
    await textarea.fill('查询用户总数');
    await page.getByText('查询').click();
    await waitForQueryComplete(page);

    // 复制按钮应可见
    const copyBtn = page.getByText('复制').first();
    await expect(copyBtn).toBeVisible({ timeout: 10000 });

    // 点击复制
    await copyBtn.click();

    // 复制成功提示
    await expect(page.getByText('SQL 已复制')).toBeVisible({ timeout: 3000 });
  });

  test('7. 历史记录抽屉 — 打开/关闭', async ({ page }) => {
    // 点击顶栏历史按钮
    const historyBtn = page.locator('button').filter({ has: page.locator('.anticon-history') });
    await historyBtn.click();

    // 抽屉应打开
    const drawer = page.locator('.ant-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText('历史记录')).toBeVisible();

    // 点击新建会话
    await drawer.getByText('+ 新建会话').click();

    // 抽屉关闭，消息列表清空
    await expect(drawer).not.toBeVisible();
  });

  test('8. 新建会话 — 清空消息列表', async ({ page }) => {
    // 打开历史抽屉
    await page.locator('button').filter({ has: page.locator('.anticon-history') }).click();

    // 点击新建会话
    await page.getByText('+ 新建会话').click();

    // 欢迎屏应显示
    await expect(page.getByText('SQL 企业级智能数据分析助手')).toBeVisible();
  });

  test('9. 左侧面板折叠/展开', async ({ page }) => {
    // 点击折叠按钮
    const collapseBtn = page.locator('button').filter({ has: page.locator('.anticon-menu-fold') });
    if (await collapseBtn.isVisible()) {
      await collapseBtn.click();
    }

    // 数据源面板应隐藏
    await expect(page.getByText('数据源')).not.toBeVisible();

    // 展开
    const expandBtn = page.locator('button').filter({ has: page.locator('.anticon-menu-unfold') });
    await expandBtn.click();

    // 数据源面板应重新显示
    await expect(page.getByText('数据源')).toBeVisible();
  });

  test('10. 空状态提示', async ({ page }) => {
    // 打开新的空会话（未发送过消息时应有欢迎提示）
    const textarea = page.locator('textarea');
    await expect(textarea).toBeVisible();

    // 例剧中应有预设提示文字
    await expect(page.getByText('查询最近7天的注册用户数')).toBeVisible();
  });
});
