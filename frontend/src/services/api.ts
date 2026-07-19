/**
 * API 服务层 — 封装与后端的所有 HTTP 通信。
 *
 * 包含：
 * - axios 实例（自动 baseURL /api/v1）
 * - SSE 流式查询（fetch + ReadableStream）
 * - 会话 / 表元数据 / 黄金示例 CRUD
 */

import axios from 'axios';

// ============================================================
// Axios 实例
// ============================================================

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// ============================================================
// 类型定义
// ============================================================

/** SSE 事件类型（来自后端 Orchestrator） */
export interface SSEEvent {
  event: 'status' | 'result' | 'error';
  data: Record<string, unknown>;
}

/** 会话摘要 */
export interface SessionSummary {
  id: string;
  title: string;
  user_id: string;
  created_at: string;
  updated_at: string;
}

/** 会话详情（含历史） */
export interface SessionDetail extends SessionSummary {
  history_count: number;
  history: QueryHistoryItem[];
}

/** 单条查询历史 */
export interface QueryHistoryItem {
  id: string;
  question: string;
  sql: string | null;
  executed_sql: string | null;
  explanation: string | null;
  status: string;
  error_message: string | null;
  execution_ms: number | null;
  retry_count: number;
  result_columns: unknown[] | null;
  result_rows: unknown[][] | null;
  total_count: number | null;
  created_at: string;
}

/** 表概览 */
export interface TableSummary {
  name: string;
  comment: string;
  row_count_approx: number;
  column_count: number;
}

/** 列定义 */
export interface ColumnDef {
  name: string;
  type: string;
  nullable: boolean;
  comment: string;
  is_pk: boolean;
}

/** 黄金示例 */
export interface ExampleItem {
  id: string;
  question: string;
  sql: string;
  tables_used: string[];
  tags: string[];
  reviewed_by: string | null;
  usage_count: number;
  created_at: string | null;
}

/** 健康检查结果 */
export interface HealthStatus {
  status: string;
  version: string;
  app_env: string;
  components: Record<string, unknown>;
}

// ============================================================
// SSE 流式查询
// ============================================================

export interface StreamHandle {
  cancel: () => void;
  done: Promise<void>;
}

/**
 * 通过 POST /api/v1/query 发起流式查询。
 *
 * 使用 fetch + ReadableStream 而非 EventSource，因为后端
 * 接口是 POST 方法（需要传递 question 等参数）。
 *
 * @param question  用户自然语言问题
 * @param sessionId 当前会话 ID（空则自动创建新会话）
 * @param userId    用户 ID（空则 RLS 不生效）
 * @param onEvent   每收到一个 SSE 事件时回调
 * @param onError   流错误回调
 * @returns         { cancel, done } — cancel 中止请求, done 在流完成时 resolve
 */
export function streamQuery(
  question: string,
  sessionId: string | null,
  userId: string | null,
  onEvent: (event: SSEEvent) => void,
  onError: (error: string) => void,
): StreamHandle {
  const controller = new AbortController();
  let resolveDone: () => void;
  const done = new Promise<void>((resolve) => { resolveDone = resolve; });

  (async () => {
    try {
      const response = await fetch('/api/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          session_id: sessionId || null,
          user_id: userId || null,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        onError(`请求失败 (${response.status})`);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onError('响应体不可读');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;

        buffer += decoder.decode(value, { stream: true });

        // 解析 SSE 协议：event: xxx\ndata: {...}\n\n
        const blocks = buffer.split('\n\n');
        // 最后一个可能不完整，保留
        buffer = blocks.pop() || '';

        for (const block of blocks) {
          if (!block.trim()) continue;
          const event = parseSSEBlock(block);
          if (event) onEvent(event);
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      resolveDone!();
    }
  })();

  return { cancel: () => controller.abort(), done };
}

/** 解析单个 SSE 块（event + data 行） */
function parseSSEBlock(block: string): SSEEvent | null {
  const lines = block.split('\n');
  let event = 'status';
  let dataStr = '';

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      event = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataStr = line.slice(6).trim();
    }
  }

  if (!dataStr) return null;

  try {
    const data = JSON.parse(dataStr) as Record<string, unknown>;
    return { event: event as SSEEvent['event'], data };
  } catch {
    return null;
  }
}

// ============================================================
// 会话管理
// ============================================================

export async function fetchSessions(
  limit = 50,
  offset = 0,
): Promise<{ total: number; sessions: SessionSummary[] }> {
  const res = await http.get('/sessions', { params: { limit, offset } });
  return res.data;
}

export async function fetchSessionDetail(
  sessionId: string,
): Promise<SessionDetail> {
  const res = await http.get(`/sessions/${sessionId}`);
  return res.data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await http.delete(`/sessions/${sessionId}`);
}

// ============================================================
// 表元数据
// ============================================================

export async function fetchTables(): Promise<{
  total: number;
  tables: TableSummary[];
}> {
  const res = await http.get('/tables');
  return res.data;
}

export async function fetchTableColumns(
  tableName: string,
): Promise<{ table_name: string; column_count: number; columns: ColumnDef[] }> {
  const res = await http.get(`/tables/${encodeURIComponent(tableName)}`);
  return res.data;
}

// ============================================================
// 黄金示例
// ============================================================

export async function fetchExamples(
  limit = 50,
  offset = 0,
  tag?: string,
): Promise<{ total: number; examples: ExampleItem[] }> {
  const params: Record<string, string | number> = { limit, offset };
  if (tag) params.tag = tag;
  const res = await http.get('/examples', { params });
  return res.data;
}

// ============================================================
// 健康检查
// ============================================================

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await http.get('/health');
  return res.data;
}

export default http;
