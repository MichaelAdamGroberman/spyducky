# Continuous Authentication Validation v2

**Status:** Architecture phase. Private repo.

## Overview

Camera-based continuous authentication validation for enterprise deployments. Confirms the authenticated user is still present and in control — watches for unauthorized people, shoulder-surfing, phone-in-hand, gaze-off-screen, and exposed confidential data, then locks, blacks out, hides, or alerts.

**v2 shift:** Centralized inference on NVIDIA H100 GPU. Multi-stream real-time processing at ~30 FPS with 100-200 ms latency. WebRTC video ingress, WebSocket control plane. Multi-tenant capable with logical isolation + MIG carve-out for regulated tiers.

## Architecture

- **Inference:** NVIDIA Triton (YOLOv8, HRNet, HeadPoseNet, DeepSORT)
- **Video transport:** WebRTC (H.264, NVDEC decode on GPU)
- **Control plane:** WebSocket (JSON session lifecycle + commands)
- **Batching:** Cross-session dynamic batching on H100 (5 ms queue delay ceiling)
- **State:** Redis (hot) + Postgres (durable audit)
- **Multi-tenancy:** Logical isolation (default) + MIG carve-out (premium)
- **HA:** Active/standby H100 with hot model cache

See `ARCHITECTURE.md` for full design, ADRs, risks, and 20-task engineering handoff.

## Modules (Skeleton)

```
conauth/
├── ARCHITECTURE.md         # Full design document
├── README.md              # This file
├── pyproject.toml         # Dependencies + build config
├── docker-compose.yml     # Local dev stack (Triton, Redis, Postgres)
├── conauth/
│   ├── __init__.py
│   ├── gateway.py         # FastAPI WebSocket + WebRTC signaling
│   ├── ingest.py          # aiortc + NVDEC decode
│   ├── inference.py       # Triton gRPC client
│   ├── tracking.py        # DeepSORT worker
│   ├── risk.py            # Risk scorer
│   ├── dispatch.py        # Command dispatch
│   ├── state/
│   │   ├── redis.py       # Redis operations
│   │   └── postgres.py    # Postgres operations
│   ├── protocol.py        # Pydantic models (shared with clients)
│   └── main.py            # Uvicorn entrypoint
├── tests/
│   ├── test_protocol.py
│   ├── test_gateway.py
│   ├── test_ingest.py
│   └── ...
└── ops/
    ├── docker-compose.yml
    └── failover/
```

## Getting Started (WIP)

```bash
# Install dependencies
pip install -e ".[dev]"

# Stand up local Triton + Redis + Postgres
docker-compose -f ops/docker-compose.yml up -d

# Run tests
pytest

# Start gateway server (on localhost:8000)
uvicorn conauth.main:app --reload
```

## Key Decisions

- **ADR-1:** Triton Inference Server (not custom asyncio + ONNX) for dynamic batching
- **ADR-2:** WebRTC for video (not WebSocket) for real-time quality
- **ADR-3:** H.264 + NVDEC (GPU-resident decode)
- **ADR-4:** Cross-session batching with 5 ms queue delay
- **ADR-5:** Bounded frame-drop policy (oldest non-keyframe)
- **ADR-6:** Risk scorer as pure function over Redis Streams
- **ADR-7:** Logical isolation (default) + MIG (premium) multi-tenancy
- **ADR-8:** Active/standby H100 for HA

See `ARCHITECTURE.md` for full rationale.

## Risks & Mitigations

- **H100 single point of failure** → Active/standby with hot cache
- **NVDEC saturation** → Admission control at ~85% utilization
- **Cross-session batch poisoning** → Per-tenant rate limit + circuit-breaker
- **Audit log gaps** → Write-ahead to Redis Stream with replay worker

See `ARCHITECTURE.md` Risk Register for full list.

## Next Steps

1. ✅ Architecture approved
2. ⏳ Confirm target repo location (~/Projects/conauth/ or ~/RedAI/cav/)
3. ⏳ Stand up cav-gateway FastAPI + WebSocket protocol
4. ⏳ Integrate aiortc + stub NVDEC
5. ⏳ Wire to Triton with TensorRT placeholders
6. ⏳ Bench cross-session batching
7. ⏳ Active/standby failover
8. ⏳ E2E test: client → H.264 → COMMAND → ack

## License

MIT License — see `LICENSE` file for details.

---

**Last updated:** 2026-06-06  
**Author:** Michael Groberman
