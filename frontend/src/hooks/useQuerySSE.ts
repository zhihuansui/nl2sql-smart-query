/**
 * SSE 查询 Hook — 封装流式查询的发送与事件处理逻辑。
 *
 * 将后端 Orchestrator 的 SSE 事件流转为 Message 更新。
 */

import { useCallback, useRef } from 'react';
import { v4 as uuidv4 } from '../services/id';
import { streamQuery } from '../services/api';
import type { StreamHandle } from '../services/api';
import { useChatContext, type Message } from './useChatReducer';

/**
 * useQuerySSE — 提供 sendMessage 函数给 ChatInput 使用。
 *
 * 每次 sendMessage：
 * 1. 追加用户消息到列表
 * 2. 追加一条空的 assistant 消息（逐步更新）
 * 3. 调用 streamQuery 消费 SSE 事件
 * 4. 根据 event 类型更新最后一条消息
 */
export function useQuerySSE() {
  const { state, dispatch } = useChatContext();
  const cancelRef = useRef<StreamHandle | null>(null);

  const sendMessage = useCallback(
    async (question: string) => {
      // 取消上一次尚未完成的请求
      cancelRef.current?.cancel();

      // 1. 用户消息
      const userMsg: Message = {
        id: uuidv4(),
        role: 'user',
        content: question,
      };
      dispatch({ type: 'ADD_MESSAGE', payload: userMsg });

      // 2. 占位 assistant 消息
      const assistantId = uuidv4();
      const assistantMsg: Message = {
        id: assistantId,
        role: 'assistant',
        content: '',
        status: 'thinking',
      };
      dispatch({ type: 'ADD_MESSAGE', payload: assistantMsg });
      dispatch({ type: 'SET_STREAMING', payload: true });

      // 3. 发起 SSE 流式请求
      cancelRef.current = streamQuery(
        question,
        state.currentSessionId,
        state.userId,
        (sseEvent) => {
          // 更新最后一条 assistant 消息
          const upd: Partial<Message> = {};

          switch (sseEvent.event) {
            case 'status': {
              const st = sseEvent.data.state as string;
              if (['thinking', 'schema_linking', 'executing', 'retrying'].includes(st)) {
                upd.status = st as Message['status'];
              }
              upd.content = (sseEvent.data.message as string) || '';
              break;
            }

            case 'result': {
              const d = sseEvent.data as Record<string, unknown>;
              upd.status = undefined;
              upd.sql = d.sql as string;
              upd.explanation = d.explanation as string;
              upd.columns = d.columns as string[];
              upd.rows = d.rows as unknown[][];
              upd.total_count = d.total_count as number;
              upd.execution_ms = d.execution_ms as number;
              upd.content = (d.explanation as string) || '';

              // 保存 sessionId
              if (d.session_id && typeof d.session_id === 'string') {
                dispatch({ type: 'SET_CURRENT_SESSION', payload: d.session_id });
              }
              break;
            }

            case 'error': {
              const d = sseEvent.data as Record<string, string>;
              upd.status = undefined;
              upd.content = d.message || '查询失败';
              upd.error = d.message || '查询失败';
              upd.error_type = (d.status as Message['error_type']) || 'failed';
              break;
            }
          }

          dispatch({ type: 'UPDATE_LAST_MESSAGE', payload: upd });
        },
        (errorMsg) => {
          dispatch({
            type: 'UPDATE_LAST_MESSAGE',
            payload: {
              status: undefined,
              content: errorMsg,
              error: errorMsg,
              error_type: 'failed',
            },
          });
          dispatch({ type: 'SET_STREAMING', payload: false });
        },
      );

      // 4. 流结束后重置 streaming 状态
      cancelRef.current!.done.then(() => {
        dispatch({ type: 'SET_STREAMING', payload: false });
      });
    },
    [state.currentSessionId, state.userId, dispatch],
  );

  /** 取消当前正在进行的查询 */
  const cancelQuery = useCallback(() => {
    cancelRef.current?.cancel();
    dispatch({ type: 'SET_STREAMING', payload: false });
  }, [dispatch]);

  return { sendMessage, cancelQuery };
}
