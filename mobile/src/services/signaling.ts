
import { API_BASE_URL, getAccessToken } from './auth';
import { RTCPeerConnection } from 'react-native-webrtc';

import {
    createWebRTCOffer,
    applyWebRTCAnswer,
    observeLocalIceCandidates,
} from './webrtc';

export async function connectWebRTCSignaling(
    sessionId: number,
    peerConnection: RTCPeerConnection
): Promise<WebSocket> {

    const token = await getAccessToken();

    if (!token) {
        throw new Error('Please log in first.');
    }

    // Change http:// to ws:// for WebSocket.
    const wsBaseUrl = API_BASE_URL.replace(/^http/, 'ws');

    const websocketUrl =
        `${wsBaseUrl}/ws/webrtc/${sessionId}` +
        `?token=${encodeURIComponent(token)}`;

    // Create the offer before opening the socket.
    const offer = await createWebRTCOffer(peerConnection);

    return new Promise<WebSocket>((resolve, reject) => {
        const socket = new WebSocket(websocketUrl);
        let offerSent = false;
        let settled = false;

        const pendingCandidates: object[] = [];

        const fail = (message: string) => {
            if (settled) return;

            settled = true;
            clearTimeout(connectionTimeout);
            socket.close();

            reject(new Error(message));
        };

        // Stop waiting if the backend does not answer
        const connectionTimeout = setTimeout(() => {
            fail('WebRTC connection timed out after 25 seconds');
        }, 25000);
        observeLocalIceCandidates(peerConnection, (candidate) => {
            const message = {
                type: 'ice-candidate',
                candidate,
            };

            if (socket.readyState === WebSocket.OPEN && offerSent) {
                socket.send(JSON.stringify(message));
            } else {
                pendingCandidates.push(message);
            }
        });

        socket.onopen = () => {
            console.log('EyeSight signaling WebSocket connected');

            socket.send(JSON.stringify({
                type: 'offer',
                sdp: peerConnection.localDescription?.sdp ?? offer.sdp,
            }));

            offerSent = true;

            for (const message of pendingCandidates) {
                socket.send(JSON.stringify(message));
            }

            pendingCandidates.length = 0;
        };

        socket.onmessage = async (event) => {
            try {
                const message = JSON.parse(String(event.data));

                if (message.type === 'answer') {
                    await applyWebRTCAnswer(
                        peerConnection,
                        message.sdp
                    );

                    console.log('Backend WebRTC answer received');

                    if (!settled) {
                        settled = true;
                        clearTimeout(connectionTimeout);
                        resolve(socket);
                    }
                }

                if (message.type === 'stream-state') {
                    console.log('Backend stream state:', message.state);
                }

                if (message.type === 'error') {
                    console.error('Backend signaling error:', message);
                    fail(message.code || 'WebRTC signaling failed');
                }

            } catch (error) {
                console.error('WebRTC signaling message error:', error);
                fail('Could not process backend signaling response');
            }
        };

        socket.onerror = () => {
            fail('WebRTC WebSocket connection failed');
        };

        socket.onclose = () => {
            console.log('EyeSight signaling WebSocket closed');

            if (!settled) {
                fail('WebRTC signaling closed before receiving an answer');
            }
        };
    });
}
