# Relay changes needed for Foxtel Go plugin

The plugin uses the existing relay server (same IPs/port as Kayo: LAN 5004, VPS 5006).
The following new routes need to be added to the relay.

## New routes

### POST /set_foxtel_token
Store the Foxtel DAZN JWT so subsequent /foxtel/* calls can use it.

Request body:
```json
{"token": "eyJ..."}
```

Response:
```json
{"status": "ok"}
```

The relay should store this separately from the Kayo token (as `foxtel_token`).

---

### GET /foxtel/live
Look up the current live event asset ID for a Foxtel channel code, then return
stream info (same format as /token).

Query params:
- `channel` — Foxtel channel code, e.g. "F1S", "UKT", "FSP1"

The relay should:
1. Query the DAZN EPG endpoint with the Foxtel DAZN token to find the current
   event on that channel.
2. Get the event's AssetId.
3. Call DAZN Playback API with that asset ID.
4. Return stream details.

Response (same format as /foxtel/token):
```json
{
  "status":      "success",
  "asset_id":    "abc123xyz",
  "license_url": "https://widevine-proxy...",
  "cdn_name":    "hdntl",
  "cdn_val":     "...",
  "wv_secure":   false
}
```

---

### GET /foxtel/token
Get stream details for a specific asset ID using the stored Foxtel DAZN token.
This is the equivalent of the existing /token route but uses foxtel_token.

Query params:
- `id`      — DAZN asset ID
- `quality` — "4k", "hd", "sd"

Response:
```json
{
  "status":      "success",
  "license_url": "https://widevine-proxy...",
  "cdn_name":    "hdntl",
  "cdn_val":     "...",
  "wv_secure":   false
}
```

---

### GET /foxtel/mpd_kodi
Return the MPEG-DASH manifest for Kodi, proxied through the relay (so the relay
can inject the right CDN auth cookie on each segment request).

Query params:
- `id`       — DAZN asset ID
- `quality`  — "4k", "hd", "sd"
- `avc_only` — "1" for live streams (strips HEVC representations)

This is the equivalent of the existing /mpd_kodi route but for Foxtel assets.

---

## DAZN EPG endpoint (for /foxtel/live)

```
GET https://epg.discovery.indazn.com/jp/v6/Epg
    ?Date=YYYY-MM-DD
    &Evaluate=5
    &Brand=foxtelgnc
Authorization: Bearer {foxtel_dazn_token}
```

The response contains a list of events. Each event has:
- `AssetId` — DAZN playback asset ID (pass to Playback API)
- `StartTime` / `EndTime`
- `LinearProvider` or similar field indicating the channel
- `Title`

Match the `channel` param (e.g. "F1S") against the LinearProvider/channel field
to find the currently-live event, then use its AssetId.

## Note on channel codes

Channel codes in i.mjh.nz/Foxtel/app.json (e.g. "F1S", "UKT", "FSP1") may not
exactly match the DAZN EPG LinearProvider values. The relay will need to build
a mapping after inspecting the EPG response. Alternatively, the relay can return
the first event that is currently live for any channel and let the user pick, or
accept the DAZN LinearProvider directly as the `channel` param once the mapping
is known.
