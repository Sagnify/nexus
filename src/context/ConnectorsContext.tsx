import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { ConnectorItem } from '../types/connectors';
import { useAuth } from './AuthContext';

interface ConnectorsContextValue {
  connectors: ConnectorItem[];
  isLoading: boolean;
  error: string | null;
  fetchConnectors: () => Promise<ConnectorItem[]>;
  connectConnector: (connectorId: string, authData: Record<string, any>) => Promise<boolean>;
  disconnectConnector: (connectorId: string) => Promise<boolean>;
  getGoogleAuthUrl: (connectorId: string) => Promise<string | null>;
  getSpotifyAuthUrl: () => Promise<string>;
}

const ConnectorsContext = createContext<ConnectorsContextValue | undefined>(undefined);

export const ConnectorsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();

  const getHeaders = useCallback(async () => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (user) {
      try {
        const token = await user.getIdToken();
        headers['Authorization'] = `Bearer ${token}`;
      } catch (_) {}
    }
    return headers;
  }, [user]);

  const fetchConnectors = useCallback(async (): Promise<ConnectorItem[]> => {
    setIsLoading(true);
    setError(null);
    try {
      const headers = await getHeaders();
      const res = await fetch('http://127.0.0.1:8000/api/connectors', { headers });
      if (!res.ok) {
        throw new Error(`Failed to fetch connectors: ${res.statusText}`);
      }
      const data = await res.json();
      const loadedConnectors = data.connectors || [];
      setConnectors(loadedConnectors);
      return loadedConnectors;
    } catch (err: any) {
      console.error('Error fetching connectors:', err);
      setError(err?.message || 'Could not load connectors.');
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [getHeaders]);

  const connectConnector = useCallback(
    async (connectorId: string, authData: Record<string, any>): Promise<boolean> => {
      try {
        const headers = await getHeaders();
        const res = await fetch(`http://127.0.0.1:8000/api/connectors/${connectorId}/connect`, {
          method: 'POST',
          headers,
          body: JSON.stringify(authData),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || 'Connection failed.');
        }
        await fetchConnectors();
        return true;
      } catch (err: any) {
        console.error(`Error connecting ${connectorId}:`, err);
        throw err;
      }
    },
    [getHeaders, fetchConnectors]
  );

  const disconnectConnector = useCallback(
    async (connectorId: string): Promise<boolean> => {
      try {
        const headers = await getHeaders();
        const res = await fetch(`http://127.0.0.1:8000/api/connectors/${connectorId}/disconnect`, {
          method: 'POST',
          headers,
        });
        if (!res.ok) {
          throw new Error('Failed to disconnect.');
        }
        await fetchConnectors();
        return true;
      } catch (err: any) {
        console.error(`Error disconnecting ${connectorId}:`, err);
        return false;
      }
    },
    [getHeaders, fetchConnectors]
  );

  const getGoogleAuthUrl = useCallback(
    async (connectorId: string): Promise<string | null> => {
      try {
        const headers = await getHeaders();
        const res = await fetch(
          `http://127.0.0.1:8000/api/connectors/google/auth-url?connector_id=${connectorId}`,
          { headers }
        );
        if (!res.ok) {
          throw new Error('Failed to generate Google auth URL.');
        }
        const data = await res.json();
        return data.url || null;
      } catch (err) {
        console.error('Error getting Google auth URL:', err);
        return null;
      }
    },
    [getHeaders]
  );

  const getSpotifyAuthUrl = useCallback(async (): Promise<string> => {
    const headers = await getHeaders();
    const res = await fetch('http://127.0.0.1:8000/api/connectors/spotify/auth-url', { headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.url) {
      throw new Error(data.detail || 'Could not start Spotify authorization.');
    }
    return data.url;
  }, [getHeaders]);

  useEffect(() => {
    fetchConnectors();
  }, [fetchConnectors]);

  return (
    <ConnectorsContext.Provider
      value={{
        connectors,
        isLoading,
        error,
        fetchConnectors,
        connectConnector,
        disconnectConnector,
        getGoogleAuthUrl,
        getSpotifyAuthUrl,
      }}
    >
      {children}
    </ConnectorsContext.Provider>
  );
};

export const useConnectors = () => {
  const context = useContext(ConnectorsContext);
  if (!context) {
    throw new Error('useConnectors must be used within a ConnectorsProvider');
  }
  return context;
};
