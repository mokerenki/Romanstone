# Aether

## Autonomous Agent Platform for Regulated Enterprises

**Phase 0**: ✅ Complete — Reactive agent loop, ModelRouter, tools, streaming API  
**Phase 1**: 🏗️ Scaffolded — Heartbeat daemon, Cognee memory, React dashboard  
**Phase 2**: 🏗️ Scaffolded — Firecracker sandboxes, desktop GUI, Kubernetes

---

## Project Structure

```
aether/
├── backend/
│   ├── app/
│   │   ├── api/           # REST + WebSocket endpoints
│   │   ├── core/          # Config, ModelRouter, Security
│   │   ├── agents/        # Planner, Executor, Verifier, DesktopAgent
│   │   ├── heartbeat/     # Daemon, Probes, Policy Engine
│   │   ├── memory/        # Cognee, Graph, Legal Schema, Temporal, Ingest
│   │   ├── sandbox/       # K8s Manager, gRPC
│   │   └── tools/         # ToolRegistry
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/              # React/Next.js dashboard
├── k8s/                   # Kubernetes manifests
├── docker/                # Sandbox Dockerfiles
├── docker-compose.yml     # Local dev stack
└── README.md
```

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 2. Start infrastructure
docker-compose up -d postgres qdrant redis

# 3. Run backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# 4. Run frontend
cd frontend
npm install
npm run dev
```

## Phase Status

| Phase | Status | Key Deliverables |
|-------|--------|-----------------|
| 0 | ✅ Complete | Agent loop, tools, streaming, tests |
| 1 | 🏗️ Scaffolded | Heartbeat, memory, dashboard |
| 2 | 🏗️ Scaffolded | Sandboxes, desktop GUI, RBAC |

## Contributing

See `CONTRIBUTING.md` (Phase 1).
