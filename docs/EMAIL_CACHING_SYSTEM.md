"""
EMAIL CACHING & FALLBACK SYSTEM - Implementation Guide
======================================================

PROBLEM SOLVED:
When Gmail connector fails or is unavailable, users see a generic help prompt instead of their emails.
This system automatically caches emails and displays cached data when the connector fails.

ARCHITECTURE:
=============

1. EMAIL CACHE SERVICE (backend/services/email_cache_service.py)
   - Persistent local storage of fetched emails
   - 24-hour TTL (configurable)
   - Metadata tracking (timestamp, count, user_id)
   - Graceful fallback when connector unavailable

2. CACHED GMAIL CONNECTOR (backend/connectors/adapters/gmail_cached.py)
   - Wraps standard Gmail connector
   - Automatically caches successful fetches
   - Falls back to cache on connector failure
   - Transparent to calling code

3. EMAIL API ENDPOINTS (backend/api/email.py)
   - POST /api/email/list - Fetch emails with fallback
   - GET /api/email/cache-info - Get cache status
   - POST /api/email/clear-cache - Clear user's cache
   - GET /api/email/cache-status - Debug cache info

4. FRONTEND COMPONENTS
   - EmailBriefView.tsx - Updated to show cache indicator
   - useEmailWithCache.ts - React hook for email operations

FLOW DIAGRAM:
=============

User requests emails
        |
        v
CachedGmailConnector.list_messages()
        |
        +---> Try Gmail API
        |       |
        |       +---> Success? Cache emails + return fresh data
        |       |
        |       +---> Failure? Check cache
        |               |
        |               +---> Cache exists? Return cached data + warning
        |               |
        |               +---> No cache? Re-raise error
        |
        v
Frontend displays emails (fresh or cached)
If cached: Show "📦 Cached summary" indicator


USAGE EXAMPLES:
===============

1. BACKEND - Using CachedGmailConnector:
   
   from backend.connectors.adapters.gmail_cached import CachedGmailConnector
   
   connector = CachedGmailConnector()
   result = await connector.list_messages(
       user_id="user123",
       query="is:unread",
       max_results=10,
       use_cache_fallback=True  # Enable fallback
   )
   
   # Result includes:
   # {
   #   "messages": [...],
   #   "from_cache": False,  # or True if fallback used
   #   "cache_status": "fresh",  # or "stale"
   #   "error": None  # or error message if cache was used
   # }


2. FRONTEND - Using useEmailWithCache Hook:
   
   import { useEmailWithCache } from '../hooks/useEmailWithCache';
   
   function EmailPanel() {
     const { emails, loading, error, isFromCache, fetchEmails } = useEmailWithCache();
     
     useEffect(() => {
       fetchEmails('is:unread', 10);
     }, []);
     
     return (
       <div>
         {isFromCache && <div className="warning">Using cached emails</div>}
         {emails.map(email => <EmailItem key={email.id} email={email} />)}
       </div>
     );
   }


3. API ENDPOINT - Direct HTTP:
   
   POST /api/email/list
   Authorization: Bearer <token>
   Content-Type: application/json
   
   {
     "query": "is:unread",
     "max_results": 10,
     "use_cache_fallback": true
   }
   
   Response:
   {
     "messages": [...],
     "from_cache": false,
     "cache_status": "fresh",
     "error": null
   }


CACHE STORAGE:
===============

Location: ~/.nexus/email_cache/
Files:
  - emails.json - Cached email data by user_id
  - cache_metadata.json - Cache metadata (optional)

Format:
{
  "user_123": {
    "emails": [...],
    "timestamp": "2024-01-15T10:30:00",
    "count": 42,
    "metadata": {
      "query": "is:unread",
      "max_results": 10
    }
  }
}


CONFIGURATION:
===============

Cache TTL (Time To Live):
  - Default: 24 hours
  - Modify in EmailCacheService.__init__():
    self.cache_ttl_hours = 24  # Change this value

Cache Directory:
  - Default: ~/.nexus/email_cache/
  - Override: EmailCacheService(cache_dir=Path("/custom/path"))


TESTING:
========

1. Test cache creation:
   - Fetch emails normally
   - Check ~/.nexus/email_cache/emails.json exists

2. Test fallback:
   - Disconnect Gmail connector
   - Fetch emails again
   - Should return cached data with "from_cache": true

3. Test cache expiration:
   - Wait 24+ hours or modify cache_ttl_hours to 0
   - Fetch emails with disconnected connector
   - Should fail (no valid cache)

4. Test cache clearing:
   - POST /api/email/clear-cache
   - Verify emails.json is cleared


MONITORING & DEBUGGING:
=======================

Check cache status:
  GET /api/email/cache-status
  
  Response:
  {
    "authenticated": true,
    "user_id": "user_123",
    "cache_available": true,
    "cache_metadata": {
      "timestamp": "2024-01-15T10:30:00",
      "count": 42,
      "is_stale": false
    }
  }

View cache info in UI:
  - EmailBriefView shows "📦 Cached summary" when using cache
  - useEmailWithCache hook provides isFromCache flag
  - Error message indicates cache fallback was used


FUTURE ENHANCEMENTS:
====================

1. Incremental sync - Only fetch new emails since last cache
2. Compression - Gzip cache for large email volumes
3. Encryption - Encrypt cached emails at rest
4. Multi-device sync - Sync cache across devices
5. Smart TTL - Adjust TTL based on email frequency
6. Partial cache - Cache only email headers, fetch bodies on demand
7. Offline mode - Full offline support with cached data
"""
