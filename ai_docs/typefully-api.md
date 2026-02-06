# Typefully API Documentation

> **Source:** https://typefully.com/docs/api
> **Retrieved:** 2026-02-06
> **API Version:** v2

## Overview

The Typefully Public API allows you to programmatically manage your social media drafts, schedule posts, and publish content across multiple platforms including X (Twitter), LinkedIn, Mastodon, Threads, and Bluesky.

## Base URL

```
https://api.typefully.com
```

## Authentication

All API requests require authentication using a Bearer token in the `Authorization` header.

### Getting Your API Key

1. Go to your [Typefully settings](https://typefully.com/settings)
2. Navigate to the API section
3. Generate a new API key
4. Store it securely - it will only be shown once

**Important:** API keys inherit the same permissions as the user who created them.

### Authentication Header

```
Authorization: Bearer YOUR_API_KEY
```

### Example Request

```bash
curl https://api.typefully.com/v2/me \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

---

## Endpoints

### Users

#### Get Current User

Retrieve the currently authenticated Typefully user associated with your API Key.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/me` |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | User ID |
| `name` | string | User's name |
| `email` | string | User's email address |
| `profile_image_url` | string | URL to user's profile image |
| `signup_date` | string | ISO 8601 date when user signed up |
| `api_key_label` | string | Label of the API key used for authentication |

**Example Request:**

```bash
curl https://api.typefully.com/v2/me \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

**Example Response:**

```json
{
  "id": 12345,
  "name": "John Doe",
  "email": "user@example.com",
  "profile_image_url": "https://example.com/avatar.jpg",
  "signup_date": "2024-01-15T10:30:00Z",
  "api_key_label": "My Production Key"
}
```

---

### Social Sets

Social sets represent connected social media accounts that you can manage through Typefully.

#### List Social Sets

Retrieve all social sets (accounts) you can access.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/social-sets` |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 10 | Number of results to return (max 50) |
| `offset` | integer | No | 0 | Number of results to skip |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `results` | array | Array of social set objects |
| `count` | integer | Total number of social sets |
| `limit` | integer | Limit applied to the request |
| `offset` | integer | Offset applied to the request |
| `next` | string | URL to next page of results |
| `previous` | string | URL to previous page of results |

**Social Set Object Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Social set ID |
| `username` | string | Username of the social set |
| `name` | string | Display name |
| `profile_image_url` | string | Profile image URL |
| `team` | object | Team information (`id`, `name`) |

**Example Request:**

```bash
curl 'https://api.typefully.com/v2/social-sets?limit=10&offset=0' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

**Example Response:**

```json
{
  "results": [
    {
      "id": 12345,
      "username": "elonmusk",
      "name": "Elon Musk",
      "profile_image_url": "https://example.com/avatar.jpg",
      "team": {
        "id": "abc123def4567890",
        "name": "Marketing Team"
      }
    }
  ],
  "count": 1,
  "limit": 10,
  "offset": 0,
  "next": null,
  "previous": null
}
```

---

#### Get Social Set Details

Retrieve detailed information about a social set, including configured platforms.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Social set ID |
| `username` | string | Username of the social set |
| `name` | string | Display name |
| `profile_image_url` | string | Profile image URL |
| `team` | object | Team information (`id`, `name`) |
| `platforms` | object | Configured platforms (`x`, `linkedin`, `mastodon`, `threads`, `bluesky`) |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/ \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

**Example Response:**

```json
{
  "id": 12345,
  "username": "elonmusk",
  "name": "Elon Musk",
  "profile_image_url": "https://example.com/avatar.jpg",
  "team": {
    "id": "abc123def4567890",
    "name": "Marketing Team"
  },
  "platforms": {
    "x": {
      "platform": "x",
      "username": "elonmusk",
      "name": "Elon Musk",
      "profile_image_url": "https://example.com/x-avatar.jpg"
    },
    "linkedin": null,
    "mastodon": null,
    "threads": null,
    "bluesky": null
  }
}
```

---

### Drafts

Drafts are the core content objects in Typefully. They can contain posts for multiple platforms and can be scheduled, published, or saved as drafts.

#### List Drafts

Retrieve all drafts for a specific social set with optional filtering.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/drafts` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | enum | No | - | Filter by status: `draft`, `published`, `scheduled`, `error`, `publishing` |
| `tag` | array | No | - | Filter by tag slugs |
| `order_by` | enum | No | `-updated_at` | Sort order |
| `limit` | integer | No | - | Number of results to return |
| `offset` | integer | No | - | Number of results to skip |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `results` | array | Array of draft objects |
| `count` | integer | Total number of drafts |
| `limit` | integer | Limit applied |
| `offset` | integer | Offset applied |
| `next` | string | Next page URL |
| `previous` | string | Previous page URL |

**Example Request:**

```bash
curl 'https://api.typefully.com/v2/social-sets/1/drafts?status=draft&order_by=-updated_at&limit=10&offset=0' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

---

#### Create Draft

Create a new draft. Applies Auto-Retweet, Auto-Plug, and Natural Posting Time if enabled in your settings.

| Property | Value |
|----------|-------|
| **Method** | `POST` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/drafts` |
| **Content-Type** | `application/json` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |

**Request Body Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `platforms` | object | Yes | Platform configuration with posts (see below) |
| `draft_title` | string | No | Title for the draft (max 512 characters) |
| `scratchpad_text` | string | No | Notes for the draft |
| `tags` | array | No | Array of tag slugs to apply |
| `share` | boolean | No | Whether to share the draft publicly |
| `publish_at` | string | No | ISO 8601 datetime to schedule publication |

**Platforms Object Structure:**

```json
{
  "x": {
    "enabled": true,
    "posts": [
      {
        "text": "First tweet in thread",
        "media": ["media_id_1", "media_id_2"]
      },
      {
        "text": "Second tweet in thread"
      }
    ]
  },
  "linkedin": {
    "enabled": true,
    "posts": [
      {
        "text": "LinkedIn post content"
      }
    ]
  }
}
```

**Post Object Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Post content |
| `media` | array | No | Array of media IDs (UUIDs from media upload) |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Draft ID |
| `social_set_id` | integer | Social set ID |
| `status` | string | Draft status (`draft`, `scheduled`, `published`, `error`, `publishing`) |
| `created_at` | string | ISO 8601 creation timestamp |
| `updated_at` | string | ISO 8601 last update timestamp |
| `scheduled_date` | string | ISO 8601 scheduled publication date (if scheduled) |
| `published_at` | string | ISO 8601 publication timestamp (if published) |
| `draft_title` | string | Draft title |
| `tags` | array | Associated tags |
| `preview` | string | Preview text |
| `share_url` | string | Public share URL |
| `private_url` | string | Private URL |
| `platforms` | object | Platform details with posts |
| `x_published_url` | string | X (Twitter) published URL (after publishing) |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/drafts \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
    "platforms": {
      "x": {
        "enabled": true,
        "posts": [
          {"text": "1/ This is the first tweet in my thread"},
          {"text": "2/ And this is the second tweet"}
        ]
      }
    },
    "draft_title": "My Thread",
    "share": true
  }'
