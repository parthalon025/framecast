# FrameCast API Reference

All API endpoints are prefixed with `/api/` and return JSON. State-changing endpoints (POST, PUT, DELETE) require PIN authentication via cookie and are subject to Origin header validation.

**Rate limiting:** State-changing endpoints (POST, PUT, DELETE) are rate limited to 60 requests per minute per IP address. GET requests are not rate limited. Exceeding the limit returns `429` with a `retry_after` field in the JSON body.

**Authentication:** Endpoints marked with a lock icon require a valid `framecast_pin` cookie. Obtain one via `POST /api/auth/verify`.

---

## Table of Contents

- [Authentication](#authentication)
- [Photos](#photos)
- [Albums](#albums)
- [Tags](#tags)
- [Users](#users)
- [Stats](#stats)
- [Settings](#settings)
- [Display](#display)
- [Slideshow](#slideshow)
- [WiFi](#wifi)
- [System](#system)
- [Updates](#updates)
- [Backup](#backup)
- [SSE Events](#sse-events)

---

## Authentication

### Verify PIN

Validate a PIN and receive an auth cookie.

```
POST /api/auth/verify
```

**Request:**
```json
{
  "pin": "1234"
}
```

**Success (200):**
```json
{
  "status": "ok",
  "message": "AUTHORIZED"
}
```

Sets `framecast_pin` cookie (HttpOnly, SameSite=Strict, 30-day expiry).

**Open access (200):**
```json
{
  "status": "ok",
  "message": "AUTHORIZED -- open access"
}
```

Returned when no PIN is configured (empty or "0000").

**Failed (401):**
```json
{
  "error": "ACCESS DENIED",
  "needs_pin": true
}
```

**Rate limited (429):**
```json
{
  "error": "TOO MANY ATTEMPTS \u2014 TRY AGAIN LATER",
  "retry_after": 287
}
```

Rate limit: 5 attempts for 4-digit PIN, 3 attempts for 6-digit PIN. 5-minute lockout.

---

## Photos

### List Photos

Return all visible (non-quarantined, non-hidden) photos.

```
GET /api/photos
```

**Response (200):**
```json
[
  {
    "id": 1,
    "filename": "beach_sunset.jpg",
    "name": "beach_sunset.jpg",
    "filepath": "/home/pi/media/beach_sunset.jpg",
    "mime_type": "image/jpeg",
    "file_size": 2458624,
    "size_human": "2.3 MB",
    "width": 1920,
    "height": 1080,
    "is_video": false,
    "is_favorite": false,
    "is_hidden": false,
    "view_count": 47,
    "gps_lat": 34.0195,
    "gps_lon": -118.4912,
    "uploaded_at": "2026-03-15T14:23:07",
    "uploaded_by": "alice"
  }
]
```

### Upload Photos

Upload one or more photos/videos.

```
POST /upload
```

**Request:** `multipart/form-data` with `files` field containing one or more files.

**Success (200):**
```json
{
  "uploaded": ["beach_sunset.jpg", "family_dinner.png"],
  "uploaded_count": 2,
  "skipped": 0
}
```

**No files (400):**
```json
{
  "error": "No files selected"
}
```

**Disk full (507):**
```json
{
  "error": "Not enough disk space"
}
```

**Concurrent upload (429):**
```json
{
  "error": "Another upload is in progress"
}
```

Notes:
- Max upload size controlled by `MAX_UPLOAD_MB` setting (default 200 MB)
- Images are auto-resized if larger than `AUTO_RESIZE_MAX` pixels
- Duplicate filenames get a UUID suffix
- Corrupt images are quarantined automatically
- Fires `photo:added` SSE event for each uploaded file

### Delete Photo

Delete a single photo by filename.

```
POST /delete
```

**Request:** `application/x-www-form-urlencoded` with `filename` field.

**Success (200):**
```json
{
  "status": "ok",
  "filename": "beach_sunset.jpg"
}
```

**Not found (404):**
```json
{
  "error": "File not found"
}
```

Fires `photo:deleted` SSE event.

### Delete All Photos

Delete all media files. Requires confirmation.

```
POST /delete-all
```

**Request:** `application/x-www-form-urlencoded` with `confirm=DELETE`.

Redirects to index page on completion (form-based endpoint, not JSON).

### Toggle Favorite

Toggle the favorite status of a photo.

```
POST /api/photos/{photo_id}/favorite
```

**Response (200):**
```json
{
  "status": "ok",
  "photo_id": 1,
  "is_favorite": true
}
```

**Not found (404):**
```json
{
  "error": "Photo not found"
}
```

### GPS Locations

Return GPS coordinates for all geotagged photos.

```
GET /api/locations
```

**Response (200):**
```json
[
  {
    "name": "beach_sunset.jpg",
    "lat": 34.0195,
    "lon": -118.4912
  }
]
```

---

## Albums

### List Albums

Return all albums (regular and smart).

```
GET /api/albums
```

**Response (200):**
```json
[
  {
    "id": 1,
    "name": "Vacation 2026",
    "description": "Spring break photos",
    "cover_photo_id": 12,
    "photo_count": 24,
    "smart": false
  },
  {
    "id": "smart:recent",
    "name": "Recent",
    "description": null,
    "cover_photo_id": 45,
    "photo_count": 15,
    "smart": true
  }
]
```

Smart albums (`smart: true`) are computed queries, not stored in the database.

### Create Album

```
POST /api/albums
```

**Request:**
```json
{
  "name": "Vacation 2026",
  "description": "Spring break photos"
}
```

**Success (201):**
```json
{
  "status": "ok",
  "album_id": 1
}
```

**Duplicate name (409):**
```json
{
  "error": "Album name already exists"
}
```

### Delete Album

Delete an album. Photos are unlinked, not deleted.

```
DELETE /api/albums/{album_id}
```

**Response (200):**
```json
{
  "status": "ok"
}
```

### Add Photo to Album

```
POST /api/albums/{album_id}/photos
```

**Request:**
```json
{
  "photo_id": 12
}
```

**Response (200):**
```json
{
  "status": "ok"
}
```

### Remove Photo from Album

```
DELETE /api/albums/{album_id}/photos/{photo_id}
```

**Response (200):**
```json
{
  "status": "ok"
}
```

---

## Tags

### List Photo Tags

```
GET /api/photos/{photo_id}/tags
```

**Response (200):**
```json
[
  {
    "id": 1,
    "name": "sunset"
  },
  {
    "id": 3,
    "name": "beach"
  }
]
```

### Add Tag to Photo

```
POST /api/photos/{photo_id}/tags
```

**Request:**
```json
{
  "name": "sunset"
}
```

**Success (201):**
```json
{
  "status": "ok",
  "tag_id": 1
}
```

### Remove Tag from Photo

```
DELETE /api/photos/{photo_id}/tags/{tag_id}
```

**Response (200):**
```json
{
  "status": "ok"
}
```

---

## Users

### List Users

```
GET /api/users
```

**Response (200):**
```json
[
  {
    "id": 1,
    "name": "alice",
    "created_at": "2026-03-15T10:00:00",
    "is_admin": false,
    "upload_count": 24,
    "last_upload_at": "2026-03-19T14:30:00"
  }
]
```

### Create User

```
POST /api/users
```

**Request:**
```json
{
  "name": "bob",
  "is_admin": false
}
```

**Success (201):**
```json
{
  "status": "ok",
  "user_id": 2
}
```

**Duplicate name (409):**
```json
{
  "error": "User name already exists"
}
```

---

## Stats

### Get Stats

Return aggregated content and display statistics.

```
GET /api/stats
```

**Response (200):**
```json
{
  "total_photos": 312,
  "videos": 8,
  "total_size": 1073741824,
  "favorites": 24,
  "albums": 3,
  "users": 4,
  "most_shown": [
    {"id": 1, "filename": "beach_sunset.jpg", "view_count": 147}
  ],
  "least_shown": [
    {"id": 45, "filename": "old_photo.jpg", "view_count": 2}
  ]
}
```

---

## Settings

### Get Settings

```
GET /api/settings
```

**Response (200):**
```json
{
  "photo_duration": 10,
  "shuffle": true,
  "transition_type": "fade",
  "photo_order": "shuffle",
  "qr_display_seconds": 30,
  "hdmi_schedule_enabled": false,
  "hdmi_off_time": "22:00",
  "hdmi_on_time": "08:00",
  "max_upload_mb": 200,
  "auto_resize_max": 1920,
  "auto_update_enabled": false,
  "web_port": 8080
}
```

### Update Settings

```
POST /api/settings
```

**Request:** Partial update -- only include fields to change.
```json
{
  "photo_duration": 15,
  "transition_type": "slide",
  "hdmi_schedule_enabled": true,
  "hdmi_off_time": "23:00",
  "hdmi_on_time": "07:00"
}
```

**Success (200):**
```json
{
  "status": "ok",
  "settings": { ... }
}
```

**Validation error (400):**
```json
{
  "error": "Invalid transition_type: must be one of ['dissolve', 'fade', 'none', 'slide', 'zoom']"
}
```

Fires `settings:changed` SSE event with the new settings object.

**Field validation:**
- `photo_duration`, `max_upload_mb`, `auto_resize_max`: positive integer
- `qr_display_seconds`: 0 or positive integer
- `hdmi_off_time`, `hdmi_on_time`: HH:MM format (00:00-23:59)
- `transition_type`: one of `fade`, `slide`, `zoom`, `dissolve`, `none`
- `photo_order`: one of `shuffle`, `newest`, `oldest`, `alphabetical`
- `web_port`: not settable via API (security)

---

## Display

### System Status

Return system status including disk usage, counts, version, and settings.

```
GET /api/status
```

**Response (200):**
```json
{
  "photo_count": 304,
  "video_count": 8,
  "disk": {
    "total": 31457280000,
    "used": 8589934592,
    "free": 22867345408,
    "percent": 27
  },
  "version": "2.0.0",
  "settings": { ... }
}
```

When called from localhost (`127.0.0.1`), the response includes `access_pin` (used by the TV display to show the PIN on screen).

---

## Slideshow

### Get Playlist

Return a weighted playlist of photo IDs for the slideshow. The client fetches this and plays locally, reducing API calls.

```
GET /api/slideshow/playlist?count=50
```

**Parameters:**
- `count` (optional): Number of photos in playlist (default 50, max 200)

**Response (200):**
```json
{
  "photos": [
    {"id": 12, "filename": "sunset.jpg", "filepath": "/home/pi/media/sunset.jpg"},
    {"id": 7, "filename": "family.png", "filepath": "/home/pi/media/family.png"}
  ],
  "playlist_id": "abc123"
}
```

---

## WiFi

### WiFi Status

```
GET /api/wifi/status
```

**Response (200):**
```json
{
  "connected": true,
  "ssid": "HomeNetwork",
  "ap_active": false,
  "ap_ssid": "FrameCast"
}
```

### Scan Networks

```
GET /api/wifi/scan
```

**Response (200):**
```json
[
  {
    "ssid": "HomeNetwork",
    "signal": 85,
    "security": "WPA2"
  },
  {
    "ssid": "Neighbor5G",
    "signal": 42,
    "security": "WPA3"
  }
]
```

### Connect to Network

```
POST /api/wifi/connect
```

**Request:**
```json
{
  "ssid": "HomeNetwork",
  "password": "secret123"
}
```

**Success (200):**
```json
{
  "success": true,
  "message": "Connected to HomeNetwork"
}
```

**Failed (502):**
```json
{
  "success": false,
  "message": "Connection failed: wrong password"
}
```

### Start AP Mode

```
POST /api/wifi/ap/start
```

**Response (200):**
```json
{
  "success": true,
  "message": "AP started"
}
```

### Stop AP Mode

```
POST /api/wifi/ap/stop
```

**Response (200):**
```json
{
  "success": true,
  "message": "AP stopped"
}
```

---

## System

### Restart Slideshow

Restart the framecast and kiosk services.

```
POST /api/restart-slideshow
```

**Response (200):**
```json
{
  "status": "ok",
  "message": "Slideshow restarted"
}
```

### Reboot Device

```
POST /api/reboot
```

**Response (200):**
```json
{
  "status": "ok",
  "message": "Device is rebooting..."
}
```

### Shutdown Device

```
POST /api/shutdown
```

**Response (200):**
```json
{
  "status": "ok",
  "message": "Device is shutting down..."
}
```

---

## Updates

### Check for Update

```
POST /api/update/check
```

**Response (200):**
```json
{
  "available": true,
  "current": "2.0.0",
  "latest": "2.1.0",
  "url": "https://github.com/parthalon025/framecast/releases/tag/v2.1.0",
  "tag_name": "v2.1.0",
  "target_commitish": "abc123def456..."
}
```

### Apply Update

Apply a specific version tag. Reboots automatically on success.

```
POST /api/update/apply
```

**Request:**
```json
{
  "tag": "v2.1.0",
  "expected_sha": "abc123def456..."
}
```

The `expected_sha` field (from `check_for_update`'s `target_commitish`) is used to verify the fetched tag matches. If the SHA does not match after `git fetch`, the update is aborted.

**Success (200):**
```json
{
  "success": true,
  "message": "Updated from v2.0.0 to v2.1.0"
}
```

Fires `update:rebooting` SSE event, then reboots after 5 seconds.

**SHA mismatch (200, success=false):**
```json
{
  "success": false,
  "message": "Update aborted \u2014 SHA mismatch: expected abc123def456, got 789012345678"
}
```

---

## Backup

### Download Database Backup

Download a copy of the SQLite database.

```
GET /api/backup
```

**Response (200):** Binary file download (`application/x-sqlite3`, filename `framecast.db.backup`).

**Not found (404):**
```json
{
  "error": "Database not found"
}
```

---

## SSE Events

Connect to the Server-Sent Events stream for real-time updates.

```
GET /api/events
```

**Headers:**
- `Last-Event-ID` (optional): Resume from a specific event ID after reconnection

**Event format:**
```
id: 42
event: photo:added
data: {"filename": "sunset.jpg", "photo_id": 12}
```

### Event Types

| Event | Payload | Trigger |
|-------|---------|---------|
| `state:current` | `{"connected": true, "clients": 3}` | Sent on initial connection |
| `photo:added` | `{"filename": "...", "photo_id": N}` | Photo uploaded |
| `photo:deleted` | `{"filename": "..."}` | Photo deleted |
| `photo:favorited` | `{"photo_id": N, "is_favorite": bool}` | Favorite toggled |
| `settings:changed` | `{...settings object...}` | Settings updated |
| `update:rebooting` | `{"version": "v2.1.0"}` | OTA update applied, reboot imminent |

**Keepalive:** The server sends `: keepalive\n\n` comments every 20 seconds (configurable via `SSE_KEEPALIVE` env var) to prevent connection timeout.

**Reconnection:** The client should send `Last-Event-ID` header on reconnect. The server replays up to 50 buffered events that occurred after that ID.

**Max clients:** 10 concurrent SSE connections (Pi RAM constraint). Connection 11+ receives an error event and is closed.

---

## Error Responses

All error responses follow this format:

```json
{
  "error": "DESCRIPTION"
}
```

### Common Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created (new album, tag, user) |
| 400 | Bad request (missing fields, validation error) |
| 401 | PIN required (`needs_pin: true`) |
| 403 | Origin mismatch (CSRF protection) |
| 404 | Resource not found |
| 408 | Request timeout (upload exceeded 300s) |
| 409 | Conflict (duplicate name) |
| 429 | Rate limited (`retry_after` field indicates wait time in seconds) |
| 500 | Server error |
| 507 | Insufficient storage (disk full) |
