# OK.ru (Odnoklassniki) Integration Guide

## Overview

This document describes the integration of OK.ru (Odnoklassniki) social network into the LeaduxAI crossposting system.

## Architecture

```
okru.py (service layer)
    ├── OAuth flow (auth + callback)
    ├── Token management (load, refresh)
    ├── Signature generation (MD5)
    ├── Media upload (photosV2.getUploadUrl)
    └── Posting (mediatopic.post)

main.py (routes + crosspost logic)
    ├── /okru/auth - OAuth start
    ├── /okru/callback - OAuth callback  
    ├── /okru/groups - List groups
    └── platform routing in _do_crosspost()
```

## Required Environment Variables

```bash
# OK.ru Configuration
OKRU_ENABLED=false                    # Enable/disable platform
OKRU_APP_ID=                          # Application ID from ok.ru dev portal
OKRU_APP_KEY=                        # Application public key
OKRU_APP_SECRET=                     # Application secret key  
OKRU_REDIRECT_URI=https://your-domain/okru/callback
OKRU_TOKEN_FILE=/root/okru_token.json
```

## Scopes Required

OK.ru requires specific permissions. Request these from api-support@ok.ru:

- **VALUABLE_ACCESS** - Required for most API methods
- **LONG_ACCESS_TOKEN** - Token valid for 30 days, auto-extends on use
- **GROUP_CONTENT** - Permission to post in groups
- **PHOTO_CONTENT** - Permission to upload photos

## OAuth Flow

### Step 1: Configure Application

1. Register at https://ok.ru/app/
2. Get `app_id`, `application_key`, `application_secret_key`
3. Set redirect_uri to your callback URL
4. Request required permissions via email to api-support@ok.ru

### Step 2: User Authorization

```
User → /okru/auth → OK.ru OAuth Page → /okru/callback → Token saved
```

### Step 3: Token Exchange

```python
# Token response structure:
{
    "access_token": "...",
    "token_type": "session",
    "expires_in": 2592000,  # 30 days in seconds
    "refresh_token": "...",  # if LONG_ACCESS_TOKEN granted
    "obtained_at": 1234567890
}
```

## OK.ru API Reference

### Base URL
```
https://api.ok.ru/fb.do
```

### Signature Algorithm

```python
import hashlib
import urllib.parse

def generate_sig(params: dict) -> str:
    """OK.ru requires MD5 signature"""
    # 1. Sort params alphabetically
    # 2. Build string: key1=value1key2=value2...
    # 3. Append application_secret_key
    # 4. Calculate MD5
    
    sorted_keys = sorted(params.keys())
    sig_parts = [f"{k}={params[k]}" for k in sorted_keys]
    sig_string = "".join(sig_parts) + APP_SECRET
    return hashlib.md5(sig_string.encode()).hexdigest()
```

### Key API Methods

| Method | Description | Required Scope |
|--------|-------------|----------------|
| users.getCurrentUser | Get current user info | VALUABLE_ACCESS |
| group.getUserGroups | List user's groups | VALUABLE_ACCESS |
| group.getInfo | Get group details | VALUABLE_ACCESS |
| photosV2.getUploadUrl | Get photo upload URL | PHOTO_CONTENT |
| mediatopic.post | Create post | VALUABLE_ACCESS + GROUP_CONTENT |

## Post Structure

### Text-only Post
```json
{
    "media": [
        {
            "type": "text",
            "text": "Post text here"
        }
    ]
}
```

### Post with Photos
```json
{
    "media": [
        {
            "type": "text", 
            "text": "Post caption"
        },
        {
            "type": "photo",
            "token": "photo_token_from_upload"
        }
    ]
}
```

### Link Post
```json
{
    "media": [
        {
            "type": "text",
            "text": "Check this link"
        },
        {
            "type": "link", 
            "url": "https://example.com"
        }
    ]
}
```

## Database Schema (Future)

For multi-account support (when users can connect multiple OK.ru accounts):

```sql
-- Accounts table
CREATE TABLE okru_accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    app_id TEXT,
    user_info JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);

-- Connected groups
CREATE TABLE okru_groups (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES okru_accounts(id),
    group_id TEXT,
    group_name TEXT,
    group_photo TEXT,
    can_post BOOLEAN DEFAULT true,
    selected_for_posting BOOLEAN DEFAULT false
);

-- Post history
CREATE TABLE okru_posts (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES okru_accounts(id),
    group_id TEXT,
    post_id TEXT,
    message_text TEXT,
    media_urls JSONB,
    posted_at TIMESTAMP DEFAULT NOW(),
    telegram_message_id INTEGER
);
```

## Error Handling

### Common Errors

| Error Code | Description | Action |
|------------|-------------|--------|
| PARAM_SIG_INVALID | Invalid signature | Check secret_key and sig algorithm |
| AUTH_TOKEN_EXPIRED | Token expired | Refresh or re-authenticate |
| PERMISSION_DENIED | No required scope | Request permission from OK.ru |
| GROUP_ACCESS_DENIED | Can't post to group | Check GROUP_CONTENT permission |
| PHOTO_UPLOAD_ERROR | Upload failed | Retry with different method |

### Retry Strategy

```python
# Network errors - retry 3 times with exponential backoff
# Auth/signature errors - no retry, log error
# Permission errors - no retry, notify admin
```

## Queue Integration (Future)

For production queue-based posting:

```
Telegram Update → Queue → Worker → OKRU Adapter → OK.ru API
```

The adapter transforms internal payload to OK.ru attachment format:
1. Receive normalized post from queue
2. Transform to OK.ru media format
3. Upload media if present
4. Call mediatopic.post
5. Return result

## Deployment Checklist

### Development
- [ ] Create OK.ru application in dev portal
- [ ] Configure redirect URI
- [ ] Set test permissions
- [ ] Run OAuth flow
- [ ] Test text posting
- [ ] Test photo posting
- [ ] Test group selection

### Production
- [ ] Register production application
- [ ] Request production permissions (VALUABLE_ACCESS, LONG_ACCESS_TOKEN, GROUP_CONTENT, PHOTO_CONTENT)
- [ ] Configure HTTPS redirect URI
- [ ] Set up token encryption
- [ ] Configure OKRU_ENABLED=true
- [ ] Test with real posts

### Monitoring
- [ ] Set up error logging (without exposing tokens)
- [ ] Monitor token expiration
- [ ] Track API rate limits

## Testing Commands

```bash
# Test OAuth flow (development)
curl http://localhost:8080/okru/auth

# List user's groups
curl http://localhost:8080/okru/groups

# Test posting (via webhook)
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel_post": {"text": "Test post"}}'
```

## Security Notes

- Store tokens encrypted at rest
- Never log access_token or secret_key
- Use HTTPS for all OAuth redirects
- Rotate secrets periodically
- Monitor for token revocation