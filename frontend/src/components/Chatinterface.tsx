"use client";

import { useState, useEffect, useRef, useCallback } from 'react';
import { Send, Loader2, Bot, User, ChevronDown, ChevronUp } from 'lucide-react';

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  plan?: PlanStep[];
  tool_calls?: ToolCall[];
  status?: 'pending' | 'running' | 'completed' | 'failed';
}

interface PlanStep {
  step_id: number;
  description: string;
  tool_name: string;
  tool_args: Record<string, any>;
  status?: string;
  output?: string;
}

interface ToolCall {
  name: string;
  args: Record<string, any>;
  result?: any;
  status?: string;
}

interface ChatInterfaceProps {
  userId?: string;
  tenantId?: string;
  initialMessage?: string;
  token?: string; // JWT token from auth
}

export default function ChatInterface({ userId = "dashboard", tenantId = "default", initialMessage = "", token }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState(initialMessage);
  const [isLoading, setIsLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [expandedPlans, setExpandedPlans] = useState<Set<string>>(new Set());
  
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const clientId = useRef(Math.random().toString(36).substring(7)).current;

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // WebSocket connection with authentication
  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/ws/${clientId}`;
    // If token provided, pass as query param or in header (browser WebSocket doesn't support headers, so use query)
    const url = token ? `${wsUrl}?token=${token}` : wsUrl;
    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log("WebSocket connected");
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'auth_error') {
        // Handle authentication error
        alert('Authentication failed. Please log in again.');
        return;
      }
      handleWebSocketMessage(data);
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected");
      setIsConnected(false);
      setTimeout(() => {
        const newWs = new WebSocket(url);
        wsRef.current = newWs;
      }, 3000);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setIsConnected(false);
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, [clientId, token]);

  const handleWebSocketMessage = (data: any) => {
    const timestamp = new Date(data.timestamp || Date.now());

    switch (data.type) {
      case 'task_start':
        setMessages(prev => [...prev, {
          id: data.task_id || `msg-${Date.now()}`,
          role: 'system',
          content: `Starting task: ${data.message || ''}`,
          timestamp,
          status: 'running'
        }]);
        setIsLoading(true);
        break;

      case 'planner_output':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === 'assistant') {
            return prev.map(msg => 
              msg.id === last.id ? { ...msg, plan: data.content, status: 'running' } : msg
            );
          }
          return [...prev, {
            id: `plan-${Date.now()}`,
            role: 'assistant',
            content: 'Generated plan:',
            timestamp,
            plan: data.content,
            status: 'running'
          }];
        });
        break;

      case 'executor_output':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === 'assistant') {
            const toolCall = {
              name: data.content.tool || 'unknown',
              args: {},
              result: data.content.output,
              status: 'completed'
            };
            return prev.map(msg => {
              if (msg.id === last.id) {
                const toolCalls = [...(msg.tool_calls || []), toolCall];
                return { ...msg, tool_calls: toolCalls };
              }
              return msg;
            });
          }
          return prev;
        });
        break;

      case 'verifier_output':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === 'assistant') {
            return prev.map(msg => {
              if (msg.id === last.id) {
                const verification = data.content;
                const status = verification.status === 'PASS' ? 'completed' : 'running';
                return { ...msg, status, content: msg.content + '\n\nVerification: ' + verification.feedback };
              }
              return msg;
            });
          }
          return prev;
        });
        break;

      case 'task_complete':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === 'assistant') {
            return prev.map(msg => {
              if (msg.id === last.id) {
                const finalAnswer = data.final_answer || 'Task completed.';
                return { ...msg, content: finalAnswer, status: 'completed' };
              }
              return msg;
            });
          }
          return [...prev, {
            id: `answer-${Date.now()}`,
            role: 'assistant',
            content: data.final_answer || 'Task completed.',
            timestamp,
            status: 'completed'
          }];
        });
        setIsLoading(false);
        break;

      case 'task_error':
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          role: 'system',
          content: `Error: ${data.error || 'Unknown error'}`,
          timestamp,
          status: 'failed'
        }]);
        setIsLoading(false);
        break;

      default:
        console.log("Unknown event type:", data.type);
        break;
    }
  };

  const sendMessage = useCallback(() => {
    if (!input.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMessage]);
    setInput('');

    wsRef.current.send(JSON.stringify({
      action: 'run_task',
      message: input.trim(),
      user_id: userId,
      tenant_id: tenantId,
      token: token // optional, already passed via query
    }));
  }, [input, userId, tenantId, token]);

  const togglePlan = (messageId: string) => {
    setExpandedPlans(prev => {
      const newSet = new Set(prev);
      if (newSet.has(messageId)) newSet.delete(messageId);
      else newSet.add(messageId);
      return newSet;
    });
  };

  return (
    <div className="flex flex-col h-full bg-gray-900 rounded-xl border border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 bg-gray-800">
        <div className="flex items-center gap-2">
          <Bot className="w-5 h-5 text-blue-400" />
          <span className="font-semibold text-white">Aether Agent</span>
          <span className={`text-xs ${isConnected ? 'text-green-400' : 'text-red-400'}`}>
            ● {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <div className="text-xs text-gray-400">
          {isLoading && <Loader2 className="w-4 h-4 animate-spin inline" />}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-center">
            <div>
              <Bot className="w-12 h-12 mx-auto mb-3 text-gray-600" />
              <p>Ask me anything about your business.</p>
              <p className="text-sm">I can help with sales, marketing, finance, and more.</p>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div key={message.id} className="flex flex-col">
              <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-3xl rounded-lg px-4 py-2 ${
                  message.role === 'user' 
                    ? 'bg-blue-600 text-white' 
                    : message.role === 'system'
                    ? 'bg-yellow-900/30 text-yellow-200 border border-yellow-700/30'
                    : 'bg-gray-800 text-gray-200'
                }`}>
                  <div className="flex items-center gap-2 mb-1">
                    {message.role === 'user' ? (
                      <User className="w-4 h-4" />
                    ) : message.role === 'system' ? (
                      <div className="text-yellow-400 text-xs">⚙️</div>
                    ) : (
                      <Bot className="w-4 h-4 text-blue-400" />
                    )}
                    <span className="text-xs opacity-70">
                      {message.timestamp.toLocaleTimeString()}
                    </span>
                    {message.status && (
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        message.status === 'completed' ? 'bg-green-900 text-green-300' :
                        message.status === 'running' ? 'bg-blue-900 text-blue-300 animate-pulse' :
                        message.status === 'failed' ? 'bg-red-900 text-red-300' :
                        'bg-gray-700 text-gray-400'
                      }`}>
                        {message.status}
                      </span>
                    )}
                  </div>
                  <div className="whitespace-pre-wrap">{message.content}</div>

                  {message.plan && message.plan.length > 0 && (
                    <div className="mt-2">
                      <button
                        onClick={() => togglePlan(message.id)}
                        className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                      >
                        {expandedPlans.has(message.id) ? (
                          <><ChevronUp className="w-3 h-3" /> Hide Plan</>
                        ) : (
                          <><ChevronDown className="w-3 h-3" /> Show Plan ({message.plan.length} steps)</>
                        )}
                      </button>
                      {expandedPlans.has(message.id) && (
                        <div className="mt-2 space-y-2 text-sm bg-gray-900/50 rounded p-2">
                          {message.plan.map((step, idx) => (
                            <div key={idx} className="flex items-start gap-2 border-b border-gray-700/50 pb-1 last:border-0">
                              <span className="text-gray-500 font-mono text-xs">{idx + 1}.</span>
                              <div className="flex-1">
                                <div className="text-gray-300">{step.description}</div>
                                {step.tool_name && step.tool_name !== 'None' && (
                                  <div className="text-xs text-gray-500">
                                    🔧 {step.tool_name}
                                    {step.tool_args && Object.keys(step.tool_args).length > 0 && (
                                      <span className="ml-1 text-gray-600">
                                        {JSON.stringify(step.tool_args)}
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {message.tool_calls && message.tool_calls.length > 0 && (
                    <div className="mt-2 text-sm">
                      <div className="text-xs text-gray-500">Tool Calls:</div>
                      {message.tool_calls.map((call, idx) => (
                        <div key={idx} className="ml-2 text-xs text-gray-400 border-l-2 border-gray-600 pl-2">
                          <div>🔧 {call.name}</div>
                          {call.result && (
                            <div className="text-gray-500 truncate">{String(call.result).substring(0, 100)}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-700 p-4 bg-gray-800">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder={isConnected ? "Type your task..." : "Connecting..."}
            disabled={!isConnected || isLoading}
            className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-white placeholder-gray-400 disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={!isConnected || isLoading || !input.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-white font-medium flex items-center gap-2 transition-colors"
          >
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Send
          </button>
        </div>
        <div className="text-xs text-gray-500 mt-2 text-center">
          {isConnected ? 'Connected to agent' : 'Reconnecting...'}
        </div>
      </div>
    </div>
  );
}