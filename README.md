<div align="center">

# ⚡ NEXUS — Autonomous Super Agent Runtime

### *The Deterministic-First Agentic Operating System that Learns, Automates, and Executes Across Desktop & Web*

[![CI Pipeline](https://github.com/Sagnify/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/Sagnify/nexus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Electron](https://img.shields.io/badge/Electron-34.2-47848F?logo=electron&logoColor=white)](https://www.electronjs.org/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC?logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Groq LPU](https://img.shields.io/badge/Groq-LPU_Inference-F05A28?logo=groq&logoColor=white)](https://groq.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Serverless-00E599?logo=postgresql&logoColor=black)](https://neon.tech/)

<br />

> **"Chatbots talk. Copilots suggest. NEXUS ACTS — Deterministically."**
>
> An ultra-fast, Spotlight-native autonomous desktop runtime built on a core engineering principle: **Stop asking the LLM to do work that deterministic code can do.**
> 
> NEXUS replaces fragile, slow multi-agent LLM loops with a deterministic compiler, sub-millisecond connector routing, live Win32 COM automation, multi-tier ground-truth outcome verification, autonomous deep research document synthesis, and demonstration-based skill acquisition powered by VLM spatial feature extraction and native OS hardware hooks.

<br />

[⚡ The Optimization Engine (Main USP)](#-the-core-usp-deterministic-first-optimization-engine) •
[📂 Project Structure](#-project-structure) •
[📊 Office Automation Suite](#-native-microsoft-office-automation-suite) •
[🔬 Deep Research Engine](#-autonomous-deep-research-engine) •
[🌐 Browser Companion (MV3)](#-nexus-browser-companion-chrome-extension-mv3) •
[⏰ Persistent Scheduler & Morning Brief](#-persistent-scheduler--background-automation-service) •
[🛡️ Self-Healing Sentinel & Voice Suite](#-self-healing-sentinel--voice-diagnostic-suite) •
[🧠 VLM Skill Learning](#-skill-learning-via-vlm-feature-extraction--hardware-hooks) •
[🛡️ Outcome Validation Layer](#-multi-tier-outcome-validation-layer) •
[🏛️ System Architecture](#-technical-architecture) •
[🔌 Connector Ecosystem](#-connected-application-ecosystem--mcp) •
[📡 API Specification](#-rest--websocket-api-specification) •
[⌨️ Shortcuts](#️-global-keyboard-controls) •
[🛠️ Quick Start](#️-getting-started)

</div>

---

## ⚡ The Core USP: Deterministic-First Optimization Engine

### The Problem with 99% of AI Agents Today
Traditional autonomous agents are plagued by massive latency, token bloat, and operational fragility:
- **The Step-by-Step Operator Anti-Pattern**: Running `LLM -> click -> LLM -> inspect -> LLM -> type -> LLM -> inspect...` burns 20–60 seconds, exhausts rate limits, costs hundreds of thousands of tokens, and introduces compound failure rates.
- **Dumb Macro Fragility**: Legacy RPA or screen recorder bots rely on hard-coded pixel coordinates that shatter the second a window is moved or a display scale changes.
- **Hallucinated Task Completion**: Asking the same LLM "did you finish the task?" results in blind self-affirmation rather than actual verification.

### The NEXUS Engineering Principle:
> **"Never burn an expensive reasoning token on an operation that deterministic code, direct APIs, or live DOM compilers can resolve in under 5 milliseconds."**

```
Traditional Agent (25,000ms, 45k tokens, Fragile):
  User ──► LLM #1 ──► Click ──► LLM #2 ──► Inspect ──► LLM #3 ──► Type ──► LLM #4 ──► Inspect ──► ???

NEXUS Deterministic Pipeline (<600ms, 0-1 LLM call, Rock Solid):
  User ──► Deterministic Compiler ──► Structured Plan ──► Native Hardware/API Executor ──► Ground-Truth Verification
                 │
                 ├── Tier 0: Direct Authenticated Connectors (Gmail, Calendar, Spotify, Drive) [<5ms]
                 ├── Tier 1: Structured Live DOM Engine (Zero screenshot grounding latency) [<20ms]
                 └── Tier 2: LLM invoked ONLY when state is genuinely ambiguous or on exceptions
```

### 1. Deterministic Multi-Tier Tool Router (<1ms Fast-Path)
Before touching an LLM, incoming requests pass through our high-speed routing compiler:
- **Tier 0 (Authenticated Connectors & MCP APIs)**: Interacts directly with official authenticated APIs (Gmail, Google Calendar, Spotify, Slack, GitHub, Linear, Notion, Todoist, Filesystem). Executes in milliseconds without opening browser tabs, navigating websites, or driving the mouse.
- **Tier 1 (Structured Browser & Live DOM)**: Uses Chrome DevTools Protocol (CDP) and DOM trees. Interacts directly with live DOM nodes via semantic selectors (`[role="button"]`, `[aria-label]`, data attributes) without screenshot capture or vision latency.
- **Tier 2 (VLM & Native OS Hardware Automation)**: Reserved exclusively for non-web OS windows (Excel, Word, PowerPoint, desktop clients) or canvas-based web apps where DOM trees are physically unavailable.

### 2. The LLM as a Planner, Not an Operator
NEXUS flips the agent architecture upside down:
1. **Single-Pass Planning**: An ultra-fast planning call (on Groq LPUs in <300ms) or cached template produces a complete, structured execution contract.
2. **Deterministic Autonomous Execution**: The execution engine executes the steps sequentially without querying the LLM between each deterministic step.
3. **Event-Driven Exception Handling**: The LLM is re-invoked **only** if an execution invariant breaks or an unexpected state occurs.

### 3. Plan Caching & Zero-LLM Fast-Paths
- Recognized query patterns (e.g. creating Excel financial models, creating Word post-mortems, scheduling calendar events, managing playlists) compile into deterministic execution plans in **<1ms with 0 LLM calls**.
- Re-executing similar intents draws from cached execution contracts, reducing recurring operational costs to zero.

### 4. Compact State vs. Giant Context Dumps
- **Observation Summarization**: When terminal commands or browser inspections return 500 lines of raw output, local deterministic parsers extract actionable key signals (exit codes, error messages, targeted selectors). The LLM receives **6 relevant lines instead of 500 lines of noise**.
- **State Over History**: NEXUS passes a compact normalized state (`task_id`, `current_step`, `active_target`, `completed_steps`) rather than multi-megabyte conversational transcripts.

---

## 📂 Project Structure

A modular, production-hardened monorepo cleanly decoupling the Electron desktop runtime, the Chrome MV3 companion extension, the React glassmorphic UI, and the Python FastAPI / LangGraph agent daemon:

```
nexus/
├── backend/                               # Python FastAPI & LangGraph Daemon (Port 8000)
│   ├── agent/                             # Stateful Agent Graph & Autonomous Orchestrator
│   │   ├── graph.py                       # LangGraph compilation & workflow state machine
│   │   ├── state.py                       # NexusState runtime state definition
│   │   ├── nodes/                         # Graph workflow nodes (intent, planner, executor, etc.)
│   │   ├── router/                        # High-speed tool router & Groq/Gemma model router
│   │   ├── skills/                        # Dynamic skill recording & compilation session manager
│   │   ├── tools/                         # Modular tool execution libraries
│   │   │   ├── excel_copilot/             # Live Win32 COM Excel companion & 7 core tool categories
│   │   │   ├── research/                  # Autonomous Deep Research multi-format engine
│   │   │   ├── spreadsheet/               # Headless openpyxl spreadsheet modeling
│   │   │   ├── document/                  # Headless python-docx executive document drafting
│   │   │   ├── presentation/              # Headless python-pptx 16:9 widescreen presentation engine
│   │   │   ├── web_automation/            # Chrome DevTools Protocol & extension WebSocket bridge
│   │   │   ├── filesystem/                # Sandboxed local filesystem operations
│   │   │   ├── gui/                       # Win32 native hardware input & window control
│   │   │   └── registry.py                # Unified tool registry & schema provider
│   │   └── validation/                    # 3-tier outcome validators & deterministic assertions
│   ├── api/                               # FastAPI REST Routers & WebSocket Endpoints
│   │   ├── nexus.py                       # Tasks, SSE streaming, permissions, Excel COM & targets
│   │   ├── skills.py                      # Skill CRUD, Teach Mode session control, version rollback
│   │   ├── scheduled_tasks.py             # Background automation, natural language parsing & leases
│   │   ├── connectors.py                  # OAuth flows (Google, Spotify) & live connector operations
│   │   ├── tts.py                         # Microsoft Edge Neural TTS streaming & voice catalog
│   │   ├── auth.py                        # Firebase authentication & session token validation
│   │   ├── history.py                     # Historical task runs, artifacts & execution telemetry
│   │   ├── recommendations.py             # Context-aware contextual suggestions
│   │   └── settings.py                    # Local persistent configuration & API keys
│   ├── connectors/                        # Direct API Connectors (Gmail, Calendar, Spotify, Slack, etc.)
│   │   ├── base.py                        # Connector abstract base class & token refresh logic
│   │   ├── credentials_store.py           # Local-first encrypted JSON credential storage
│   │   └── manager.py                     # Connector lifecycle & tool registration manager
│   ├── core/                              # Low-Level OS Hooks, Security & System Services
│   │   ├── auto_healer.py                 # Self-Healing Sentinel for deadlock recovery & model pooling
│   │   ├── device_identity.py             # Hardware UUID extraction for scheduler multi-worker leases
│   │   ├── permissions.py                 # Human-in-the-loop security permission gate
│   │   ├── logging_security.py            # Real-time regex secret redaction filter
│   │   ├── speech.py                      # Groq Whisper Turbo transcription & wake-word engine
│   │   ├── targets.py                     # Desktop active window context & target discovery
│   │   ├── paths.py                       # OS Desktop, Documents, Downloads safe path resolution
│   │   └── file_dialog.py                 # Win32 native save dialog integration
│   ├── database/                          # PostgreSQL / SQLite Storage Layer
│   │   ├── models.py                      # SQLAlchemy ORM models (Users, Skills, Schedules, Runs)
│   │   ├── session.py                     # Async database engine & connection pool
│   │   └── repositories/                  # Clean data repository abstractions (SkillRepo, ScheduleRepo)
│   ├── services/                          # Asynchronous Daemon Services
│   │   ├── scheduler_service.py           # Multi-worker background scheduler engine
│   │   ├── schedule_parser.py             # Natural language cron & recurrence parser
│   │   ├── notification_service.py        # System tray & desktop toast notifications
│   │   ├── history_service.py             # Task telemetry and artifact indexing
│   │   └── safety_filter.py               # Prompt injection defense & destructive action guardrails
│   └── tests/                             # Backend unit & integration test suites
├── electron/                              # Desktop App Shell (Electron 34 + TypeScript)
│   ├── main.ts                            # Transparent Spotlight window, floating pill, global hotkeys
│   └── preload.ts                         # Secure contextBridge IPC layer between renderer & host OS
├── extension/                             # NEXUS Browser Companion (Chrome Extension MV3)
│   ├── manifest.json                      # Manifest V3 configuration with CDP & debugger permissions
│   ├── background.js                      # Background service worker with WebSocket bridge client
│   ├── content.js                         # In-page synthetic event injection & live DOM observer
│   ├── popup.html / popup.js              # Extension status popup & manual reconnect HUD
│   └── icons/                             # Extension brand assets
├── src/                                   # Frontend UI (React 18 + Vite + Tailwind CSS)
│   ├── components/                        # Modern Glassmorphic UI Components
│   │   ├── SpotlightBar.tsx               # 860px Spotlight Command HUD & autocomplete
│   │   ├── ExcelCopilot.tsx               # Live Win32 COM Excel companion widget
│   │   ├── MicDiagnosticTool.tsx          # Real-time decibel meter, audio node & mic diagnostic suite
│   │   ├── EmailBriefView.tsx             # Morning email brief Markdown viewer & artifact extractor
│   │   ├── BrowserConnectPage.tsx         # OAuth verification & connector authorization portal
│   │   ├── AutomationPill.tsx             # Universal desktop execution progress pill
│   │   ├── RecordingPill.tsx              # Teach Mode demonstration recording controls
│   │   ├── SkillsPanel.tsx                # Skill library, editor, parameter schema & version history
│   │   ├── SchedulePanel.tsx              # Recurring automation scheduler & natural language input
│   │   ├── ConnectorsPanel.tsx            # One-click third-party OAuth hub
│   │   └── SettingsPanel.tsx              # Model selector, API keys, audio voice preferences
│   ├── context/                           # React Contexts (AuthContext, TargetContext, etc.)
│   ├── hooks/                             # Custom React Hooks (hotkeys, audio recording, SSE streams)
│   ├── services/                          # API client bindings & WebSocket connection managers
│   └── types/                             # Strict TypeScript interfaces & data contracts
├── tests/                                 # End-to-end integration & verification test matrix (24 test suites)
├── alembic.ini                            # Database migration configuration
├── requirements.txt                       # Python dependencies (FastAPI, LangGraph, openpyxl, python-docx, etc.)
├── package.json                           # Node.js dependencies (Electron, React, Tailwind, Vite)
├── tailwind.config.js                     # Obsidian Glass styling tokens & custom animations
└── vite.config.ts                         # Vite build configuration with Electron integration
```

---

## 📊 Native Microsoft Office Automation Suite

NEXUS features deep, native Microsoft Office automation across spreadsheets, documents, and presentations — bridging both live interactive desktop sessions via Win32 COM and high-speed headless document generation.

```
                           NEXUS OFFICE AUTOMATION SUITE
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  [ MICROSOFT EXCEL ]           [ MICROSOFT WORD ]           [ MICROSOFT POWERPOINT ]
  • Live Win32 COM Companion    • Executive Word Drafting     • 16:9 Widescreen Engine
  • Real-Time Context Engine    • Typographical Hierarchy     • 5 Executive Color Themes
  • 7 Core Tool Categories      • Callout Boxes & Tables      • Auto Web Image Placement
  • Headless openpyxl Models    • Headless python-docx        • Headless python-pptx
```

### 1. Excel Copilot (Live Win32 COM Companion)
Unlike external chatbots that ask you to upload spreadsheets or paste CSV snippets into a prompt, NEXUS includes a live, dockable companion widget (`ExcelCopilot.tsx`) that attaches directly to active Microsoft Excel workbooks via Win32 COM (`pywin32`):

- **Real-Time Context Inspection (`acquire_deep_excel_context`)**: Inspects active workbook names, sheet tabs, selected cell ranges, `UsedRange` boundaries, column header names, and inferred data types in sub-5ms without locking the UI.
- **7 Core Operation Tool Categories**:
  1. **`ExcelFormulaTool`**: Direct formula injection (`SUM`, `AVERAGE`, `COUNT`, `COUNTA`, `IF`, `IFS`, `SUMIF`, `AVERAGEIF`, and complex multi-column arithmetic) preserving Excel syntax and cell coordinate offsets.
  2. **`ExcelLookupTool`**: Automatically builds resilient relational lookups (`XLOOKUP`, `VLOOKUP`) across disparate columns and worksheets.
  3. **`ExcelSortFilterTool`**: Performs whole-table multi-column sorting (ascending/descending) and applies native `AutoFilter` rules with exact criteria matching.
  4. **`ExcelPivotTool`**: Programmatically synthesizes native Excel PivotTables from raw ranges, placing row fields, column fields, and calculated data aggregates (`xlSum`, `xlCount`, `xlAverage`) into dedicated report sheets.
  5. **`ExcelConditionalFormatTool`**: Configures native Excel `FormatConditions` rules (color scales, greater than, less than, equals) to highlight outliers, performance thresholds, and financial anomalies.
  6. **`ExcelDataCleanupTool`**: Deterministic deduplication (`RemoveDuplicates`), whitespace trimming, text-to-columns delimiter parsing, and empty row/column purging.
  7. **`ExcelInspectTool`**: On-demand range sampling and formula verification.
- **Visual VLM Post-Execution Validation & Self-Healing**: After executing mutations, NEXUS captures the active Excel window and runs a spatial VLM check (`validate_excel_execution_with_vlm`). If formula errors (e.g. `#REF!`, `#DIV/0!`, `#VALUE!`) or misplaced calculations are detected, the autonomous self-healing sentinel recalculates the range, adjusts column references, and replans the execution.

### 2. Headless Spreadsheet Modeling (`openpyxl`)
When Excel is not open or when large datasets require automated synthesis, NEXUS invokes the headless `spreadsheet_automation` engine:
- Generates multi-sheet financial models (P&L statements, DCF models, SaaS unit economics, churn cohorts).
- Applies curated typography, cell fills, borders, currency formats (`$#,##0.00`), and percentage styling (`0.0%`).
- Embeds dynamic cross-sheet formulas (`=SUM(B4:B12)`, `=(C4-B4)/B4`).
- Verifies output through **Tier 1 Ground-Truth Validation** (file existence, byte size, workbook schema parse).

### 3. Executive Word Drafting (`python-docx`)
The `document_automation` engine produces publication-ready Microsoft Word (`.docx`) documents:
- **Typographical Hierarchy**: Custom styled heading levels (Title, Subtitle, Heading 1, Heading 2), executive line spacing, and margin definitions.
- **Visual Callout Boxes**: Single-cell tinted callout containers with left accent borders for key takeaways, warnings, and executive quotes.
- **Custom Formatted Tables**: Zebra-striped data tables with centered metric headers, bold totals, and automated column width distribution.

### 4. PowerPoint Presentation Automation (`python-pptx`)
The `presentation_create` tool generates complete, professional slide decks:
- **Modern 16:9 Widescreen Standard**: Slide canvas sized to modern widescreen displays (13.333" × 7.5").
- **5 Executive Color Palettes**:
  - `executive_navy`: Slate/Navy backgrounds with Sky Blue accents for corporate strategy.
  - `modern_dark`: Minimalist charcoal canvas with purple/cyan accents for tech pitches.
  - `emerald_growth`: Deep forest greens and emerald tones for financial and sustainability reports.
  - `warm_editorial`: Sophisticated warm cream and terracotta tones for thought leadership.
  - `slate_minimal`: Clean monochromatic layout for high-density academic and engineering reviews.
- **Integrated Automated Web Image Placement**: Autonomous image search (`image_search.py`) queries high-resolution topic imagery, validates image formats and dimensions via PIL, and embeds photos with exact aspect-ratio cropping and rounded accent cards directly into slide layouts.
- **Native Save Integration**: Allows immediate desktop placement or invokes the native Windows File Dialog (`pick-save-path`) to save the deck anywhere on your system.

---

## 🔬 Autonomous Deep Research Engine

NEXUS includes an autonomous, academic-grade research engine (`deep_research.py`) capable of conducting end-to-end multi-source investigation and compiling comprehensive findings into any universal document format.

```
                             DEEP RESEARCH PIPELINE
                                       │
  1. Multi-Angle Query Formulation ────┼──── Formulates 4+ distinct research angles
  2. Live Concurrent Web Search    ────┼──── Searches DuckDuckGo / web sources concurrently
  3. Body Scraping & Extraction    ────┼──── Scrapes full article text via BeautifulSoup / httpx
  4. Academic Synthesis            ────┼──── Generates multi-section analysis with formal citations
  5. Multi-Format Compilation      ────┼──── Compiles directly into requested target formats
```

### End-to-End Pipeline Breakdown
1. **Multi-Query Web Research (`_plan_search_queries`)**: Deconstructs high-level research questions into 4 to 8 orthogonal search vectors covering historical background, current market metrics, competitive landscape, regulatory implications, and future outlooks.
2. **Live Scraping & Body Extraction (`_fetch_page_contents`)**: Uses `httpx` with realistic browser headers and `BeautifulSoup` to scrape full article content, strip navigation/ad clutter, and extract clean text.
3. **Academic Synthesis & Formal Citations (`_synthesize_research_report`)**: Synthesizes in-depth analytical sections, key findings, quantitative data tables, and an enumerated Bibliography with exact source URLs.
4. **Universal Multi-Format Compilation**: Compiles findings simultaneously into whatever formats you specify:
   - **Word (`.docx`)**: Full typography, styled callout boxes, bulleted analysis, and reference tables.
   - **PDF (`.pdf`)**: Formatted document output ready for distribution.
   - **Excel (`.xlsx`)**: Structured data worksheets with research findings, metrics, and quantitative source tracking.
   - **CSV (`.csv`)**: Raw tabular dataset export.
   - **Markdown (`.md`)**: GitHub-flavored Markdown report.
   - **Interactive HTML (`.html`)**: Self-contained, responsive HTML report styled with modern dark/light CSS.
   - **Plain Text (`.txt`)**: Clean UTF-8 text report.
   - **Structured JSON (`.json`)**: Machine-readable JSON schema containing topics, metadata, sections, and sources.

### Binary Format Guidance with Transparent Fallback
If a user requests synthesis into a proprietary binary format that cannot be generated without third-party host software (e.g. `.cpr` Cubase Project, `.psd` Photoshop, `.aep` After Effects, `.prproj` Premiere Pro, `.flp` FL Studio, `.dwg` AutoCAD, `.blend` Blender), NEXUS does not fail blindly or hallucinate invalid binary files:
- It issues a clear, helpful in-app notification explaining format constraints.
- It automatically compiles the comprehensive research, project plan, and data model into universal **DOCX, PDF, or XLSX** formats so you can immediately proceed with your work.

---

## 🌐 NEXUS Browser Companion (Chrome Extension MV3)

The NEXUS Browser Companion is a **Manifest V3** Chrome extension (`extension/`) that acts as a low-latency bridge between the local agent runtime and live browser web pages.

```
 ┌──────────────────────┐          WebSocket (Port 8000)          ┌──────────────────────┐
 │    NEXUS DESKTOP     │◄───────────────────────────────────────►│   CHROME EXTENSION   │
 │   FastAPI Backend    │      ws://127.0.0.1:8000/ws/extension   │    (Manifest V3)     │
 └──────────────────────┘                                         └──────────────────────┘
            │                                                                │
            │ REST / SSE                                                     │ Chrome DevTools Protocol
            ▼                                                                ▼ (chrome.debugger)
 ┌──────────────────────┐                                         ┌──────────────────────┐
 │     ELECTRON UI      │                                         │      LIVE WEB        │
 │ (BrowserConnectPage) │                                         │      DOM TREE        │
 └──────────────────────┘                                         └──────────────────────┘
```

### Architecture Highlights
- **Manifest V3 Service Worker (`background.js`)**: Runs an event-driven background service worker that maintains an auto-reconnecting WebSocket connection to `ws://127.0.0.1:8000/ws/extension`.
- **Content Script (`content.js`)**: Injected at `document_idle` across all tabs to observe live DOM mutations, track focused elements, and handle in-page UI overlays.
- **Chrome DevTools Protocol (CDP via `chrome.debugger`)**: Bypasses slow screen capture and noisy vision models by issuing raw CDP input commands (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`). This provides **sub-20ms synthetic clicks and typing** indistinguishable from native user interactions.
- **Sub-20ms Live DOM Inspection**: Deterministically discovers buttons, input fields, dropdowns, and links via semantic attributes (`role`, `aria-label`, `data-testid`, text anchors) without screenshot latency.
- **Companion Diagnostics & Connection Verification (`BrowserConnectPage.tsx`)**:
  - In-app interactive diagnostic page for verifying WebSocket bridge connectivity, checking active tabs, and testing element clicks.
  - Dedicated verification test harness (`/test-harness`) for end-to-end integration validation.

---

## ⏰ Persistent Scheduler & Background Automation Service

NEXUS includes an enterprise-grade background automation engine (`scheduler_service.py`) that executes scheduled tasks, daily routines, and notifications even when the main Spotlight window is closed.

```
                               SCHEDULER ENGINE
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
  [ Hardware UUID Lease ]     [ Natural Language Parser ]   [ Morning Email Brief ]
  • Atomic execution claiming  • "every Monday at 9am"       • Scans unread emails
  • Multi-worker lock safety  • "remind me in 20 minutes"   • Summarizes key threads
  • Prevents duplicate runs   • Cron & interval synthesis   • Generates action items
```

### 1. Multi-Worker Atomic Claiming & Hardware Leases
- **Hardware UUID Binding (`device_identity.py`)**: Every host machine computes a deterministic hardware UUID. Tasks can be pinned to specific physical machines or dynamically claimed.
- **Atomic Run Claiming**: Before executing an automation, the worker executes an atomic database update lease. This guarantees **zero duplicate task executions** across multiple daemon instances or distributed nodes.
- **Pre-Flight Connector Verification**: Verifies OAuth token validity for required connectors (e.g. Gmail, Calendar) prior to execution, alerting the user if re-authentication is needed.

### 2. Natural Language Schedule Parsing (`schedule_parser.py`)
Users can schedule tasks in plain English without learning cron syntax:
- `"every Monday at 9am"` ➔ Recurrence rule: `FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0`
- `"every weekday at 8:30 AM"` ➔ Recurrence rule: `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=30`
- `"remind me in 45 minutes to submit the quarterly report"` ➔ One-shot execution at `now() + 45m`
- Standard 5-field cron strings (`0 9 * * 1`) are fully supported for power users.

### 3. Automated Morning Email Brief (`EmailBriefView.tsx`)
- Schedules a recurring morning review of your inbox via authenticated Gmail APIs.
- Filters out promotional noise and newsletters to extract urgent client inquiries, meeting requests, and blocker threads.
- Formats the brief into structured Markdown with direct deep-links to Gmail message threads.
- Provides a dedicated run history drawer in Spotlight to browse previous briefs and review generated artifacts.

---

## 🛡️ Self-Healing Sentinel & Voice Diagnostic Suite

Reliability and natural interaction are foundational to the NEXUS architecture.

### 1. Autonomous Self-Healing Sentinel (`auto_healer.py`)
Background sentinel continuously monitors runtime health and prevents degradation:
- **Deadlock Mitigation**: Detects hung tool invocations or stalled graph workflows and gracefully releases thread locks.
- **Model Pool Health & Cooldown Tracking**: Automatically manages API rate limits across model providers. When a provider returns `429 Too Many Requests`, the sentinel places that model into a cooldown state and transparently switches to the next available tier without interrupting execution.
- **System Health & Recovery Endpoints**:
  - `GET /api/system/health`: Reports uptime, active sessions, model pool health, and recovery statistics.
  - `POST /api/system/recover`: Instantly flushes stale sessions, resets expired cooldowns, and restores the runtime to an optimal state.

### 2. Microphone Diagnostic Suite (`MicDiagnosticTool.tsx`)
A complete in-app audio engineering diagnostic tool built directly into Settings:
- **Live Decibel Metering**: Real-time visual decibel meter tracking peak and RMS microphone input volume.
- **Web Audio Node Inspection**: Inspects the entire `AudioContext` graph, `MediaStreamAudioSourceNode`, and `AnalyserNode` frequency spectrum.
- **Device Enumeration**: Lists all connected physical audio input devices and allows seamless switching between microphones.
- **Hardware Test Runner**: Automated 4-step diagnostic verification (Device Availability, AudioContext Initialization, Stream Acquisition, Signal Detection) with one-click diagnostic log export.

### 3. Speech Transcription & Microsoft Edge Neural TTS
- **Low-Latency Speech Recognition (`speech.py`, Groq Whisper Turbo)**: Transcribes incoming audio in <200ms using `whisper-large-v3-turbo`.
- **Instant Wake-Word Engine**: Listens for wake phrases (*"Hey NEXUS"*, *"OK NEXUS"*, or *"NEXUS"*) and immediately extracts the actionable instruction for execution.
- **Neural Voice Synthesis (`tts.py`, `edge_tts`)**: High-fidelity, natural neural text-to-speech streaming directly into the desktop client with zero cloud subscription cost. Supports diverse neural voices (`en-US-AriaNeural`, `en-US-GuyNeural`, `en-GB-SoniaNeural`, and multilingual options).

---

## 🧠 Skill Learning via VLM Feature Extraction & Hardware Hooks

> **NEXUS Teach Mode is NOT dumb screen recording or video replay.**

Screen recorders capture brittle pixels (`(x=420, y=780)`) that inevitably fail when window positions, screen resolutions, display scaling (100% vs 125%), or responsive layouts change.

NEXUS captures **human demonstration at the semantic and hardware layer**, turning user actions into intelligent, parameterized executable code:

```
                    NEXUS DEMONSTRATION-TO-CODE DISTILLATION PIPELINE
                    
 ┌──────────────────────┐        ┌───────────────────────┐        ┌────────────────────────┐
 │   NATIVE HARDWARE    │        │  VLM SPATIAL FEATURE  │        │   PARAMETER INDUCTION  │
 │      MONITORING      │───────►│      EXTRACTION       │───────►│    & CODE SYNTHESIS    │
 │ • Mouse clicks & pos │        │ • Element bounding box│        │ • Identify typed values│
 │ • Keyboard strokes   │        │ • Visual anchor text  │        │ • Generalize variables │
 │ • Win32 active window│        │ • Accessibility roles │        │ • Purge noise & jitter │
 └──────────────────────┘        └───────────────────────┘        └────────────────────────┘
                                                                               │
                                                                               ▼
                                                                  ┌────────────────────────┐
                                                                  │ RESILIENT SKILL SCHEMA │
                                                                  │ • Resolution agnostic  │
                                                                  │ • Semantic fallbacks   │
                                                                  │ • Idempotent contract  │
                                                                  └────────────────────────┘
```

### How Teach Mode Actually Works:

1. **Hardware Interaction Interception**:
   - The native OS Floating Pill activates low-level event hooks to capture raw mouse clicks, keyboard inputs, modifier keys, and OS active window handles.
   - Sensitive text inputs (passwords, tokens) are automatically redacted in real-time before passing to memory.

2. **VLM Spatial & Semantic Feature Extraction**:
   - At every interaction point, NEXUS captures the local UI region and runs visual-spatial grounding alongside accessibility trees.
   - Rather than storing an absolute coordinate, the feature extractor isolates:
     - **Visual Landmarks**: Semantic proximity to surrounding labels, icons, and text anchors.
     - **Element Identity**: Tag names, ARIA roles, input types, and test identifiers (`data-testid`, `name`, `id`).
     - **Spatial Offsets**: Relative position within the parent container, ensuring resilience across differing DPIs and window dimensions.

3. **Dynamic Parameter Induction**:
   - Concrete values demonstrated during recording (e.g. typing `"alex@company.com"` or `"Q3 Budget"`) are analyzed by the compiler.
   - The compiler automatically abstracts these literals into typed parameters (`{{recipient_email}}`, `{{document_title}}`) with full schema definitions (`type: "email"`, `description: "..."`).

4. **Multi-Attribute Fallback Bundles**:
   - Every compiled step generates a ranked selector bundle:
     `[testId] -> [aria-label] -> [accessible-role + text] -> [css-path] -> [VLM visual anchor]`
   - If a website update modifies the CSS class or layout, the execution runtime transparently cascades to the next attribute in the bundle.

5. **3-Stage Skill Matcher**:
   - When a user speaks or types a prompt in Spotlight, NEXUS evaluates:
     1. Exact trigger keywords.
     2. Semantic embedding similarity against the user's personal skill registry.
     3. AI intent synthesis.
   - The matched skill executes with zero friction, showing the active skill badge, parameter bindings, and step timeline.

---

## 🛡️ Multi-Tier Outcome Validation Layer

Most agent frameworks suffer from the **"Blind Executor" problem**: they fire off actions and assume they worked without verifying real system ground truth.

NEXUS implements a dedicated **3-Tier Outcome Validation Layer** that guarantees task completion:

```
                                  EVALUATOR NODE
                                         │
                        Does the task have ground-truth?
                                         │
                ┌────────────────────────┴────────────────────────┐
                ▼                                                 ▼
      [ Tier 1: Deterministic ]                        [ Tier 2: Live DOM / OS ]
     • File existence on disk                         • Assert element visibility
     • Non-zero file byte size                        • Check URL & navigation state
     • Valid JSON / XLSX / DOCX parsing               • Text / status presence
     • Exit code == 0 & API 200 payload               • Window title & focus state
                │                                                 │
                └────────────────────────┬────────────────────────┘
                                         ▼
                                Did assertions pass?
                                 ├── YES ──► Task Marked "COMPLETED" (Verified Ground-Truth)
                                 └── NO  ──► Tier 3: Targeted Micro-LLM Diagnostic & Self-Heal
```

- **Tier 1 (Deterministic Verification - Zero LLM)**: For file operations, spreadsheets, documents, or API actions, NEXUS directly inspects the filesystem or API response. It verifies file creation, byte length, workbook formulas, or message IDs on disk without asking the LLM.
- **Tier 2 (Live DOM & OS State Inspection)**: For web and desktop tasks, NEXUS inspects the live DOM or window tree to verify that submitted forms generated confirmation elements, correct URLs, or desired UI changes.
- **Tier 3 (Targeted Micro-LLM Judge)**: If and only if a task requires subjective visual verification (e.g. validating design layout), a compact evaluation model performs targeted inspection.
- **Spotlight UI Feedback**: Completed tasks display transparent performance metrics:
  `⚡ 0 LLM Calls | 42ms | Verified Ground-Truth (Tier 1)` or `⚡ 1 LLM Call | 480ms | Verified DOM`.

---

## 🏛️ Technical Architecture

NEXUS is engineered as a reactive hybrid desktop system: an **Obsidian Glass Electron UI** fronting an **Asynchronous Python FastAPI Daemon** that powers stateful LangGraph workflows.

```mermaid
flowchart TD
    subgraph OS_Client ["Host Desktop (Windows / Electron 34)"]
        GlobalHotkeys["Global Hotkeys (Alt+N / Ctrl+Shift+N)"]
        SpotlightHUD["Spotlight Command Bar (860px Glassmorphism HUD)"]
        FloatingPill["Universal OS Floating Pill (Always-on-top HUD)"]
        AudioEngine["Microsoft Edge Neural TTS (en-US-AriaNeural)"]
        HardwareHooks["Win32 Input & Window Focus Hooks"]
        ExcelCopilotWidget["Excel Copilot Companion Widget"]
    end

    subgraph Browser_Layer ["Browser Companion Ecosystem"]
        ExtensionBridge["NEXUS Chrome Companion Extension (MV3)"]
        CDPBridge["Live DOM / CDP Inspection Bridge"]
    end

    subgraph Backend_Runtime ["Autonomous Agent Runtime (FastAPI + LangGraph)"]
        FastAPIServer["Async FastAPI Server (Port 8000)"]
        
        subgraph Graph_Nodes ["LangGraph Execution Graph"]
            IntentNode["1. Intent Classifier"]
            PlannerNode["2. Tier Compiler & Planner"]
            PermissionGate{"3. Human Permission Gate"}
            ExecutorNode["4. Hardware / API Executor"]
            ObserverNode["5. State Observer"]
            EvaluatorNode["6. Multi-Tier Outcome Validator"]
        end

        subgraph Core_Services ["Core Engines"]
            ExcelCOM["Win32 COM Excel Engine (7 Categories)"]
            DeepResearch["Autonomous Deep Research Engine"]
            SchedulerEngine["Multi-Worker Persistent Scheduler"]
            AutoHealer["Self-Healing Sentinel"]
            ConnectorRegistry["Connector & MCP Mesh"]
            VLMFeatureExtractor["VLM Spatial Feature Extractor"]
            SmartEmailComposer["Smart Email AI Composer"]
            SafetyEngine["Policy & Risk Categorization Engine"]
        end
    end

    subgraph Hardware_Inference ["Ultra-Low Latency Inference"]
        GroqEngine["Groq LPU Engine (Llama 3.3 70B / 3.1 8B Instant)"]
        GemmaEngine["Google Gemma 3 27B IT (Deep Reasoning)"]
    end

    %% Wiring
    GlobalHotkeys --> SpotlightHUD
    SpotlightHUD <--> FloatingPill
    SpotlightHUD <--> ExcelCopilotWidget
    SpotlightHUD -- "REST / SSE Stream" --> FastAPIServer
    ExtensionBridge <--> CDPBridge
    CDPBridge <--> FastAPIServer
    
    FastAPIServer --> IntentNode
    IntentNode --> PlannerNode
    PlannerNode --> PermissionGate
    PermissionGate -- "Requires Approval" --> SpotlightHUD
    PermissionGate -- "Approved" --> ExecutorNode
    ExecutorNode --> ObserverNode
    ObserverNode --> EvaluatorNode
    EvaluatorNode -- "Loop / Heal" --> PlannerNode
    
    PlannerNode <--> Core_Services
    ExecutorNode <--> HardwareHooks
    ExecutorNode <--> ExcelCOM
    Core_Services <--> Hardware_Inference
```

---

## 🔌 Connected Application Ecosystem & MCP

NEXUS connects directly to your digital workspace via official authenticated APIs and Model Context Protocol (MCP) servers:

| Connector | Tools Provided | Execution Mode | Security Risk |
| :--- | :--- | :--- | :--- |
| **Gmail** | `gmail_send_email`, `gmail_create_draft` | Official Google OAuth API (<300ms) | `PRIVILEGED` (Requires Approval to Send) |
| **Google Calendar** | `calendar_list_events`, `calendar_create_event`, `calendar_delete_event` | Google Calendar API (<200ms) | `SAFE` (Read) / `MUTATION` (Write) |
| **Spotify** | `spotify_play_track`, `spotify_search_tracks` | Web API / Desktop URI (<50ms) | `SAFE` |
| **Google Drive** | `drive_search_files`, `drive_get_file` | Google Drive v3 API (<250ms) | `SAFE` (Read) |
| **Slack** | `slack_send_message` | Webhooks / Slack API (<150ms) | `PRIVILEGED` |
| **GitHub** | `github_create_issue`, `github_search_repositories` | GitHub REST / MCP API (<300ms) | `SAFE` / `MUTATION` |
| **Linear** | `linear_create_issue`, `linear_search_issues` | Linear GraphQL / MCP API (<200ms) | `SAFE` / `MUTATION` |
| **Notion** | `notion_search_pages` | Notion Official API (<250ms) | `SAFE` |
| **Todoist** | `todoist_create_task`, `todoist_list_tasks` | Todoist REST API (<200ms) | `SAFE` / `MUTATION` |
| **Filesystem** | `read_file`, `write_file`, `list_directory`, `search_files` | Native Host OS (<5ms) | `READ_ONLY` / `MUTATION` / `DESTRUCTIVE` |

### Smart Email Preview & Human Confirmation Gate
When you ask NEXUS to write or send an email:
1. **Intelligent Content Composition**: Composes a concise subject line and a polite, well-structured body.
2. **Sender Identity Resolution**: Resolves the sender's sign-off name in priority order:
   - *Prompt Override*: If you say `"from Bob"` or `"sign off as Alice"`, NEXUS signs off with that explicit name.
   - *Logged-in User*: Defaults to your authenticated Firebase / Google account display name.
   - *Local Profile*: Falls back to your local OS user profile (`USERNAME`).
   - *Zero Placeholder Guarantee*: Replaces and strips any lingering `[Your Name]` tokens.
3. **Dedicated In-App Preview Card**: Suspends execution at the `PermissionGate` and displays the exact email inside Spotlight:
   - **To**: Highlighted recipient email address
   - **Subject**: Formatted subject line
   - **Message Body**: Clean, readable, scrollable message text
   - **Instant Execution**: One-click **"Send Email Immediately"** (dispatches via API) or **"Cancel"**.

---

## 📡 REST & WebSocket API Specification

The FastAPI backend exposes a robust suite of REST and streaming endpoints:

| Category | Method | Endpoint | Description | Risk / Access |
| :--- | :--- | :--- | :--- | :--- |
| **Tasks & Graph** | `POST` | `/api/nexus/run` | Dispatches task to LangGraph, returns `task_id` | User Session |
| | `GET` | `/api/nexus/stream/{task_id}` | Real-time Server-Sent Events (SSE) telemetry stream | Public Stream |
| | `POST` | `/api/nexus/permission/{task_id}` | Submits user approval/rejection for gated step | User Session |
| | `POST` | `/api/nexus/pause` | Pauses currently executing workflow | User Session |
| | `POST` | `/api/nexus/resume` | Resumes paused workflow | User Session |
| | `POST` | `/api/nexus/cancel` | Immediately cancels active workflow and cancels jobs | User Session |
| | `POST` | `/api/nexus/input` | Resolves interactive user clarification prompt | User Session |
| **Target Discovery**| `GET` | `/api/nexus/targets` | Discovers open desktop windows, applications & tabs | Host System |
| | `POST` | `/api/nexus/target/select` | Focuses target application and acquires active context | Host System |
| | `GET` | `/api/nexus/target/current` | Returns active target and cached UI state context | Host System |
| **Excel COM** | `GET` | `/api/nexus/excel/windows` | Enumerates open Excel window handles (`HWND`) | Host System |
| | `GET` | `/api/nexus/excel/context` | Deep inspection of active sheet, selection, headers | Host System |
| | `POST` | `/api/nexus/excel/execute` | Executes 7-category Excel operations via Win32 COM | Privileged Mutating |
| **Skills Lifecycle** | `GET` | `/api/skills` | Lists registered automation skills for user tenant | Authenticated |
| | `POST` | `/api/skills` | Creates new compiled skill schema | Authenticated |
| | `POST` | `/api/skills/teach/start` | Initiates Teach Mode demonstration capture | Authenticated |
| | `GET` | `/api/skills/teach/status` | Polling endpoint for active recording status | Authenticated |
| | `POST` | `/api/skills/teach/stop` | Finalizes recording, triggers VLM distillation | Authenticated |
| | `POST` | `/api/skills/{id}/rollback`| Reverts skill to previous verified version | Authenticated |
| | `POST` | `/api/skills/{id}/health` | Updates skill reliability & execution telemetry | Authenticated |
| **Scheduler** | `GET` | `/api/scheduled-tasks` | Retrieves scheduled automation jobs and timers | Authenticated |
| | `POST` | `/api/scheduled-tasks` | Creates new scheduled job | Authenticated |
| | `POST` | `/api/scheduled-tasks/parse`| Parses natural language query into cron recurrence | Authenticated |
| | `POST` | `/api/scheduled-tasks/create-from-text` | One-shot schedule creation from plain English prompt | Authenticated |
| | `GET` | `/api/scheduled-tasks/device-id` | Returns host hardware UUID for worker claiming | Authenticated |
| | `POST` | `/api/scheduled-tasks/{id}/run-now` | Triggers immediate out-of-schedule execution | Authenticated |
| | `GET` | `/api/scheduled-tasks/{id}/runs` | Retrieves execution run history and artifact logs | Authenticated |
| **Connectors** | `GET` | `/api/connectors` | Lists status and health of all connected accounts | User Session |
| | `GET` | `/api/connectors/google/auth-url` | Generates Google OAuth consent URL | User Session |
| | `GET` | `/api/connectors/spotify/auth-url` | Generates Spotify OAuth authorization URL | User Session |
| | `GET` | `/api/connectors/calendar/events` | Reads calendar events via Google Calendar API | Authenticated |
| | `POST` | `/api/connectors/calendar/events` | Schedules calendar event | Authenticated |
| **Voice & Speech** | `POST` | `/api/nexus/transcribe` | Transcribes audio via Groq Whisper Turbo & wake word | Host System |
| | `GET` | `/api/nexus/voices` | Returns catalog of Microsoft Edge Neural TTS voices | Host System |
| | `POST` | `/api/nexus/tts` | Streams high-fidelity neural audio speech stream | Host System |
| **System Sentinel**| `GET` | `/api/system/health` | Returns runtime health, model pool state, uptimes | Diagnostic |
| | `POST` | `/api/system/recover` | Triggers auto-healer session recovery and cache flush | Admin / Local |
| **Browser Bridge** | `WS` | `/ws/extension` | Bidirectional WebSocket for Chrome MV3 extension | WebSocket |
| | `GET` | `/api/extension/status` | Checks extension connection state and disk path | Local Bridge |
| | `POST` | `/api/extension/command` | Dispatches synthetic CDP action to active tab | Local Bridge |
| | `GET` | `/test-harness` | HTML verification harness for extension testing | Verification |

---

## 🛡️ Security & Human-In-The-Loop Governance

| Security Layer | Implementation Detail |
| :--- | :--- |
| **Strict Permission Gate** | Privileged actions (`gmail_send_email`, `slack_send_message`, file deletions, destructive shell commands) halt automatically and require physical user approval. |
| **Real-Time Secret Redaction** | All outgoing LLM context and telemetry pass through a streaming regex engine that masks API keys (`gsk_*`, `sk-*`, `AIza*`), OAuth tokens, passwords, and private connection strings. |
| **Local-First Secrets Storage** | OAuth tokens and API keys are stored locally on your machine in `~/.nexus/connector_credentials.json` and `~/.nexus/settings.json`. No secrets are transmitted to cloud telemetry. |
| **Multi-Tenant Data Isolation** | User skills, history, and preferences are strictly isolated by authenticated user IDs via Row-Level Security in PostgreSQL. |
| **Offline Guest Mode** | Unauthenticated sessions run purely in-memory and local storage without remote network persistence. |

---

## ⌨️ Global Keyboard Controls

| Shortcut | Context | Function |
| :--- | :--- | :--- |
| <kbd>Alt</kbd> + <kbd>N</kbd> | Anywhere in OS | **Toggle NEXUS Spotlight Bar** (Hardware-accelerated) |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>N</kbd> | Anywhere in OS | Alternate global toggle shortcut |
| <kbd>Tab</kbd> | Spotlight Bar | Cycle search modes: `All` ➔ `Apps` ➔ `Files` ➔ `AI` |
| <kbd>Enter</kbd> | Spotlight Bar | Execute command or confirm selected suggestion |
| <kbd>Esc</kbd> | Spotlight / Pill | Dismiss window, close modals, or reset task state |
| <kbd>Arrow Up</kbd> / <kbd>Down</kbd> | Spotlight Bar | Navigate through autocomplete and search history |

---

## 🛠️ Getting Started

### Prerequisites
- **Node.js**: v18.0 or newer (`node -v`)
- **Python**: v3.11 or v3.12 (`python --version`)
- **Google Chrome**: (For the NEXUS Browser Companion Extension)
- **Git**

---

### 1. Installation

```bash
# 1. Clone the repository
git clone https://github.com/Sagnify/nexus.git
cd nexus

# 2. Install frontend dependencies
npm install

# 3. Setup Python virtual environment
python -m venv venv

# 4. Activate virtual environment (Windows PowerShell)
.\venv\Scripts\activate
# Or on macOS/Linux:
# source venv/bin/activate

# 5. Install backend dependencies
pip install -r requirements.txt
```

---

### 2. Environment Configuration

Copy the example environment configuration and populate your API credentials:

```bash
cp .env.example .env
```

Key environment variables:
```ini
# LLM Inference Providers
GROQ_API_KEY=gsk_your_groq_api_key_here
GEMMA_API_KEY=your_gemini_api_key_here

# Database Configuration (PostgreSQL / Neon Serverless)
DATABASE_URL=postgresql+asyncpg://user:password@ep-sample-123.pooler.neon.tech/nexus?sslmode=require

# Connectors & OAuth (Google Workspace, Spotify)
GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
```

---

### 3. Loading the Chrome Extension

1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Toggle the **Developer mode** switch in the top-right corner.
3. Click **Load unpacked**.
4. Select the `extension/` folder inside the `nexus/` repository directory.
5. The **NEXUS Browser Companion** badge will appear in your Chrome toolbar. It will automatically connect to `ws://127.0.0.1:8000/ws/extension` when the backend starts.

---

### 4. Running the Development Server

Start both the FastAPI backend daemon and the Vite + Electron desktop application concurrently:

```bash
npm run dev
```

1. Press <kbd>Alt</kbd> + <kbd>N</kbd> anywhere on your system to summon the Obsidian Glass Spotlight HUD.
2. Click the **Settings (gear)** icon on the top right to verify your API keys, run the **Microphone Diagnostic Suite**, or select neural voice models.
3. Open the **Connectors Hub** to link your Gmail, Google Calendar, Spotify, or GitHub accounts.
4. Try saying or typing:
   - *"Create a 5-year SaaS financial model on my desktop"*
   - *"Do deep research on solid-state battery manufacturing breakthroughs and compile into Word and PDF on my desktop"*
   - *"Summarize my morning emails and prepare a brief"*
   - *"Open Excel and highlight all sales above 50,000"*

---

### 5. Running Verification & Comprehensive Test Suite

NEXUS includes an automated test matrix covering database isolation, connector integrations, schedule parsing, Office automation, and speech transcription:

```bash
# Run backend test suite (Optimization, Ground-Truth Verification, Email Composer, Excel Copilot)
pytest backend/tests/test_optimization.py backend/tests/test_email_composer.py backend/tests/test_excel_target_refactor.py

# Run the comprehensive test matrix (24 test suites)
pytest tests/

# Verify frontend TypeScript compilation
npm run typecheck

# Verify production build bundle
npm run build:ci
```

---

## Continuous Integration (CI Pipeline)

The project includes an automated GitHub Actions CI pipeline configured in [`.github/workflows/ci.yml`](https://github.com/Sagnify/nexus/actions/workflows/ci.yml):

- **Frontend CI (`ubuntu-latest`)**:
  - Node.js 20.x dependency caching
  - Clean dependency installation (`npm ci`)
  - TypeScript typechecking (`npm run typecheck`)
  - Vite and Electron bundle build verification (`npm run build:ci`)
- **Backend CI (`windows-latest`)**:
  - Python 3.12 environment with pip caching
  - Full dependency installation (`pip install -r requirements.txt`)
  - Alembic migration integrity verification (`alembic heads`)
  - Unit test suite execution covering authentication, database isolation, recommendations, Word automation, and media player tools.

---

## 👥 Technology Stack & Ecosystem

NEXUS was engineered as a high-performance agent runtime designed to demonstrate what real-world desktop intelligence should feel like: fast, deterministic, safe, and verifiable.

- **Agent Core & Orchestration**: LangGraph, LangChain, FastAPI, Python 3.12, Pydantic v2
- **Ultra-Fast Inference**: Groq LPUs (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`), Google DeepMind Gemma 3
- **Desktop Runtime**: Electron 34, React 18, TypeScript 5.7, Tailwind CSS 3.4, Lucide Icons
- **Office & Document Automation**: `pywin32` (Win32 COM), `openpyxl`, `python-docx`, `python-pptx`, `Pillow`
- **Research & Web Automation**: `httpx`, `beautifulsoup4`, Chrome DevTools Protocol (CDP), WebSockets
- **Speech Engine**: Microsoft Edge Neural Speech API (`edge_tts`), Groq Whisper Turbo (`whisper-large-v3-turbo`)
- **Database Layer**: PostgreSQL (Neon Serverless), SQLAlchemy 2.0 (AsyncIO), Alembic

---

<div align="center">
  <sub>Built with precision for autonomous productivity. Distributed under the MIT License.</sub>
</div>
