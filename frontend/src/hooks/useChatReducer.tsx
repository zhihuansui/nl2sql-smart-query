/**
 * 聊天状态管理 — Context + useReducer。
 *
 * 按 SPEC 5.2 节设计，管理会话列表、当前会话、消息流、加载态。
 */

import React, { createContext, useContext, useReducer } from 'react';
import type { SessionSummary, SessionDetail, TableSummary } from '../services/api';

// ============================================================
// 类型定义
// ============================================================

/** 单条消息 */
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;

  // Agent 中间状态
  status?: 'thinking' | 'schema_linking' | 'executing' | 'retrying';

  // 最终结果
  sql?: string;
  explanation?: string;
  columns?: string[];
  rows?: unknown[][];
  total_count?: number;
  execution_ms?: number;

  // 错误
  error?: string;
  error_type?: 'failed' | 'blocked' | 'rejected';
}

/** 全局聊天状态 */
export interface ChatState {
  /** 用户 ID（用于 RLS 行级权限） */
  userId: string | null;
  /** 会话列表 */
  sessions: SessionSummary[];
  /** 当前会话 ID */
  currentSessionId: string | null;
  /** 当前会话的详细数据（含历史） */
  currentSessionDetail: SessionDetail | null;
  /** 消息列表 */
  messages: Message[];
  /** 是否正在加载历史 */
  loadingHistory: boolean;
  /** 是否正在流式查询 */
  streaming: boolean;
  /** 全局错误 */
  error: string | null;
  /** 左侧数据源面板的表列表 */
  tables: TableSummary[];
  /** 数据源面板 loading */
  tablesLoading: boolean;
}

/** Action 联合类型 */
type Action =
  | { type: 'SET_USER_ID'; payload: string | null }
  | { type: 'SET_SESSIONS'; payload: SessionSummary[] }
  | { type: 'SET_CURRENT_SESSION'; payload: string | null }
  | { type: 'SET_SESSION_DETAIL'; payload: SessionDetail | null }
  | { type: 'LOAD_HISTORY_MESSAGES'; payload: Message[] }
  | { type: 'SET_LOADING_HISTORY'; payload: boolean }
  | { type: 'ADD_MESSAGE'; payload: Message }
  | { type: 'UPDATE_LAST_MESSAGE'; payload: Partial<Message> }
  | { type: 'SET_STREAMING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_TABLES'; payload: TableSummary[] }
  | { type: 'SET_TABLES_LOADING'; payload: boolean }
  | { type: 'RESET' };

// ============================================================
// Reducer
// ============================================================

const initialState: ChatState = {
  userId: null,
  sessions: [],
  currentSessionId: null,
  currentSessionDetail: null,
  messages: [],
  loadingHistory: false,
  streaming: false,
  error: null,
  tables: [],
  tablesLoading: false,
};

function chatReducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'SET_USER_ID':
      return { ...state, userId: action.payload };

    case 'SET_SESSIONS':
      return { ...state, sessions: action.payload };

    case 'SET_CURRENT_SESSION':
      return { ...state, currentSessionId: action.payload };

    case 'SET_SESSION_DETAIL':
      return { ...state, currentSessionDetail: action.payload };

    case 'LOAD_HISTORY_MESSAGES': {
      // 过滤出 user / assistant 消息用于展示
      return { ...state, messages: action.payload, loadingHistory: false };
    }

    case 'SET_LOADING_HISTORY':
      return { ...state, loadingHistory: action.payload };

    case 'ADD_MESSAGE':
      return {
        ...state,
        messages: [...state.messages, action.payload],
      };

    case 'UPDATE_LAST_MESSAGE': {
      const msgs = [...state.messages];
      if (msgs.length === 0) return state;
      const last = { ...msgs[msgs.length - 1], ...action.payload };
      msgs[msgs.length - 1] = last;
      return { ...state, messages: msgs };
    }

    case 'SET_STREAMING':
      return { ...state, streaming: action.payload };

    case 'SET_ERROR':
      return { ...state, error: action.payload, streaming: false };

    case 'SET_TABLES':
      return { ...state, tables: action.payload };

    case 'SET_TABLES_LOADING':
      return { ...state, tablesLoading: action.payload };

    case 'RESET':
      return initialState;

    default:
      return state;
  }
}

// ============================================================
// Context
// ============================================================

interface ChatContextType {
  state: ChatState;
  dispatch: React.Dispatch<Action>;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, initialState);
  return (
    <ChatContext.Provider value={{ state, dispatch }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext(): ChatContextType {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error('useChatContext 必须在 ChatProvider 内使用');
  }
  return ctx;
}
