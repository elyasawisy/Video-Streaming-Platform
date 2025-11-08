import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');

// Test configuration
export const options = {
    scenarios: {
        // Scenario 1: Steady viewer load
        steady_viewers: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '1m', target: 100 },  // Ramp up to 100 viewers
                { duration: '3m', target: 100 },  // Stay at 100 viewers
                { duration: '1m', target: 0 },    // Ramp down to 0
            ],
        },
        // Scenario 2: Viewer spike
        viewer_spike: {
            executor: 'ramping-vus',
            startTime: '5m',  // Start after steady_viewers
            startVUs: 0,
            stages: [
                { duration: '30s', target: 500 },  // Quick ramp up to 500
                { duration: '1m', target: 500 },   // Hold at 500
                { duration: '30s', target: 0 },    // Quick ramp down
            ],
        },
    },
    thresholds: {
        'errors': ['rate<0.1'],  // Error rate should be below 10%
        'http_req_duration': ['p(95)<2000'],  // 95% of requests should be below 2s
    },
};

// Simulated video manifest
const qualities = [
    { resolution: '480p', bitrate: 1000000 },
    { resolution: '720p', bitrate: 2500000 },
    { resolution: '1080p', bitrate: 5000000 },
];

// Video segment duration in seconds
const SEGMENT_DURATION = 10;

// Viewer session simulation
export default function() {
    // 1. Get video manifest (playlist)
    const manifestRes = http.get('http://localhost:8003/api/v1/videos/test123/manifest');
    check(manifestRes, {
        'manifest loaded': (r) => r.status === 200,
    });
    
    if (manifestRes.status !== 200) {
        errorRate.add(1);
        return;
    }

    // 2. Select quality level (simulate adaptive bitrate)
    const quality = qualities[Math.floor(Math.random() * qualities.length)];
    
    // 3. Simulate video playback by requesting segments
    const totalSegments = 6;  // 1 minute of playback
    
    for (let segment = 0; segment < totalSegments; segment++) {
        const segmentRes = http.get(
            `http://localhost:8003/api/v1/videos/test123/segment/${quality.resolution}/${segment}`
        );
        
        check(segmentRes, {
            'segment loaded': (r) => r.status === 200,
            'correct content type': (r) => r.headers['Content-Type'] === 'video/mp4',
        });
        
        if (segmentRes.status !== 200) {
            errorRate.add(1);
        }
        
        // Simulate segment playback before requesting next segment
        sleep(SEGMENT_DURATION);
    }
    
    // 4. Report viewer metrics
    // These will be available in k6's output
    check(null, {
        'viewer session completed': true,
    });
}