/**
 * 底部输入框组件。
 *
 * 支持发送查询、Enter 快捷键、loading 态禁用、取消查询。
 */

import React, { useState, useRef, useCallback } from 'react';
import { Input, Button, Space, Typography } from 'antd';
import {
  SendOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useChatContext } from '../hooks/useChatReducer';
import { useQuerySSE } from '../hooks/useQuerySSE';

const { TextArea } = Input;
const { Text } = Typography;

const ChatInput: React.FC = () => {
  const [value, setValue] = useState('');
  const { state } = useChatContext();
  const { sendMessage, cancelQuery } = useQuerySSE();
  const textareaRef = useRef<typeof TextArea>(null);

  const handleSend = useCallback(async () => {
    const q = value.trim();
    if (!q || state.streaming) return;
    setValue('');
    await sendMessage(q);
  }, [value, state.streaming, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Enter 发送（Shift+Enter 换行）
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      style={{
        borderTop: '1px solid #e8e8e8',
        background: '#fff',
        padding: '12px 16px 16px',
      }}
    >
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'flex-end',
          maxWidth: 900,
          margin: '0 auto',
        }}
      >
        <div style={{ flex: 1, position: 'relative' }}>
          <TextArea
            ref={textareaRef as never}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入数据查询需求，例如：查询过去7天注册的用户数"
            autoSize={{ minRows: 1, maxRows: 6 }}
            disabled={state.streaming}
            style={{ borderRadius: 8, fontSize: 14 }}
          />
        </div>

        <Space>
          {state.streaming ? (
            <Button
              danger
              icon={<StopOutlined />}
              onClick={cancelQuery}
              style={{ borderRadius: 8 }}
            >
              停止
            </Button>
          ) : (
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              disabled={!value.trim()}
              style={{ borderRadius: 8, height: 40 }}
            >
              查询
            </Button>
          )}
        </Space>
      </div>

      <div
        style={{
          maxWidth: 900,
          margin: '4px auto 0',
          textAlign: 'right',
        }}
      >
        <Text type="secondary" style={{ fontSize: 12 }}>
          <ThunderboltOutlined /> Enter 发送 · Shift+Enter 换行
        </Text>
      </div>
    </div>
  );
};

export default ChatInput;
