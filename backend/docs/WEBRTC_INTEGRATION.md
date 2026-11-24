# EyeSight backend WebRTC integration

This document defines the backend contract for Member 1's mobile live-camera client.

## Architecture

- Mobile app: WebRTC offerer and camera/video sender.
- Backend: FastAPI WebSocket signaling endpoint and aiortc peer receiver.
- Member 2: existing `save_camera_frame` quality selection and frame storage.
- Dashboard: authenticated preview WebSocket receiving JPEG binary frames.
- Session identity: every stream is bound to the authenticated user's active `sessions.session_id`.

The backend now exposes authenticated device registration and capture-session lifecycle endpoints. The session starts in `starting` state and becomes `active` only after the WebRTC peer reaches `connected`. The mobile app must call these endpoints before opening the signaling socket.

## Install and configure

From `backend/`:

```powershell
python -m pip install -r requirements.txt
```

Set these backend environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `WEBRTC_STUN_URL` | `stun:stun.l.google.com:19302` | STUN server |
| `WEBRTC_TURN_URL` | unset | TURN server URL; required when direct ICE paths are blocked |
| `WEBRTC_TURN_USERNAME` | unset | TURN username |
| `WEBRTC_TURN_CREDENTIAL` | unset | TURN credential |
| `WEBRTC_MAX_ACTIVE_STREAMS` | `8` | Maximum peer connections per backend process |
| `WEBRTC_FRAME_SAMPLE_INTERVAL_SECONDS` | `1.0` | Minimum interval between frame-history samples |
| `WEBRTC_MAX_FRAME_WIDTH` | `1280` | Maximum preview/storage width |
| `WEBRTC_JPEG_QUALITY` | `85` | JPEG encoding quality |
| `WEBRTC_MAX_SIGNAL_MESSAGE_BYTES` | `65536` | Maximum signaling message size |
| `WEBRTC_OFFER_TIMEOUT_SECONDS` | `20` | Timeout for the first SDP offer |\n| `SESSION_FRAME_RETENTION_SECONDS` | `86400` | Session frame-history retention in seconds |

STUN assists network discovery but does not relay media. TURN is needed on networks where direct ICE connectivity is blocked. Store TURN credentials in backend deployment secrets, not mobile source code.

## Device and capture-session REST contract

All three endpoints below require the access token returned by `POST /auth/login`:

```http
Authorization: Bearer ACCESS_TOKEN
```

1. Register the installation:

```http
POST /api/devices/register
Content-Type: application/json

{
  "installation_id": "UUID_FROM_SECURE_STORE",
  "platform": "android",
  "device_name": "EyeSight phone",
  "app_version": "1.0.0"
}
```

The response contains `device_id`. A device installation is associated with one user; a different account cannot claim it.

2. Create a capture session only after the user has explicitly consented:

```http
POST /api/sessions
Content-Type: application/json

{
  "device_id": 1,
  "language_code": "en",
  "consent": true,
  "consent_version": "1.0"
}
```

The response contains `session_id`. Its initial status is `starting`; the backend changes it to `active` when the WebRTC connection is established. The default frame-history retention is 86400 seconds and can be configured with `SESSION_FRAME_RETENTION_SECONDS`.

3. After sending the WebRTC `stop` message and closing the signaling socket, end the session:

```http
POST /api/sessions/SESSION_ID/end
Authorization: Bearer ACCESS_TOKEN
```

Ending a session also closes the backend peer connection. Session creation rejects missing consent and devices owned by another user.

## Mobile signaling contract

Connect with the access token returned by `POST /auth/login`:

```text
wss://YOUR_API_HOST/ws/webrtc/SESSION_ID?token=ACCESS_TOKEN
```

Use `ws://` only for local development. Deploy with TLS and redact query strings from access logs because the query contains a bearer token.

1. Create an `RTCPeerConnection`, add the camera video track, create an offer, and set it as the local description.
2. Send this JSON text as the first WebSocket message:

```json
{"type":"offer","sdp":"<complete SDP offer>"}
```

3. The backend returns:

```json
{"type":"answer","sdp":"<complete SDP answer>"}
```

4. Set the answer as the mobile peer's remote description.
5. If the mobile library emits trickled ICE candidates, send:

```json
{"type":"ice-candidate","candidate":"candidate:...","sdpMid":"0","sdpMLineIndex":0}
```

For end-of-candidates:

```json
{"type":"ice-candidate","candidate":""}
```

6. Optional keepalive:

```json
{"type":"heartbeat"}
```

The backend replies with `{"type":"heartbeat-ack"}`.

7. Stop explicitly:

```json
{"type":"stop"}
```

Closing the WebSocket also closes the peer connection. The mobile client should additionally call `POST /api/sessions/SESSION_ID/end` so the database session is marked ended and the backend media resources are released.

## Server signaling responses

- `answer`: SDP answer to set as remote description on mobile.
- `stream-state`: connection lifecycle notification.
- `ice-candidate-accepted`: server accepted a trickled candidate.
- `error`: an error with a stable `code`.

aiortc gathers its local ICE candidates during `setLocalDescription`; the returned SDP answer includes the gathered candidates.

## Video decoding and Member 2 integration

The backend receives the remote video track through aiortc, decodes each frame using PyAV, converts it to OpenCV BGR, scales overly wide frames, and JPEG-encodes the preview.

At most one history sample per configured interval is passed to:

```python
save_camera_frame(session_id, jpeg_bytes, select_for_history=True)
```

Member 2's existing function performs image validation, quality evaluation, duplicate detection, retention checks, MySQL persistence, and image-file storage. Accepted frames are recorded with processing status `pending` for the existing OCR/object-detection/embedding pipeline.

The real-time receive loop does not run the synchronous ML pipeline because inference would stall media reception. Run the existing pipeline for a session using:

```powershell
python -m multimedia.frame_pipeline --session SESSION_ID
```

For deployment, run this command as a supervised worker for pending frames. Do not run two workers against the same claimed frame.

## Dashboard preview

Connect the dashboard to:

```text
wss://YOUR_API_HOST/ws/webrtc/SESSION_ID/watch?token=ACCESS_TOKEN
```

The first message is JSON text:

```json
{"type":"preview-ready","session_id":123,"format":"jpeg-binary"}
```

Subsequent messages are binary JPEG frames. Convert each received Blob/ArrayBuffer into an image for the dashboard.

Status endpoint:

```http
GET /api/webrtc/sessions/SESSION_ID/status?token=ACCESS_TOKEN
```

The response includes session/stream state, ICE/peer state, received/saved frame counters, and the latest saved frame ID.

## Session and security rules

- Access tokens are verified with the existing JWT verifier.
- The stream attaches only to an active, unexpired session owned by the authenticated user.
- Only one active peer is allowed per session.
- The server enforces a configurable per-process active-stream limit.
- WebSocket disconnect, explicit stop, failed ICE, and failed peer state trigger peer cleanup.
- Use HTTPS/WSS and TURN credentials in environment secrets in production.
- Peer state is in memory and process-local. Use one signaling worker per instance or add shared routing before horizontal scaling.

## Verification boundaries

Offline contract tests validate offer type, SDP presence, and signaling size limits. Full media negotiation requires aiortc/PyAV installed. End-to-end verification requires an active MySQL session, reachable STUN/TURN configuration, and a real or simulated WebRTC sender. Member 1's physical-device test remains the final mobile integration check.
