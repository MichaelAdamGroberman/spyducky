# Continuous Authentication Validation v2 — Centralized H100 Architecture

## Overview

Camera-based continuous authentication validation for enterprise deployments. Centralized H100 GPU handles all inference (YOLOv8 detection, HRNet pose, HeadPoseNet gaze, DeepSORT tracking) in real-time across multiple concurrent camera streams. Single authoritative risk engine, WebRTC video ingress, WebSocket control plane.

**Key insight:** Centralized inference on H100 eliminates heterogeneous sensor calibration complexity. One calibration curve for all camera types. H100 batching across tenants provides economic multi-tenancy.

---

## Top 3 Risks

1. **Single H100 = single point of failure.** Mitigated by active/standby with hot model cache (ADR-8).
2. **Cross-session batching trades latency for throughput.** Knob: 5 ms queue delay (ADR-4). Tunable per-tenant SLO.
3. **WebSocket video transport has head-of-line blocking.** Recommend WebRTC (ADR-2); WebSocket fallback acceptable for LAN-only.

---

## Architecture Decisions (ADRs)

### ADR-1: NVIDIA Triton Inference Server (not custom asyncio + ONNX)
- **Decision**: YOLOv8, HRNet, HeadPoseNet as separate Triton models with TensorRT backends and dynamic batching.
- **Why**: Proven batching, multi-model concurrency, no GIL, built-in metrics.
- **Trade-off**: Operational dependency on Triton; less flexibility for exotic pre/post-processing.

### ADR-2: WebRTC for video ingress, WebSocket for control (deviation from "WebSocket only")
- **Decision**: Use `aiortc` for WebRTC DTLS/SRTP H.264 uplink; WebSocket JSON for session lifecycle and commands.
- **Why**: Native congestion control, hardware-accelerated decode, sub-100ms transport, graceful packet loss.
- **Trade-off**: Requires STUN/TURN (coturn). If "WebSocket video" is non-negotiable, accept latency degradation and lean on frame-drop policy (ADR-5).

### ADR-3: H.264 decode via NVDEC (GPU-resident)
- **Decision**: Clients send H.264 baseline/main; server decodes on H100 NVDEC units (5-7 per card) directly to GPU NV12.
- **Why**: H.264 is 2-8 Mbps; raw NV12 is 750 Mbps. NVDEC is the capacity ceiling, not compute.
- **Trade-off**: Hard ceiling ~40-56 concurrent 1080p30 streams per H100 (NVDEC-limited). Downscale to 720p to push toward 80.

### ADR-4: Cross-session dynamic batching with 5 ms queue-delay ceiling
- **Decision**: Triton batches frames from any session; `max_queue_delay_microseconds=5000`, `preferred_batch_size=[8,16,32]`.
- **Why**: Maximizes GPU utilization; 5 ms wait still meets 100-200 ms end-to-end SLO.
- **Trade-off**: Tail latency dominated by batch-wait. Tunable per-tenant.

### ADR-5: Bounded per-session ring buffer with explicit frame-drop policy
- **Decision**: 8-frame in-process ring per session. Drop oldest non-keyframe when full; force IDR request if only keyframes remain.
- **Why**: Bounded memory (~1.6 MB per session). Predictable degradation under overload.
- **Trade-off**: Graceful frame loss. Audit log records every drop.

### ADR-6: Risk engine as pure-function service over Redis Streams
- **Decision**: Risk scorer `(window, policy) -> (css, decision)` is deterministic and replayable. Inference events stream to Redis; workers consume and emit decisions.
- **Why**: Replayable from audit log; A/B-testable; one calibration source.
- **Trade-off**: Single risk-engine calibration to maintain (v1 benefit of per-sensor calibration is traded away).

### ADR-7: Multi-tenancy via logical isolation (default) + MIG carve-out (premium)
- **Decision**: Default tier: shared Triton, isolation via tenant_id routing and rate limits. Premium: dedicated MIG slice with own Triton instance.
- **Why**: Logical isolation is cost-effective; MIG provides hard isolation for regulated customers.
- **Trade-off**: Two operational profiles.

### ADR-8: Active/standby H100 with hot model cache
- **Decision**: Two H100 nodes, active handles requests, standby runs Triton with all engines loaded. On active failure, drain and reroute; degradation mode if both fail.
- **Why**: Cold-start Triton takes 30-90s; unacceptable. Standby responds within 2-5s.
- **Trade-off**: 2x GPU cost for HA.

---

## Module Boundaries

| Module | Role | Interface |
|---|---|---|
| `cav-gateway` | Session lifecycle, JWT auth, WebRTC signaling | `POST /v2/sessions`, `WS /v2/control/{session_id}` |
| `cav-ingest` | WebRTC + NVDEC decode to GPU tensors | aiortc peers, internal tensor queue |
| `cav-infer` | Triton (YOLOv8, HRNet, HeadPoseNet) | gRPC from cav-ingest |
| `cav-track` | DeepSORT Kalman + Hungarian tracking | CPU worker pool, per-session state |
| `cav-risk` | Risk scoring engine | Redis Streams consumer, pure function |
| `cav-dispatch` | Command push + audit write | WebSocket + Postgres |
| State: Redis | Hot state (streams, per-session meta) | 24h TTL |
| State: Postgres | Audit log, tenant config, risk-engine versions | Row-level security by tenant_id |

