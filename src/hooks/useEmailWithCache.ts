import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';

const BACKEND_URL = 'http://127.0.0.1:8000';

interface EmailCacheStatus {
  has_cache: boolean;
  timestamp?: string;
  count: number;
  is_stale: boolean;
}

interface EmailListResult {
  messages: any[];
  from_cache: boolean;
  cache_status: 'fresh' | 'stale' | 'error';
  error?: string;
  cache_timestamp?: string;
}

export const useEmailWithCache = () => {
  const { idToken } = useAuth();
  const [emails, setEmails] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cacheStatus, setCacheStatus] = useState<EmailCacheStatus | null>(null);
  const [isFromCache, setIsFromCache] = useState(false);

  // Fetch cache status on mount
  useEffect(() => {
    if (!idToken) return;

    const fetchCacheStatus = async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/email/cache-info`, {
          headers: { Authorization: `Bearer ${idToken}` },
        });
        if (res.ok) {
          const data = await res.json();
          setCacheStatus(data);
        }
      } catch (err) {
        console.warn('Failed to fetch cache status:', err);
      }
    };

    fetchCacheStatus();
  }, [idToken]);

  const fetchEmails = useCallback(
    async (query: string = 'is:unread', maxResults: number = 10) => {
      if (!idToken) return;

      setLoading(true);
      setError(null);

      try {
        const res = await fetch(`${BACKEND_URL}/api/email/list`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${idToken}`,
          },
          body: JSON.stringify({
            query,
            max_results: maxResults,
            use_cache_fallback: true,
          }),
        });

        if (!res.ok) {
          throw new Error(`Failed to fetch emails (${res.status})`);
        }

        const data: EmailListResult = await res.json();
        setEmails(data.messages || []);
        setIsFromCache(data.from_cache);

        if (data.from_cache) {
          setError(
            data.error ||
              `Showing cached emails from ${data.cache_timestamp || 'earlier'}`
          );
        } else {
          setError(null);
        }

        // Update cache status
        setCacheStatus({
          has_cache: true,
          count: data.messages?.length || 0,
          is_stale: data.cache_status === 'stale',
          timestamp: data.cache_timestamp,
        });
      } catch (err) {
        const errMsg = err instanceof Error ? err.message : 'Failed to fetch emails';
        setError(errMsg);
        setEmails([]);
      } finally {
        setLoading(false);
      }
    },
    [idToken]
  );

  const clearCache = useCallback(async () => {
    if (!idToken) return;

    try {
      const res = await fetch(`${BACKEND_URL}/api/email/clear-cache`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${idToken}` },
      });

      if (res.ok) {
        setCacheStatus(null);
        setIsFromCache(false);
      }
    } catch (err) {
      console.error('Failed to clear cache:', err);
    }
  }, [idToken]);

  return {
    emails,
    loading,
    error,
    cacheStatus,
    isFromCache,
    fetchEmails,
    clearCache,
  };
};