```

**Example Response:**

```json
{
  "id": 12345,
  "social_set_id": 67890,
  "status": "draft",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z",
  "scheduled_date": null,
  "published_at": null,
  "draft_title": "My Thread",
  "tags": [],
  "preview": "1/ This is the first tweet in my thread",
  "share_url": "https://typefully.com/share/abc123",
  "private_url": "https://typefully.com/draft/abc123",
  "platforms": {
    "x": {
      "enabled": true,
      "posts": [
        {"text": "1/ This is the first tweet in my thread", "media": []},
        {"text": "2/ And this is the second tweet", "media": []}
      ]
    }
  },
  "x_published_url": null
}
```

---

#### Get Draft

Retrieve a specific draft by ID.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/drafts/{draft_id}` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |
| `draft_id` | integer | Yes | ID of the draft |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/drafts/12345 \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

---

#### Update Draft

Update an existing draft with partial update semantics (PATCH).

| Property | Value |
|----------|-------|
| **Method** | `PATCH` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/drafts/{draft_id}` |
| **Content-Type** | `application/json` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |
| `draft_id` | integer | Yes | ID of the draft |

**Request Body Fields:**

All fields are optional. Only include fields you want to update.

| Field | Type | Description |
|-------|------|-------------|
| `platforms` | object | Updated platform configuration |
| `draft_title` | string | Updated draft title |
| `scratchpad_text` | string | Updated notes |
| `tags` | array | Updated tags (replaces existing) |
| `share` | boolean | Updated share setting |
| `publish_at` | string | Updated publication time (ISO 8601) |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/drafts/12345 \
  --request PATCH \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
    "platforms": {
      "x": {
        "enabled": true,
        "posts": [
          {"text": "Updated first tweet"},
          {"text": "Updated second tweet"}
        ]
      }
    },
    "publish_at": "2025-01-20T10:30:00Z"
  }'
```

