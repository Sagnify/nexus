export type ConnectorType = 'mcp' | 'api' | 'native' | 'local';

export type ConnectorStatus =
  | 'connected'
  | 'disconnected'
  | 'connecting'
  | 'action_required'
  | 'error'
  | 'disabled';

export type ConnectorCategory =
  | 'all'
  | 'productivity'
  | 'communication'
  | 'development'
  | 'media'
  | 'storage'
  | 'automation';

export interface ConnectorTool {
  tool_id: string;
  connector_id: string;
  name: string;
  description: string;
  risk_level: string; // 'safe' | 'caution' | 'dangerous'
  source: string;
  input_schema?: Record<string, any>;
  enabled?: boolean;
}

export interface ConnectorAuthField {
  id: string;
  label: string;
  type: string;
  placeholder?: string;
  required?: boolean;
}

export interface ConnectorItem {
  id: string;
  name: string;
  description: string;
  category: string;
  type: ConnectorType;
  icon: string;
  status: ConnectorStatus;
  auth_type: string;
  account_identifier?: string | null;
  connected_at?: string | null;
  capabilities: string[];
  discovered_tools: ConnectorTool[];
  error_message?: string | null;
  required_scopes?: string[];
  auth_fields?: ConnectorAuthField[];
}
