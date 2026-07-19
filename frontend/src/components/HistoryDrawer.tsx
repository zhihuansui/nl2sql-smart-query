/**
 * 历史记录抽屉 — 从右侧滑出。
 *
 * 从 /sessions 接口拉取会话列表，点击可加载该会话的历史消息。
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  Drawer,
  List,
  Typography,
  Button,
  Skeleton,
  Empty,
  Popconfirm,
  message,
  Tag,
} from 'antd';
import {
  HistoryOutlined,
  DeleteOutlined,
  MessageOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  fetchSessions,
  fetchSessionDetail,
  deleteSession,
} from '../services/api';
import type { SessionSummary } from '../services/api';
import { useChatContext } from '../hooks/useChatReducer';
import type { Message } from '../hooks/useChatReducer';

const { Text } = Typography;

interface HistoryDrawerProps {
  open: boolean;
  onClose: () => void;
}

const HistoryDrawer: React.FC<HistoryDrawerProps> = ({ open, onClose }) => {
  const { state, dispatch } = useChatContext();
  const [loading, setLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchSessions(50);
      dispatch({ type: 'SET_SESSIONS', payload: res.sessions });
    } catch {
      message.error('无法加载历史记录');
    } finally {
      setLoading(false);
    }
  }, [dispatch]);

  useEffect(() => {
    if (open) loadSessions();
  }, [open, loadSessions]);

  // 点击会话 → 加载历史消息
  const handleSessionClick = async (session: SessionSummary) => {
    dispatch({ type: 'SET_CURRENT_SESSION', payload: session.id });
    dispatch({ type: 'SET_LOADING_HISTORY', payload: true });

    try {
      const detail = await fetchSessionDetail(session.id);
      dispatch({ type: 'SET_SESSION_DETAIL', payload: detail });

      // 将历史记录转成 Message[]
      const msgs: Message[] = [];
      // 按时间正序展示
      const history = [...detail.history].reverse();

      for (const h of history) {
        // 用户消息
        msgs.push({
          id: `hist-user-${h.id}`,
          role: 'user',
          content: h.question,
        });
        // 助手消息
        if (h.status === 'success') {
          msgs.push({
            id: `hist-ast-${h.id}`,
            role: 'assistant',
            content: h.explanation || '',
            sql: h.sql || undefined,
            explanation: h.explanation || undefined,
            columns: (h.result_columns as string[]) || undefined,
            rows: h.result_rows as unknown[][],
            total_count: h.total_count || undefined,
            execution_ms: h.execution_ms || undefined,
          });
        } else {
          msgs.push({
            id: `hist-ast-${h.id}`,
            role: 'assistant',
            content: h.error_message || '查询失败',
            error: h.error_message || '查询失败',
            error_type: h.status as 'failed' | 'blocked',
          });
        }
      }

      dispatch({ type: 'LOAD_HISTORY_MESSAGES', payload: msgs });
      onClose();
    } catch {
      message.error('加载会话详情失败');
      dispatch({ type: 'SET_LOADING_HISTORY', payload: false });
    }
  };

  // 删除会话
  const handleDelete = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      message.success('会话已删除');
      loadSessions();
    } catch {
      message.error('删除失败');
    }
  };

  // 新建会话
  const handleNewSession = () => {
    dispatch({ type: 'SET_CURRENT_SESSION', payload: null });
    dispatch({ type: 'SET_SESSION_DETAIL', payload: null });
    dispatch({ type: 'LOAD_HISTORY_MESSAGES', payload: [] });
    onClose();
  };

  return (
    <Drawer
      title={
        <span>
          <HistoryOutlined style={{ marginRight: 8 }} />
          历史记录
        </span>
      }
      placement="right"
      width={380}
      open={open}
      onClose={onClose}
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={loadSessions}>
          刷新
        </Button>
      }
    >
      <div style={{ marginBottom: 12 }}>
        <Button block type="dashed" onClick={handleNewSession}>
          + 新建会话
        </Button>
      </div>

      {loading ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : state.sessions.length === 0 ? (
        <Empty description="暂无历史记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          dataSource={state.sessions}
          renderItem={(session) => (
            <List.Item
              style={{
                cursor: 'pointer',
                padding: '10px 12px',
                borderRadius: 6,
                background:
                  state.currentSessionId === session.id
                    ? '#e6f4ff'
                    : 'transparent',
                transition: 'background 0.2s',
              }}
              onMouseEnter={(e) => {
                if (state.currentSessionId !== session.id) {
                  (e.currentTarget as HTMLElement).style.background = '#f5f5f5';
                }
              }}
              onMouseLeave={(e) => {
                if (state.currentSessionId !== session.id) {
                  (e.currentTarget as HTMLElement).style.background = 'transparent';
                }
              }}
              onClick={() => handleSessionClick(session)}
              actions={[
                <Popconfirm
                  title="确认删除此会话？"
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    handleDelete(session.id);
                  }}
                  onCancel={(e) => e?.stopPropagation()}
                  key="delete"
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                avatar={<MessageOutlined style={{ color: '#1677ff' }} />}
                title={
                  <Text style={{ fontSize: 13 }} ellipsis={{ tooltip: session.title }}>
                    {session.title}
                  </Text>
                }
                description={
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {session.created_at?.slice(0, 16).replace('T', ' ')}
                  </Text>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Drawer>
  );
};

export default HistoryDrawer;
