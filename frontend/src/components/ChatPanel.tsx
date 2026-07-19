/**
 * 聊天主面板 — 消息列表 + 输入框。
 */

import React, { useEffect, useRef } from 'react';
import { Typography, Empty, Button, Spin } from 'antd';
import { MessageOutlined } from '@ant-design/icons';
import { useChatContext } from '../hooks/useChatReducer';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';

const { Title, Text } = Typography;

const WelcomeScreen: React.FC = () => (
  <div
    style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      color: '#999',
    }}
  >
    <MessageOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
    <Title level={4} type="secondary" style={{ margin: 0 }}>
      SQL 企业级智能数据分析助手
    </Title>
    <Text type="secondary" style={{ marginTop: 8, textAlign: 'center', maxWidth: 400 }}>
      输入自然语言查询您的业务数据库，AI 将自动生成 SQL 并返回结果。
    </Text>
    <div
      style={{
        marginTop: 24,
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap',
        justifyContent: 'center',
      }}
    >
      {['查询最近7天的注册用户数', '按月份统计销售额趋势', '显示订单金额TOP10的用户'].map(
        (hint) => (
          <Text
            key={hint}
            type="secondary"
            style={{
              padding: '4px 12px',
              background: '#f5f5f5',
              borderRadius: 16,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            {hint}
          </Text>
        ),
      )}
    </div>
  </div>
);

const ChatPanel: React.FC = () => {
  const { state } = useChatContext();
  const bottomRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [state.messages, state.streaming]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#fafafa',
      }}
    >
      {/* 消息列表 */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '24px 16px 16px',
        }}
      >
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          {state.loadingHistory ? (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Spin tip="加载历史记录..." />
            </div>
          ) : state.messages.length === 0 ? (
            <WelcomeScreen />
          ) : (
            state.messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))
          )}

          {/* 底部锚点 */}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* 输入框 */}
      <ChatInput />
    </div>
  );
};

export default ChatPanel;
