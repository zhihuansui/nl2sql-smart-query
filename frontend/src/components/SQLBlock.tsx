/**
 * SQL 代码块展示组件。
 *
 * 使用 Ant Design Collapse 面板展示 SQL，支持一键复制。
 * 语法高亮通过简单的关键词着色实现（避免引入 prism/highlight.js）。
 */

import React from 'react';
import { Typography, Button, Space, message } from 'antd';
import { CopyOutlined, CodeOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface SQLBlockProps {
  sql: string;
  defaultOpen?: boolean;
}

/** SQL 关键词着色映射 */
const KEYWORD_COLORS: Record<string, string> = {
  SELECT: '#1677ff',
  FROM: '#1677ff',
  WHERE: '#1677ff',
  AND: '#1677ff',
  OR: '#1677ff',
  NOT: '#1677ff',
  IN: '#1677ff',
  LIKE: '#1677ff',
  BETWEEN: '#1677ff',
  IS: '#1677ff',
  NULL: '#1677ff',
  GROUP: '#1677ff',
  BY: '#1677ff',
  ORDER: '#1677ff',
  HAVING: '#1677ff',
  LIMIT: '#1677ff',
  OFFSET: '#1677ff',
  JOIN: '#1677ff',
  LEFT: '#1677ff',
  RIGHT: '#1677ff',
  INNER: '#1677ff',
  OUTER: '#1677ff',
  ON: '#1677ff',
  AS: '#1677ff',
  DISTINCT: '#1677ff',
  COUNT: '#722ed1',
  SUM: '#722ed1',
  AVG: '#722ed1',
  MAX: '#722ed1',
  MIN: '#722ed1',
  COALESCE: '#722ed1',
  CASE: '#722ed1',
  WHEN: '#722ed1',
  THEN: '#722ed1',
  ELSE: '#722ed1',
  END: '#722ed1',
  CAST: '#722ed1',
  ASC: '#13c2c2',
  DESC: '#13c2c2',
};

function highlightSQL(sql: string): React.ReactNode {
  // 按单词分割，对关键词着色
  const tokens = sql.split(/(\b\w+\b|[^a-zA-Z0-9_])/g);
  return tokens.map((token, i) => {
    const upper = token.toUpperCase();
    const color = KEYWORD_COLORS[upper];
    if (color) {
      return (
        <span key={i} style={{ color, fontWeight: 600 }}>
          {upper}
        </span>
      );
    }
    // 数字着色
    if (/^\d+$/.test(token)) {
      return (
        <span key={i} style={{ color: '#cf1322' }}>
          {token}
        </span>
      );
    }
    // 字符串字面量
    if (token.startsWith("'") || token.startsWith('"')) {
      return (
        <span key={i} style={{ color: '#389e0d' }}>
          {token}
        </span>
      );
    }
    return token;
  });
}

const SQLBlock: React.FC<SQLBlockProps> = ({ sql, defaultOpen = true }) => {
  const handleCopy = () => {
    navigator.clipboard.writeText(sql).then(() => {
      message.success('SQL 已复制');
    });
  };

  return (
    <div
      style={{
        background: '#f6f8fa',
        borderRadius: 8,
        border: '1px solid #e8e8e8',
        overflow: 'hidden',
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '6px 12px',
          background: '#eef1f5',
          borderBottom: '1px solid #e8e8e8',
        }}
      >
        <Space size={4}>
          <CodeOutlined style={{ color: '#1677ff' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            SQL
          </Text>
        </Space>
        <Button
          type="text"
          size="small"
          icon={<CopyOutlined />}
          onClick={handleCopy}
        >
          复制
        </Button>
      </div>

      {/* 代码内容 */}
      <pre
        style={{
          margin: 0,
          padding: '10px 14px',
          fontSize: 13,
          lineHeight: 1.6,
          fontFamily:
            "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        <code>{highlightSQL(sql)}</code>
      </pre>
    </div>
  );
};

export default SQLBlock;