---

## Data Flow (Happy Path)

```
Client (phone/webcam) 
  → WebRTC H.264 frames → cav-ingest 
  → NVDEC decode → GPU tensor 
  → Triton gRPC (yolov8 + hrnet + headposenet, cross-session batch) 
  → cav-track (DeepSORT per-session) 
  → Redis Stream `risk:session:{id}` 
  → cav-risk (score window, apply policy) 
  → if decision changed: cav-dispatch (push WS COMMAND) 
  → Postgres audit
```

---

## Scaling Characteristics (Empirical Pending Benchmarks)

| Metric | Estimate | Notes |
|---|---|---|
| NVDEC capacity | 40–56 concurrent 1080p30 H.264 | Hard ceiling |
| Compute capacity (YOLOv8 FP16) | Not binding at 30 FPS/stream | Batch size 32 sufficient |
| DeepSORT (CPU) | 150 sessions per 16-core node | Scale horizontally |
| End-to-end p50 latency | ~120 ms | breakdown: 30 net + 10 decode + 8 batch + 35 inference + 10 risk + 30 net |
| End-to-end p99 latency | ~200 ms | dominated by batch-delay + retransmit |

**Rule of thumb:** ~40 concurrent 1080p30 cameras per H100 (NVDEC-bound). Downscale to 720p to push toward 80.

---

## Failover

Active H100 dies → gateway health check fails → drain in-flight → reroute new sessions to standby (warm, <2s) → existing sessions reconnect. If both H100s die, dispatcher broadcasts `DEGRADED` signal and clients fall back to conservative policy (e.g., lock on >X seconds without heartbeat).

---

## Multi-Tenancy

**Logical isolation (default):**
- Shared Triton, frames batched cross-tenant
- Per-tenant rate limits at ingress
- Per-tenant Redis keyspaces
- Row-level security in Postgres (tenant_id column)

**MIG isolation (premium):**
- Dedicated GPU slice (e.g., 1g.10gb or 2g.20gb)
- Separate Triton instance per slice
- Hard isolation, auditable

---

## Protocol: WebSocket Control Plane

Two channels per session:
1. **Media (WebRTC)** — H.264 uplink
2. **Control (WebSocket, JSON)**

| Direction | Type | Payload |
|---|---|---|
| C→S | `HELLO` | `{session_id, client_caps: {...}}` |
| S→C | `READY` | `{session_id, policy_version, heartbeat_interval_ms}` |
| C→S | `HEARTBEAT` | `{ts}` (every 1 s) |
| S→C | `COMMAND` | `{command_id, action: OK\|WARN\|LOCK\|BLACKOUT\|ALERT, expires_ms}` |
| C→S | `COMMAND_ACK` | `{command_id, applied: bool}` |
| S→C | `DEGRADED` | `{since_ts, fallback_policy}` |
| S→C | `BYE` | `{reason}` |

Session lifecycle: `HELLO → READY → steady state → BYE`. Heartbeat timeout (3 misses) triggers `DEGRADED`.

---

## Key Risks & Mitigations

| Risk | Detection | Mitigation |
|---|---|---|
| H100 driver hang | Triton gRPC health + `nvidia-smi` | Active/standby failover; auto-restart on Xid |
| NVDEC saturation before compute | Per-stream decode latency | Admission control: reject sessions when NVDEC > 85% |
| Cross-session batch poisoning | Per-tenant p99 latency | Per-tenant rate limit; circuit-breaker |
| Risk-engine version drift | Track `risk_engine_version` per decision | Pin version per session at HELLO; never hot-swap |
| Multi-tenant data leak | Triton isolation review | MIG for regulated tenants |
| WebSocket head-of-line blocking | Client-side gap detection | Prefer WebRTC; aggressive drop policy |
| Replay attack (video re-stream) | Liveness signal (gaze entropy, micro-motion) | Challenge-response on `REQUEST_KEYFRAME` |
| Audit log gaps (Postgres outage) | Pending audit in Redis Stream | Async drain with monotonic seq |

---

## Recommended First Steps

1. Confirm repo location (`~/Projects/conauth/` vs. `~/RedAI/cav/`).
2. Stand up `cav-gateway` FastAPI scaffold + test WebSocket control protocol.
3. Integrate `aiortc` + stub NVDEC decode.
4. Wire to Triton with TensorRT placeholders.
5. Bench cross-session batching with synthetic H.264 load.
6. Active/standby failover controller.
7. Full e2e test: client connects, sends H.264, receives COMMAND, acks.

---

**Status:** Architecture approved 2026-06-06. Ready for engineering handoff (20-task list available in full design doc).
