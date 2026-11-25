
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

    let socket: WebSocket;
    let offerSent = false;
    const pendingCandidates: string[] = [];

    // Setting the local description can emit candidates before the socket opens.
    const stopObserving = observeLocalIceCandidates(peerConnection, (candidate) => {
        const message = JSON.stringify({ type: 'ice-candidate', ...candidate });

        if (!offerSent) {
            pendingCandidates.push(message);
        } else if (socket.readyState === WebSocket.OPEN) {
            socket.send(message);
        }
    });

    let offerSdp: string;
    try {
        const offer = await createWebRTCOffer(peerConnection);
        offerSdp = offer.sdp;
        socket = new WebSocket(websocketUrl);
    } catch (error) {
        stopObserving();
        throw error;
    }

    return new Promise<WebSocket>((resolve, reject) => {
        let settled = false;

        const fail = (message: string) => {
            if (settled) return;

            settled = true;
            clearTimeout(connectionTimeout);
            stopObserving();
            socket.close();

            reject(new Error(message));
        };

        // Stop waiting if the backend does not answer
        const connectionTimeout = setTimeout(() => {
            fail('WebRTC connection timed out after 25 seconds');
        }, 25000);

        socket.onopen = () => {
            console.log('EyeSight signaling WebSocket connected');

            socket.send(JSON.stringify({
                type: 'offer',
                sdp: peerConnection.localDescription?.sdp ?? offerSdp,
            }));

            for (const message of pendingCandidates) {
                socket.send(message);
            }

            pendingCandidates.length = 0;
            offerSent = true;
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
            stopObserving();
            console.log('EyeSight signaling WebSocket closed');

            if (!settled) {
                fail('WebRTC signaling closed before receiving an answer');
            }
        };
    });
}