---

#### Delete Draft

Delete a draft in any status.

| Property | Value |
|----------|-------|
| **Method** | `DELETE` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/drafts/{draft_id}` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |
| `draft_id` | integer | Yes | ID of the draft |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/drafts/12345 \
  --request DELETE \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

**Response:** `204 No Content`

---

### Media

Upload images and videos to use in your posts.

#### Create Media Upload

Generate a presigned S3 upload URL for media.

| Property | Value |
|----------|-------|
| **Method** | `POST` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/media/upload` |
| **Content-Type** | `application/json` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |

**Request Body Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_name` | string | Yes | File name with extension |

**Supported File Extensions:**
- Images: `jpg`, `jpeg`, `png`, `webp`, `gif`
- Videos: `mp4`, `mov`
- Documents: `pdf`

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `media_id` | uuid | Unique identifier for the uploaded media |
| `upload_url` | string | Presigned S3 URL for uploading the file |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/media/upload \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{"file_name": "profile-photo.jpg"}'
```

**Example Response:**

```json
{
  "media_id": "550e8400-e29b-41d4-a716-446655440000",
  "upload_url": "https://s3.amazonaws.com/bucket/path?presigned-params..."
}
```

**Upload the File:**

After receiving the presigned URL, upload your file using a PUT request:

```bash
curl --request PUT \
  --header 'Content-Type: image/jpeg' \
  --data-binary '@/path/to/profile-photo.jpg' \
  'https://s3.amazonaws.com/bucket/path?presigned-params...'
```

---

#### Get Media Status

Retrieves the processing status of an uploaded media file.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/media/{media_id}` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |
| `media_id` | uuid | Yes | Media UUID |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `media_id` | uuid | Media ID |
| `file_name` | string | Original file name |
| `mime` | string | MIME type |
| `status` | string | Processing status (`ready`, `processing`, `error`) |
| `error_reason` | string | Error reason if processing failed |
| `media_urls` | object | URLs for different sizes |

**Media URLs Object:**

| Field | Type | Description |
|-------|------|-------------|
| `large` | string | Large size URL |
| `medium` | string | Medium size URL |
| `original` | string | Original size URL |
| `small` | string | Small/thumbnail size URL |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/media/550e8400-e29b-41d4-a716-446655440000 \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

**Example Response:**

```json
{
  "media_id": "550e8400-e29b-41d4-a716-446655440000",
  "file_name": "profile-photo.jpg",
  "mime": "image/jpeg",
  "status": "ready",
  "error_reason": null,
  "media_urls": {
    "large": "https://cdn.typefully.com/media/large/...",
    "medium": "https://cdn.typefully.com/media/medium/...",
    "original": "https://cdn.typefully.com/media/original/...",
    "small": "https://cdn.typefully.com/media/small/..."
  }
}
```

---

### Tags

Organize your drafts with tags.

#### List Tags

Retrieve all tags for a social set.

| Property | Value |
|----------|-------|
| **Method** | `GET` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/tags` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | - | Number of results to return |
| `offset` | integer | No | - | Number of results to skip |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `results` | array | Array of tag objects |
| `count` | integer | Total number of tags |
| `limit` | integer | Limit applied |
| `offset` | integer | Offset applied |
| `next` | string | Next page URL |
| `previous` | string | Previous page URL |

**Tag Object Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Tag slug (URL-safe identifier) |
| `name` | string | Tag name |
| `created_at` | string | ISO 8601 creation timestamp |

**Example Request:**

```bash
curl 'https://api.typefully.com/v2/social-sets/1/tags?limit=10&offset=0' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'
```

**Example Response:**

```json
{
  "results": [
    {
      "slug": "marketing",
      "name": "Marketing",
      "created_at": "2025-01-15T10:30:00Z"
    },
    {
      "slug": "product-updates",
      "name": "Product Updates",
      "created_at": "2025-01-10T08:00:00Z"
    }
  ],
  "count": 2,
  "limit": 10,
  "offset": 0,
  "next": null,
  "previous": null
}
```

---

#### Create Tag

