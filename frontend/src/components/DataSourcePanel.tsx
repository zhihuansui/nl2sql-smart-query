/**
 * 左侧数据源面板 — 展示目标数据库的表列表。
 *
 * 从 /tables 接口拉取数据，点击表名弹出 Modal 显示字段详情。
 */

import React, { useEffect, useState } from 'react';
import {
  Skeleton,
  Typography,
  List,
  Modal,
  Table,
  Tag,
  Empty,
  Input,
  Alert,
  Button,
  Tabs,
} from 'antd';
import {
  DatabaseOutlined,
  TableOutlined,
  SearchOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { fetchTables, fetchTableColumns, fetchTableRows } from '../services/api';
import type { TableSummary, ColumnDef, TableRowsResult } from '../services/api';
import { useChatContext } from '../hooks/useChatReducer';

const { Title, Text } = Typography;

const DataSourcePanel: React.FC = () => {
  const { state, dispatch } = useChatContext();
  const [search, setSearch] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);

  // 选中的表（用于弹窗）
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [columns, setColumns] = useState<ColumnDef[]>([]);
  const [columnsLoading, setColumnsLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  // 拉取表列表
  useEffect(() => {
    setLoadError(null);
    dispatch({ type: 'SET_TABLES_LOADING', payload: true });
    fetchTables()
      .then((res) => {
        dispatch({ type: 'SET_TABLES', payload: res.tables });
      })
      .catch((err) => {
        dispatch({ type: 'SET_TABLES', payload: [] });
        setLoadError(err instanceof Error ? err.message : '加载失败');
      })
      .finally(() => {
        dispatch({ type: 'SET_TABLES_LOADING', payload: false });
      });
  }, [dispatch]);

  // 过滤
  const filtered = state.tables.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()),
  );

  // 数据预览
  const [rowsData, setRowsData] = useState<TableRowsResult | null>(null);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('columns');

  // 点击表名 → 弹窗展示字段 + 数据预览
  const handleTableClick = async (table: TableSummary) => {
    setSelectedTable(table.name);
    setModalOpen(true);
    setActiveTab('columns');
    setRowsData(null);

    // 并行加载字段和数据
    setColumnsLoading(true);
    setRowsLoading(true);
    try {
      const detail = await fetchTableColumns(table.name);
      setColumns(detail.columns);
    } catch {
      setColumns([]);
    } finally {
      setColumnsLoading(false);
    }

    try {
      const data = await fetchTableRows(table.name, 100, 0);
      setRowsData(data);
    } catch {
      setRowsData(null);
    } finally {
      setRowsLoading(false);
    }
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 标题 */}
      <div style={{ padding: '16px 16px 8px' }}>
        <Title level={5} style={{ margin: 0 }}>
          <DatabaseOutlined /> 数据源
        </Title>
      </div>

      {/* 搜索框 */}
      <div style={{ padding: '8px 16px' }}>
        <Input
          size="small"
          placeholder="搜索表名..."
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
        />
      </div>

      {/* 表列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}>
        {state.tablesLoading ? (
          <Skeleton active paragraph={{ rows: 6 }} style={{ padding: 16 }} />
        ) : loadError ? (
          <div style={{ padding: 16 }}>
            <Alert
              type="error"
              message="加载表数据失败"
              description={loadError}
              showIcon
              style={{ marginBottom: 12, fontSize: 12 }}
            />
            <Button
              block
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => {
                setLoadError(null);
                dispatch({ type: 'SET_TABLES_LOADING', payload: true });
                fetchTables()
                  .then((res) => dispatch({ type: 'SET_TABLES', payload: res.tables }))
                  .catch((err) => setLoadError(err instanceof Error ? err.message : '加载失败'))
                  .finally(() => dispatch({ type: 'SET_TABLES_LOADING', payload: false }));
              }}
            >
              重试
            </Button>
          </div>
        ) : filtered.length === 0 ? (
          <Empty description="无表数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            dataSource={filtered}
            renderItem={(table) => (
              <List.Item
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  borderRadius: 6,
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.background = '#f5f5f5';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.background = 'transparent';
                }}
                onClick={() => handleTableClick(table)}
              >
                <List.Item.Meta
                  avatar={<TableOutlined style={{ color: '#1677ff' }} />}
                  title={
                    <Text style={{ fontSize: 13 }}>{table.name}</Text>
                  }
                  description={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {table.column_count} 字段
                      {table.row_count_approx > 0
                        ? ` · ${(table.row_count_approx / 10000).toFixed(1)}w 行`
                        : ''}
                    </Text>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </div>

      {/* 表详情弹窗（字段 + 数据预览） */}
      <Modal
        title={
          <span>
            <TableOutlined style={{ marginRight: 8 }} />
            {selectedTable}
          </span>
        }
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={800}
      >
        <Tabs activeKey={activeTab} onChange={setActiveTab}>
          {/* === 字段 Tab === */}
          <Tabs.TabPane tab="字段" key="columns">
            {columnsLoading ? (
              <Skeleton active paragraph={{ rows: 8 }} />
            ) : (
              <Table
                dataSource={columns}
                rowKey="name"
                size="small"
                pagination={false}
                columns={[
                  {
                    title: '字段名',
                    dataIndex: 'name',
                    key: 'name',
                    width: 160,
                    render: (name: string, record: ColumnDef) => (
                      <span>
                        {record.is_pk ? (
                          <Tag color="gold" style={{ marginRight: 4 }}>
                            PK
                          </Tag>
                        ) : null}
                        <Text code>{name}</Text>
                      </span>
                    ),
                  },
                  {
                    title: '类型',
                    dataIndex: 'type',
                    key: 'type',
                    width: 130,
                  },
                  {
                    title: '可空',
                    dataIndex: 'nullable',
                    key: 'nullable',
                    width: 60,
                    render: (v: boolean) =>
                      v ? <Tag color="default">YES</Tag> : <Tag color="red">NO</Tag>,
                  },
                  {
                    title: '注释',
                    dataIndex: 'comment',
                    key: 'comment',
                    ellipsis: true,
                  },
                ]}
              />
            )}
          </Tabs.TabPane>

          {/* === 数据 Tab === */}
          <Tabs.TabPane tab="数据" key="data">
            {rowsLoading ? (
              <Skeleton active paragraph={{ rows: 8 }} />
            ) : rowsData ? (
              <Table
                dataSource={rowsData.rows.map((row, i) => {
                  const obj: Record<string, unknown> = { __key: i };
                  rowsData.columns.forEach((col, j) => {
                    obj[col] = row[j];
                  });
                  return obj;
                })}
                rowKey="__key"
                size="small"
                scroll={{ x: 'max-content' }}
                pagination={{
                  pageSize: 50,
                  showSizeChanger: false,
                  total: rowsData.total_count,
                  showTotal: (total) => `共 ${total} 行`,
                }}
                columns={rowsData.columns.map((col) => ({
                  title: col,
                  dataIndex: col,
                  key: col,
                  width: 130,
                  ellipsis: true,
                  render: (v: unknown) =>
                    v === null ? (
                      <Text type="secondary" italic>(null)</Text>
                    ) : (
                      String(v)
                    ),
                }))}
              />
            ) : (
              <Empty description="加载数据失败" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Tabs.TabPane>
        </Tabs>
      </Modal>
    </div>
  );
};

export default DataSourcePanel;
