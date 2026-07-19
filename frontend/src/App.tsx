/**
 * 应用主布局 — 左（数据源面板）+ 中（聊天面板）+ 右（History Drawer）。
 *
 * 使用 Ant Design Layout 实现三栏式结构：
 * - Sider: DataSourcePanel（表列表）
 * - Content: ChatPanel（消息 + 输入框）
 * - Drawer: HistoryDrawer（历史会话）
 */

import React, { useState } from 'react';
import { Layout, Button, Badge, Tooltip, Typography } from 'antd';
import {
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons';
import { ChatProvider, useChatContext } from './hooks/useChatReducer';
import DataSourcePanel from './components/DataSourcePanel';
import ChatPanel from './components/ChatPanel';
import HistoryDrawer from './components/HistoryDrawer';
import './App.css';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const AppLayout: React.FC = () => {
  const { state } = useChatContext();
  const [siderCollapsed, setSiderCollapsed] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <Layout style={{ height: '100vh' }}>
      {/* ===== 左侧数据源面板 ===== */}
      <Sider
        width={280}
        collapsedWidth={0}
        collapsed={siderCollapsed}
        theme="light"
        style={{
          borderRight: '1px solid #e8e8e8',
          overflow: 'hidden',
          transition: 'all 0.2s',
        }}
      >
        <DataSourcePanel />
      </Sider>

      {/* ===== 主区域 ===== */}
      <Layout>
        {/* 顶栏 */}
        <Header
          style={{
            background: '#fff',
            borderBottom: '1px solid #e8e8e8',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 16px',
            height: 56,
            lineHeight: '56px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button
              type="text"
              icon={siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setSiderCollapsed(!siderCollapsed)}
            />
            <Text strong style={{ fontSize: 16 }}>
              SQL 智能分析助手
            </Text>
          </div>

          <Tooltip title="历史记录">
            <Badge count={state.sessions.length} size="small">
              <Button
                type="text"
                icon={<HistoryOutlined style={{ fontSize: 18 }} />}
                onClick={() => setHistoryOpen(true)}
              />
            </Badge>
          </Tooltip>
        </Header>

        {/* 聊天面板 */}
        <Content style={{ overflow: 'hidden', position: 'relative' }}>
          <ChatPanel />
        </Content>
      </Layout>

      {/* ===== 右侧历史抽屉 ===== */}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
      />
    </Layout>
  );
};

const App: React.FC = () => {
  return (
    <ChatProvider>
      <AppLayout />
    </ChatProvider>
  );
};

export default App;