Create a new tag. The slug is auto-generated from the name.

| Property | Value |
|----------|-------|
| **Method** | `POST` |
| **URL** | `https://api.typefully.com/v2/social-sets/{social_set_id}/tags` |
| **Content-Type** | `application/json` |

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `social_set_id` | integer | Yes | ID of the social set |

**Request Body Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Tag name (1-32 characters) |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Auto-generated tag slug |
| `name` | string | Tag name |
| `created_at` | string | ISO 8601 creation timestamp |

**Example Request:**

```bash
curl https://api.typefully.com/v2/social-sets/1/tags \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{"name": "Marketing"}'
```

**Example Response:**

```json
{
  "slug": "marketing",
  "name": "Marketing",
  "created_at": "2025-01-15T10:30:00Z"
}
```

---

## Rate Limits

API requests are rate-limited on a per user and per social set basis.

### Rate Limit Types

| Type | Scope | Description |
|------|-------|-------------|
| User Rate Limits | Per user | Applies to all endpoints |
| Social Set Rate Limits | Per social set | Applies to specific operations like draft creation |

### Rate Limit Response Headers

All API responses include headers showing your current rate limit status:

| Header | Description |
|--------|-------------|
| `X-RateLimit-User-Limit` | Maximum user requests allowed |
| `X-RateLimit-User-Remaining` | User requests remaining |
| `X-RateLimit-User-Reset` | Unix timestamp when user limit resets |
| `X-RateLimit-SocialSet-Limit` | Maximum social set requests allowed |
| `X-RateLimit-SocialSet-Remaining` | Social set requests remaining |
| `X-RateLimit-SocialSet-Reset` | Unix timestamp when social set limit resets |
| `X-RateLimit-SocialSet-Resource` | Resource being limited (e.g., `drafts.create`) |

### Handling Rate Limits

When you exceed the rate limit, you'll receive a `429 Too Many Requests` response. Best practices:

1. Check the `X-RateLimit-*-Remaining` headers before making requests
2. Use the `X-RateLimit-*-Reset` timestamp to know when to retry
3. Implement exponential backoff for retries

---

## Error Handling

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created |
| `204` | No Content (successful deletion) |
| `400` | Invalid request data, validation error, or draft cannot be edited |
| `401` | Missing or invalid authentication |
| `402` | Account is paused or requires a paid plan |
| `403` | Insufficient permissions, feature not available, or forbidden access to social set |
| `404` | Resource not found |
| `422` | Schema validation error |
| `429` | Too Many Requests / Rate limited |

### Error Response Format

```json
{
  "error": "Error message describing what went wrong",
  "details": {
    "field_name": ["Specific validation error"]
  }
}
```

---

## Webhooks

Receive real-time notifications for account events via webhooks.

### Configuration

