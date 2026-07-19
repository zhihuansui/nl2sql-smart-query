/**
 * 消息气泡组件。
 *
 * 根据消息类型渲染不同内容：
 * - user: 普通用户问题卡片
 * - assistant: 含状态指示 / SQL 代码 / 解释 / 结果表格
 */

import React from 'react';
import { Typography, Spin, Tag, Alert, Space, Empty } from 'antd';
import {
  UserOutlined,
  RobotOutlined,
  LoadingOutlined,
  SearchOutlined,
  LinkOutlined,
  ThunderboltOutlined,
  SyncOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import type { Message } from '../hooks/useChatReducer';
import SQLBlock from './SQLBlock';
import ResultTable from './ResultTable';

const { Text, Paragraph } = Typography;

interface MessageBubbleProps {
  message: Message;
}

/** 状态映射：label + 颜色 + 图标 */
const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: React.ReactNode }
> = {
  thinking: {
    label: '正在理解语义...',
    color: '#1677ff',
    icon: <LoadingOutlined />,
  },
  schema_linking: {
    label: '正在检索表结构...',
    color: '#1677ff',
    icon: <SearchOutlined />,
  },
  executing: {
    label: '正在执行查询...',
    color: '#1677ff',
    icon: <ThunderboltOutlined />,
  },
  retrying: {
    label: '正在重新尝试...',
    color: '#fa8c16',
    icon: <SyncOutlined />,
  },
};

const MessageBubble: React.FC<MessageBubbleProps> = ({ message }) => {
  const isUser = message.role === 'user';

  // ========== 用户消息 ==========
  if (isUser) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          marginBottom: 16,
        }}
      >
        <div style={{ maxWidth: '70%' }}>
          <div
            style={{
              background: '#1677ff',
              color: '#fff',
              padding: '10px 16px',
              borderRadius: 16,
              borderBottomRightRadius: 4,
              fontSize: 14,
              lineHeight: 1.6,
              whiteSpace: 'pre-wrap',
            }}
          >
            {message.content}
          </div>
        </div>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            background: '#1677ff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginLeft: 10,
            flexShrink: 0,
          }}
        >
          <UserOutlined style={{ color: '#fff', fontSize: 16 }} />
        </div>
      </div>
    );
  }

  // ========== Assistant 消息 ==========
  return (
    <div style={{ display: 'flex', marginBottom: 16 }}>
      {/* 头像 */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: '#f0f0f0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginRight: 10,
          flexShrink: 0,
        }}
      >
        <RobotOutlined style={{ color: '#666', fontSize: 16 }} />
      </div>

      <div style={{ maxWidth: '80%' }}>
        {/* ===== 中间状态指示 ===== */}
        {message.status && STATUS_CONFIG[message.status] && (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 16px',
              background: '#f6f8fa',
              borderRadius: 8,
              border: '1px solid #e8e8e8',
            }}
          >
            <Spin indicator={<LoadingOutlined style={{ fontSize: 18 }} spin />} />
            <Text style={{ color: STATUS_CONFIG[message.status].color }}>
              {STATUS_CONFIG[message.status].label}
            </Text>
          </div>
        )}

        {/* ===== 错误消息 ===== */}
        {message.error && (
          <Alert
            type={message.error_type === 'blocked' ? 'warning' : 'error'}
            showIcon
            icon={
              message.error_type === 'blocked' ? (
                <WarningOutlined />
              ) : (
                <CloseCircleOutlined />
              )
            }
            message={
              message.error_type === 'blocked'
                ? '查询被安全拦截'
                : '查询失败'
            }
            description={message.content}
            style={{ borderRadius: 8, marginBottom: 8 }}
          />
        )}

        {/* ===== SQL ===== */}
        {message.sql && (
          <div style={{ marginBottom: 12 }}>
            <SQLBlock sql={message.sql} />
          </div>
        )}

        {/* ===== 白话解释 ===== */}
        {message.explanation && !message.error && (
          <div
            style={{
              padding: '12px 16px',
              background: '#f6ffed',
              borderRadius: 8,
              border: '1px solid #d9f7be',
              marginBottom: 12,
            }}
          >
            <Space style={{ marginBottom: 4 }}>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              <Text strong style={{ fontSize: 13 }}>
                查询说明
              </Text>
            </Space>
            <Paragraph
              style={{ margin: '4px 0 0', fontSize: 14, color: '#333' }}
            >
              {message.explanation}
            </Paragraph>
          </div>
        )}

        {/* ===== 结果表格 ===== */}
        {message.columns && message.columns.length > 0 && (
          <div
            style={{
              background: '#fff',
              borderRadius: 8,
              border: '1px solid #e8e8e8',
              padding: 8,
            }}
          >
            <ResultTable
              columns={message.columns}
              rows={message.rows || []}
              totalCount={message.total_count || 0}
              executionMs={message.execution_ms || 0}
            />
          </div>
        )}

        {/* ===== 成功但无数据 ===== */}
        {message.sql && !message.error && !message.columns && (
          <div
            style={{
              padding: 16,
              background: '#fafafa',
              borderRadius: 8,
              border: '1px solid #e8e8e8',
            }}
          >
            <Empty
              description="查询完成，未返回数据"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble;
