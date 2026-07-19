/**
 * 查询结果表格组件。
 *
 * 使用 Ant Design Table 动态渲染后端返回的 columns + rows，
 * 支持横向滚动、分页、复制单元格。
 */

import React, { useMemo } from 'react';
import { Table, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';

const { Text } = Typography;

interface ResultTableProps {
  columns: string[];
  rows: unknown[][];
  totalCount: number;
  executionMs: number;
}

const ResultTable: React.FC<ResultTableProps> = ({
  columns,
  rows,
  totalCount,
  executionMs,
}) => {
  // 动态生成 Ant Design 列定义
  const antColumns: ColumnsType<Record<string, unknown>> = useMemo(() => {
    return columns.map((col, idx) => ({
      title: col,
      dataIndex: `_col_${idx}`,
      key: `_col_${idx}`,
      ellipsis: true,
      width: 150,
      render: (val: unknown) => (
        <Text
          style={{ fontSize: 13 }}
          copyable={{ text: val != null ? String(val) : '' }}
        >
          {val != null ? String(val) : <Text type="secondary">NULL</Text>}
        </Text>
      ),
    }));
  }, [columns]);

  // 将 rows 转为 { _col_0: ..., _col_1: ..., key: ... } 格式
  const dataSource = useMemo(() => {
    return rows.map((row, rowIdx) => {
      const record: Record<string, unknown> = { key: String(rowIdx) };
      row.forEach((val, colIdx) => {
        record[`_col_${colIdx}`] = val;
      });
      return record;
    });
  }, [rows]);

  if (!columns.length) {
    return (
      <div style={{ padding: 16, textAlign: 'center' }}>
        <Text type="secondary">查询未返回列数据</Text>
      </div>
    );
  }

  return (
    <div>
      <Table
        columns={antColumns}
        dataSource={dataSource}
        size="small"
        scroll={{ x: 'max-content', y: 400 }}
        pagination={
          totalCount > 10
            ? { pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }
            : false
        }
        bordered
        style={{ fontSize: 13 }}
      />
      <div style={{ padding: '6px 0', textAlign: 'right' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {totalCount} 行 · 耗时 {executionMs} ms
          {rows.length < totalCount ? ` · 仅展示前 ${rows.length} 行` : ''}
        </Text>
      </div>
    </div>
  );
};

export default ResultTable;