Configure your webhook endpoint URL in your [Typefully API settings](https://typefully.com/settings).

### Webhook Events

| Event | Description |
|-------|-------------|
| `draft.created` | New draft created |
| `draft.scheduled` | Draft scheduled for publishing |
| `draft.published` | Draft successfully published |
| `draft.status_changed` | Any status transition |
| `draft.tags_changed` | Draft tags modified |
| `draft.deleted` | Draft deleted |

### Webhook Payload

```json
{
  "event": "draft.published",
  "data": {
    "id": 12345,
    "social_set_id": 67890,
    "status": "published",
    "created_at": "2025-01-15T10:30:00Z",
    "updated_at": "2025-01-15T12:00:00Z",
    "published_at": "2025-01-15T12:00:00Z",
    "draft_title": "My Thread",
    "platforms": {
      "x": {
        "enabled": true,
        "posts": [...]
      }
    },
    "x_published_url": "https://twitter.com/user/status/123456789"
  }
}
```

### Signature Verification

Verify webhook authenticity using HMAC-SHA256 signatures.

**Headers:**
- `X-Typefully-Signature`: Signature in format `sha256=<hex_digest>`
- `X-Typefully-Timestamp`: Unix timestamp of the request

**Verification Process:**

1. Get your webhook secret from your API settings
2. Construct the signed payload: `{timestamp}.{request_body}`
3. Compute HMAC-SHA256 using your secret
4. Compare with the signature in `X-Typefully-Signature`

**Python Example:**

```python
import hmac
import hashlib

def verify_webhook(secret: str, timestamp: str, body: str, signature: str) -> bool:
    expected_sig = hmac.new(
        secret.encode(),
        f"{timestamp}.{body}".encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected_sig}", signature)
```

### Failure Handling

- Webhooks are retried with exponential backoff (4 retries, 5 attempts total) over approximately 1 hour
- Your endpoint must return a `2xx` status code to be considered successful
- Webhooks are automatically disabled after 100 consecutive failures
- You'll receive an email notification when webhooks are disabled
- Re-enable from your API settings after fixing the endpoint issue

---

## Common Use Cases

### Creating and Scheduling a Thread

```bash
# Create a scheduled thread
curl https://api.typefully.com/v2/social-sets/1/drafts \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
    "platforms": {
      "x": {
        "enabled": true,
        "posts": [
          {"text": "1/ Here is my thread about an important topic..."},
          {"text": "2/ The first key point is..."},
          {"text": "3/ Another important consideration..."},
          {"text": "4/ In conclusion..."}
        ]
      }
    },
    "draft_title": "Important Topic Thread",
    "publish_at": "2025-01-20T14:00:00Z"
  }'
```

### Uploading Media and Creating a Post

```bash
# Step 1: Get upload URL
UPLOAD_RESPONSE=$(curl -s https://api.typefully.com/v2/social-sets/1/media/upload \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{"file_name": "chart.png"}')

MEDIA_ID=$(echo $UPLOAD_RESPONSE | jq -r '.media_id')
UPLOAD_URL=$(echo $UPLOAD_RESPONSE | jq -r '.upload_url')

# Step 2: Upload the file
curl --request PUT \
  --header 'Content-Type: image/png' \
  --data-binary '@chart.png' \
  "$UPLOAD_URL"

# Step 3: Wait for processing and check status
curl https://api.typefully.com/v2/social-sets/1/media/$MEDIA_ID \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN'

# Step 4: Create post with media
curl https://api.typefully.com/v2/social-sets/1/drafts \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data "{
    \"platforms\": {
      \"x\": {
        \"enabled\": true,
        \"posts\": [
          {
            \"text\": \"Check out this chart!\",
            \"media\": [\"$MEDIA_ID\"]
          }
        ]
      }
    }
  }"
```

### Cross-Posting to Multiple Platforms

```bash
curl https://api.typefully.com/v2/social-sets/1/drafts \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
    "platforms": {
      "x": {
        "enabled": true,
        "posts": [
          {"text": "Exciting news! We just launched our new feature."}
        ]
      },
      "linkedin": {
        "enabled": true,
        "posts": [
          {"text": "Exciting news! We just launched our new feature.\n\nLearn more at example.com"}
        ]
      },
      "threads": {
        "enabled": true,
        "posts": [
          {"text": "Exciting news! We just launched our new feature."}
        ]
      }
    },
    "publish_at": "2025-01-20T10:00:00Z"
  }'
```

---

## SDK and Libraries

While Typefully does not provide official SDKs, the API is straightforward to use with any HTTP client. Here are examples in popular languages:

### Python

```python
import requests

API_KEY = "your_api_key"
BASE_URL = "https://api.typefully.com/v2"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Get current user
response = requests.get(f"{BASE_URL}/me", headers=headers)
user = response.json()

# Create a draft
draft_data = {
    "platforms": {
        "x": {
            "enabled": True,
            "posts": [{"text": "Hello from Python!"}]
        }
    }
}
response = requests.post(
    f"{BASE_URL}/social-sets/1/drafts",
    headers=headers,
    json=draft_data
)
draft = response.json()
```

### JavaScript/Node.js

```javascript
const API_KEY = 'your_api_key';
const BASE_URL = 'https://api.typefully.com/v2';

const headers = {
  'Authorization': `Bearer ${API_KEY}`,
  'Content-Type': 'application/json'
};

// Get current user
const userResponse = await fetch(`${BASE_URL}/me`, { headers });
const user = await userResponse.json();

// Create a draft
const draftData = {
  platforms: {
    x: {
      enabled: true,
      posts: [{ text: 'Hello from JavaScript!' }]
    }
  }
};

const draftResponse = await fetch(`${BASE_URL}/social-sets/1/drafts`, {
  method: 'POST',
  headers,
  body: JSON.stringify(draftData)
});
const draft = await draftResponse.json();
```

---

## Changelog

For the latest API updates and changes, check the [Typefully documentation](https://typefully.com/docs/api).
