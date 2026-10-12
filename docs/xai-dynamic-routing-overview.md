# Project Overview

**Title:** Explainable AI-Based Dynamic Routing Recommendation System for Intelligent and Secure Computer Networks

**Source:** Network Project Titles — item 4 (page 1), field details (page 5)

**Layer focus:** Network layer (Layer 3) routing, with QoS and security metrics used as path-selection features.

---

## 1. Problem

Traditional protocols such as OSPF and RIP choose paths from a small set of static metrics (hop count or configured link cost). That is a poor fit for networks whose delay, congestion, loss, energy use, and threat level change over time.

Those protocols also cannot jointly optimize several Quality of Service (QoS) and security factors, and they do not explain *why* a path was chosen. Operators then struggle to trust, audit, or debug routing.

This project builds an **Explainable AI (XAI)** routing recommender that:

1. Predicts a suitable path from live (or simulated) network features.
2. Explains each recommendation in terms humans can check (feature importance).

---

## 2. Goal

Recommend an **optimal route** under changing conditions, using both **QoS** and **security** signals, and attach a **transparent explanation** (SHAP and/or LIME) to every decision.

---

## 3. AI approach

| Role | Method |
|------|--------|
| Route recommendation | Supervised / ranking model trained on topology + link/path features (exact architecture to be chosen during implementation) |
| Explanation | **SHAP** (SHapley Additive Explanations) and **LIME** (Local Interpretable Model-Agnostic Explanations) |

SHAP/LIME sit on top of the predictor: they do not replace OSPF/RIP in the kernel; they justify *which features* pushed the model toward a given path.

---

## 4. Inputs (features)

Use as path or link attributes (subset as data allows):

- Delay (latency)
- Available bandwidth
- Congestion level
- Packet loss rate
- Energy use of intermediate nodes
- Security risk score
- Link utilization
- Queue length
- Hop count
- Historical traffic statistics
- Link reliability
- Topology (nodes, edges, connectivity)

---

## 5. Intended contributions

- Multi-criteria routing engine: QoS **and** security, not hop count alone.
- XAI on every recommendation (feature importance / local explanation).
- Framework that can refresh recommendations as metrics change.
- Comparison with **OSPF**, **RIP**, and existing AI routing (accuracy, delay, loss, interpretability).
- Better performance **without** treating the model as a black box.

---

## 6. Datasets and testbeds

| Source | Use |
|--------|-----|
| Internet Topology Zoo | Real / research topologies |
| SNDlib | Network design / traffic instances |
| CAIDA | Internet traffic characteristics |
| NS-3 or OMNeT++ | Controlled routing traces |
| Mininet, GNS3, or Cisco Packet Tracer | Custom runs under load and (lab) attack/failure scenarios |

Custom traces should vary traffic and **security-related events** (e.g. degraded or risky links) so the security-risk feature is meaningful. Work stays in simulation/lab; no exploit or attack-procedure content.

---

## 7. Research gap

AI routing papers often maximize throughput or delay and stop there: the model is opaque. Classical IGPs stay on fixed metrics and do not adapt well. Few systems combine **dynamic path choice**, **security awareness**, and **explanations** in one pipeline.

---

## 8. Novelty

An XAI routing recommender that jointly considers delay, congestion, loss, energy, and security risk, and produces **interpretable** SHAP/LIME explanations per decision—linking intelligent routing with trustworthy AI.

---

## 9. Suggested system flow

```
Topology + live/sim metrics
        ↓
Feature builder (per candidate path / next hop)
        ↓
Route recommender (learned model)
        ↓
Selected path + scores
        ↓
SHAP / LIME explanation (which features mattered)
        ↓
Operator view / comparison vs OSPF–RIP
```

**Network idea (short):** forwarding still happens hop by hop; the AI **recommends** which path (or next hop) to prefer given current QoS and risk, instead of a single static cost.

---

## 10. Evaluation (planned)

Compare against OSPF/RIP and a non-explained AI baseline on:

- End-to-end delay, packet loss, congestion / utilization
- Path quality under changing load
- Security-aware avoidance of high-risk links (lab scenarios)
- Explanation quality (feature attributions that match the metrics used)

---

## 11. Out of scope (unless later expanded)

- Replacing production IGP implementations on live campus/ISP gear
- Offensive security, exploit PoCs, or unauthorized scanning
- Black-box models with no explanation path

---

## 12. Proposed folder layout

Capstone code lives under `projects/xai-dynamic-routing/`. Course labs stay under `labs/`. Skill files stay under `.cursor/skills/computer-networks/`.

```
ComputerNetworks/
├── README.md
├── docs/
│   ├── Network Project Titles.pdf
│   ├── xai-dynamic-routing-overview.md
│   └── xai-dynamic-routing-phase-plan.md
├── labs/                              # CN lab programs (CRC, sockets, …)
├── reports/                           # write-ups only if requested
└── projects/
    └── xai-dynamic-routing/
        ├── README.md                  # aim, how to run, ports
        ├── requirements.txt
        ├── configs/                   # topology size, model hyperparams, ports
        ├── data/
        │   ├── raw/                   # Topology Zoo, SNDlib, CAIDA dumps (gitignored if large)
        │   ├── processed/             # feature tables (CSV/Parquet)
        │   └── samples/               # small fixtures for demos and tests
        ├── src/
        │   ├── topology/              # graph load/build
        │   ├── features/              # delay, loss, risk, utilization, …
        │   ├── routing/
        │   │   ├── baselines.py       # OSPF-like SPF, RIP-like hop count
        │   │   └── recommender.py     # learned path / next-hop scores
        │   ├── xai/                   # SHAP, LIME wrappers
        │   ├── simulate/              # Mininet/NS-3 adapters or Python graph sim
        │   └── evaluate/              # metrics vs baselines
        ├── notebooks/                 # EDA and explanation plots (optional)
        ├── models/                    # saved weights (gitignored except tiny demo)
        ├── outputs/
        │   ├── routes/                # recommended paths
        │   ├── explanations/          # SHAP/LIME artifacts
        │   └── figures/
        ├── tests/
        └── scripts/                   # train, infer, compare_ospf_rip
```

Default bind for any local service: `127.0.0.1`. Document the port in `projects/xai-dynamic-routing/README.md`.

---

## 13. Phase plan and dependencies

Canonical plan: [xai-dynamic-routing-phase-plan.md](xai-dynamic-routing-phase-plan.md).  
Live status (update before commit): [phase-execution-status.md](phase-execution-status.md).  
What you run: [execution-plan.md](execution-plan.md).  
Methods and results reference: [xai-dynamic-routing-methods.md](xai-dynamic-routing-methods.md).  
Concepts (explanations, examples, diagrams): [concepts/cn-concepts-xai-routing.md](concepts/cn-concepts-xai-routing.md).  
Webpage by phase: [web/web-phase-plan.md](web/web-phase-plan.md).  
Backend/Docker: [web/backend-docker.md](web/backend-docker.md).

**Critical path:** P0 → P1 → P3 → P4 → P5. P2 can run in parallel with P3 after P1. P0 is done.

**First demo (M3, end of P4):** sample graph → RIP/OSPF/AI paths → SHAP/LIME text and figure.

Work checklists live in the phase-plan file (tick them as each phase is finished).

Faults: [fault-ledger.md](fault-ledger.md). Do not correct a logged fault unless the user approves that ID.
