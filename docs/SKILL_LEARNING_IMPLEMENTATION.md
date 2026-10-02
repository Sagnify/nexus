# NEXUS: Personalized Demonstration-Driven Skill Learning System
## Complete Architectural Blueprint and Phased Implementation Guide (Refined & Hardened)

---

# 1. Executive Summary

The **Personalized Demonstration-Driven Skill Learning System** elevates NEXUS from a purely reactive, ad-hoc planning agent into an adaptive operating-system companion. By observing human demonstrations across web browsers and desktop applications, NEXUS compiles observed interaction streams into structured, reusable, and parameterized **Skills**. When an authenticated user requests a matching workflow in the future, NEXUS retrieves the skill, validates execution feasibility, and replays the verified recipe with high determinism.

### Key Architectural Tenets

1. **Dual-Engine Coexistence**: Preserves strict separation between:
   - **Browser Automation Engine**: Governed by the NEXUS Chrome Companion Extension utilizing live DOM tree inspection and Chrome DevTools Protocol (`chrome.debugger`) for synthetic native input injection.
   - **Desktop Automation Engine**: Governed by Win32 window focus management, semantic Office APIs (`python-docx`, `openpyxl`), and PyAutoGUI input synthesis with selective VLM/OCR perceptual verification.
   - **Cross-Engine Handoff**: Coordinates hybrid workflows (e.g., downloading a report in the browser, verifying file completion, and opening/formatting in desktop Excel) through explicit state synchronization contracts.
2. **Semantic Compilation (Not Coordinate Replay)**: Demonstrations are never stored as brittle screen coordinates. The semanticizer translates raw interactions into multi-attribute selector bundles (`data-testid`, ARIA labels, semantic roles, IDs, CSS paths, relative XPaths, and text anchors), dynamic parameter templates (`{{variable}}`), formal preconditions, and verifiable postconditions.
3. **Rigorous Demonstration Safety & Privacy**: Continuous background recording is prohibited. Observation is gated behind explicit user-controlled sessions with active visual badges, automatic sensitive field redaction (passwords, payment cards, OTPs), tab/window scope isolation, and ephemeral recording buffers.
4. **Realistic, Multi-Stage Fast-Path Matching**: Replaces naive "<1ms guarantees" with a measurable performance target (<15ms indexed lookup, <60ms semantic evaluation). Enforces a multi-stage validation gate (intent classification, parameter extractability, environment readiness, precondition feasibility, and ambiguity resolution) before bypassing the LLM planner. Unmatched or ambiguous queries gracefully fall back to NEXUS's standard ReAct planning engine.
5. **Deterministic Checkpointing & Self-Healing Runtime**: Replays track execution checkpoints, verify preconditions before each step, retry only safe/idempotent actions, fall back across selector bundles, and trigger guided human recovery upon irrecoverable failure.
6. **Skill Health & Lifecycle Management**: Tracks execution telemetry (successes, failures, recoveries, selector degradation). Automatically flags degraded skills, suspends repeatedly failing workflows, prevents broken auto-replay, and provides a guided review/rollback workflow.
7. **Strict Account-Based Isolation**: Skills and execution telemetry are owned exclusively by authenticated Firebase users and stored in PostgreSQL with cascading constraints. Guest users retain standard ad-hoc LLM planning but are barred from persistent skill recording, storage, or execution.

---

# 2. Existing Architecture & Component Audit

Every proposed modification builds directly upon verified components in the existing NEXUS codebase. Below is the ground-truth audit of existing interfaces versus proposed changes:

| Component / Subsystem | Verified File Path | Verified Existing Functionality | Proposed System Role & Modifications | Validation & Verification Method |
| :--- | :--- | :--- | :--- | :--- |
| **Agent State** | [`backend/agent/state.py`](file:///d:/Codes/nexus/backend/agent/state.py) | `NexusState(TypedDict)` containing `plan`, `current_step`, `execution_history`, `active_target`, `goal_achieved`. | Add `skill_id: Optional[str]`, `skill_version: Optional[int]`, `is_replay_mode: bool`, `resolved_params: dict`, `execution_checkpoints: list[dict]`. | State schema validation unit tests; verify backward compatibility with existing LangGraph nodes. |
| **Intent Classifier** | [`backend/agent/nodes/intent.py`](file:///d:/Codes/nexus/backend/agent/nodes/intent.py) | Classifies user input into categories (`web_automation`, `file_op`, `shell`, etc.) and detects fast-paths for media/search. | Add intent recognition for `"teach_mode"` / `"teach_start"` and stage-1 trigger phrase matching against user's active skills. | Pytest suite validating prompt routing to teach mode vs replay vs ad-hoc planning. |
| **Planner Node** | [`backend/agent/nodes/planner.py`](file:///d:/Codes/nexus/backend/agent/nodes/planner.py) | Generates multi-step `PlanStep` sequences via LLM reasoning models or regex fallback plans. | Intercept verified skill matches; convert compiled skill steps into pre-validated `PlanStep` sequence, skipping LLM planner prompt. | Measure plan dispatch latency; verify identical `PlanStep` schema contract with executor. |
| **Executor Node** | [`backend/agent/nodes/executor.py`](file:///d:/Codes/nexus/backend/agent/nodes/executor.py) | Dispatches tools sequentially or iteratively in adaptive ReAct loop. | Inject parameter substitution into tool arguments; record step execution checkpoints and track idempotent retry states. | Integration tests executing browser and desktop steps with mocked parameter bindings. |
| **Evaluator Node** | [`backend/agent/nodes/evaluator.py`](file:///d:/Codes/nexus/backend/agent/nodes/evaluator.py) | Verifies step outcome via DOM snapshot diffing, CLI returncodes, and visual assertions. | Evaluate compiled skill postconditions; log telemetry metrics (success, selector degradation, failure) to database repository. | Assert postcondition validation against synthetic passing and failing DOM/desktop states. |
| **Browser Extension Bridge** | [`backend/agent/tools/web_automation/extension_bridge.py`](file:///d:/Codes/nexus/backend/agent/tools/web_automation/extension_bridge.py) | WebSocket bridge managing communication between NEXUS backend and Chrome Extension (`ws://127.0.0.1:8000/ws/extension`). | Add message handlers for `teach_event` telemetry and commands for `start_recording`, `pause_recording`, `stop_recording`. | Mock WebSocket test harness asserting bidirectional telemetry and command delivery. |
| **Browser Content Script** | [`extension/content.js`](file:///d:/Codes/nexus/extension/content.js) | Injects DOM inspection scripts, Shadow DOM overlays, and virtual cursor visualizers. | Add scoped event listeners (`click`, `input`, `change`, `keydown`) during active teach sessions; attach multi-attribute selector generator. | Chrome extension manual & automated headless tests verifying selector bundle extraction and input masking. |
| **Browser Background Service** | [`extension/background.js`](file:///d:/Codes/nexus/extension/background.js) | Manages Chrome debugger CDP sessions, native mouse/keyboard dispatch, tab management. | Gate recording to active tab ID; forward redacted interaction events to `extension_bridge.py`; manage recording state badge. | Test tab switching behavior to ensure background tabs are not recorded. |
| **Desktop Hardware Tools** | [`backend/agent/tools/gui/hardware.py`](file:///d:/Codes/nexus/backend/agent/tools/gui/hardware.py) | `ActivateWindowTool`, `ClickMouseTool`, `TypeTextTool`, `PressKeyTool`. | Serve as execution primitives during desktop skill replay; add window focus validation prior to dispatch. | Unit tests verifying window handle activation and guarded input dispatch. |
| **Target Discovery** | [`backend/core/targets.py`](file:///d:/Codes/nexus/backend/core/targets.py) | `TargetManager` tracks running applications, window titles, and targets (Word, Excel, Terminal). | Used by desktop observer to filter and tag user demonstrations to the active target process. | Unit tests asserting event tagging matches foreground PID and application name. |
| **Database Models** | [`backend/database/models.py`](file:///d:/Codes/nexus/backend/database/models.py) | SQLAlchemy 2.0 models for `User`, `Conversation`, `Message`, `Task`, `TaskEvent`. | Add `Skill`, `SkillVersion`, and `SkillExecution` models with foreign key constraints, indexes, and relationship cascades. | Alembic migration check and database integration test suite against PostgreSQL. |
| **Firebase Auth Gate** | [`backend/core/firebase_auth.py`](file:///d:/Codes/nexus/backend/core/firebase_auth.py) | Verifies Bearer JWT tokens; resolves to PostgreSQL `User` record via `get_current_user`. | Enforce `Depends(get_current_user)` on all skill API routes; enforce strict user ID ownership filtering in repository queries. | Security test suite asserting 401 on missing token, 403 on guest token, and 404/403 on cross-tenant ID access. |
| **Frontend Auth Context** | [`src/context/AuthContext.tsx`](file:///d:/Codes/nexus/src/context/AuthContext.tsx) | Manages Firebase user session, auth state, and `isGuest` flag. | Guard Teach Mode toggle and Skill Library navigation so they are disabled/hidden for guest users. | Vitest component tests ensuring guest users cannot activate teach controls. |
| **Spotlight Interface** | [`src/components/SpotlightBar.tsx`](file:///d:/Codes/nexus/src/components/SpotlightBar.tsx) | Omni-bar input for user prompts, model selection, and execution status. | Add Teach Mode toggle, active recording HUD pill, matched skill indicator, and parameter prompt modal. | Frontend UI component test verifying visual transitions across idle, recording, and replay states. |

---

# 3. Updated Dual-Engine Architecture & Cross-Engine Contracts

NEXUS maintains two physically distinct automation execution engines coordinated under a unified skill definition.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AUTHENTICATION GATE                                  │
│                 Firebase Auth (Client) ──Bearer JWT──► backend/core/firebase_auth      │
│                     [Verified User: UID / PostgreSQL User ID]                          │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                    ┌───────────────────────┴────────────────────────┐
                    ▼                                                ▼
     [TEACH / DEMONSTRATION MODE]                        [EXECUTION / REPLAY MODE]
                    │                                                │
        ┌────────────┴────────────┐                      ┌────────────┴────────────┐
        ▼                         ▼                      ▼                         ▼
 ┌──────────────┐          ┌──────────────┐       ┌──────────────┐          ┌──────────────┐
 │   Browser    │          │   Desktop    │       │  Skill Store │          │ Intent &     │
 │ Demonstration│          │ Demonstration│       │  (Postgres)  │          │ Multi-Stage  │
 │ (Extension)  │          │(Win32/Target)│       └──────┬───────┘          │ Matcher      │
 └──────┬───────┘          └──────┬───────┘              │                  └──────┬───────┘
        │                         │                      └───────────┬─────────────┘
        ▼                         ▼                                  ▼
 ┌────────────────────────────────────────┐                 ┌─────────────────┐
 │       Scoped Observation Collector     │                 │ Execution Router│
 │  - Tab/Window scope filtering          │                 │ - Browser Driver│
 │  - Sensitive field & input redaction   │                 │ - Desktop Driver│
 │  - Ephemeral session memory buffer     │                 │ - Mixed Handoff │
 └──────────────────┬─────────────────────┘                 └────────┬────────┘
                    ▼                                                │
 ┌────────────────────────────────────────┐                          ▼
 │        Action Semanticizer             │                 ┌─────────────────┐
 │  - Noise & jitter reduction            │                 │ Checkpoint &    │
 │  - Multi-attribute selector bundling   │                 │ Runtime Engine  │
 │  - Dynamic parameter identification   │                 └────────┬────────┘
 └──────────────────┬─────────────────────┘                          │
                    ▼                                                ▼
 ┌────────────────────────────────────────┐                 ┌─────────────────┐
 │          Skill Compiler                │                 │   Evaluator &   │
 │  - Pre/Post-condition synthesis        │                 │ Self-Healing    │
 │  - Schema & integrity validation       │                 │ Recovery        │
 │  - Human Review Modal & Approval       │                 └────────┬────────┘
 └──────────────────┬─────────────────────┘                          ▼
                    ▼                                       ┌─────────────────┐
 ┌────────────────────────────────────────┐                 │ Health Monitor  │
 │    PostgreSQL Cloud Skill Store        │                 │ - Telemetry log │
 │  - `skills` & `skill_versions` tables  │                 │ - Auto-suspend  │
 └────────────────────────────────────────┘                 └─────────────────┘
```

### Browser Automation Engine Specification
- **Substrate**: Chrome Companion Extension connecting via local authenticated WebSocket to `backend/agent/tools/web_automation/extension_bridge.py`.
- **Perception**: Live DOM tree traversal, computed styles, bounding client rects, accessibility tree roles, and ARIA labels.
- **Actuation**: Native input event dispatch via Chrome DevTools Protocol (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`) through attached `chrome.debugger` session, guaranteeing event propagation across single-page applications and complex shadow roots.
- **Isolation Guarantee**: Operates strictly within browser tabs; cannot access or manipulate host operating system windows.

### Desktop Automation Engine Specification
- **Substrate**: Win32 window APIs (`win32gui`, `win32process`), Python semantic application APIs (`python-docx`, `openpyxl`), and PyAutoGUI hardware injection.
- **Perception**: Windows Accessibility / UI Automation tree, window handle enumeration, and selective screen capture via `backend/agent/tools/gui/screen.py` passed to OCR or VLM for visual grounding.
- **Actuation**: Foreground window activation (`SetForegroundWindow`), standard hotkey chords, mouse clicks, and structured file generation via shell.
- **Isolation Guarantee**: Operates strictly on host desktop processes identified by `TargetManager`; never injects synthetic DOM events into Chrome tabs.

### Cross-Engine Handoff & Synchronization Contract
Hybrid workflows (e.g., extracting data from a web portal and compiling it into a local Word or Excel document) must adhere to explicit handoff contracts:
1. **File Readiness Checkpoint**: When transitioning from browser download to desktop processing:
   - The browser step must emit a target download event containing expected filename patterns.
   - The runtime suspends execution until the file exists on disk, its file size is stable (>0 bytes and unchanging for at least 1.0s), and any browser temporary extensions (e.g., `.crdownload`, `.tmp`) have resolved.
2. **Window Focus Handoff**:
   - Before dispatching desktop steps, the runtime explicitly verifies the target window handle (`HWND`), brings it to the foreground via `win32gui.SetForegroundWindow`, and pauses 300ms for UI settling.
3. **Partial Failure Isolation**:
   - If a desktop step fails following successful browser extraction, the runtime does not re-run the browser extraction. It resumes execution from the File Readiness Checkpoint using the verified local artifact.

---

# 4. Demonstration Recording Safety & Privacy Design

To prevent accidental data leaks or unauthorized system monitoring, recording is strictly gated by an explicit, auditable security layer.

### Recording Lifecycle States
Demonstration observation follows a strict finite state machine:
```
[IDLE] ──(User Clicks 'Teach NEXUS')──► [ARMED] ──(Target App Focused)──► [RECORDING]
                                                                              │   ▲
                                                                (Pause Click) │   │ (Resume Click)
                                                                              ▼   │
                                                                           [PAUSED]
                                                                              │
                                                            (User Clicks Stop)│
                                                                              ▼
[IDLE] ◄──(Discard / Reject)────── [COMPILING & REVIEW] ──(Approved)──► [PERSISTED]
```

### Browser Telemetry Collection Safety (`extension/content.js` & `background.js`)
1. **Explicit Session Gating**:
   - Event listeners are **never** attached to DOM elements during normal browsing.
   - When the user starts Teach Mode, the backend issues `start_teach_mode` with a specific `session_id` and target `tab_id`. Only the designated tab attaches listeners.
2. **Visual Recording Indicator**:
   - An immutable, high-contrast banner is injected into the top of the viewport using an isolated closed Shadow DOM root (`nexus-teach-indicator`). It displays:
     - Blinking red recording indicator.
     - Active session duration timer.
     - Scope indicator: `"Recording Tab: [Title]"`.
     - Direct controls: `[Pause]`, `[Resume]`, `[Finish Demonstration]`, `[Cancel/Discard]`.
3. **Sensitive Input Redaction**:
   - Any input element with `type="password"`, `type="hidden"`, or attributes matching `autocomplete="cc-*"`, `autocomplete="one-time-code"`, `data-private`, or containing `pin`, `cvv`, `ssn`, `card` in `id`/`name`/`aria-label` is **instantly redacted**.
   - Keystrokes inside redacted elements emit `[REDACTED_SECRET]` tokens.
   - The selector bundle records element identity without persisting actual secret values.
4. **Selector Bundle Generator**:
   - Emits a resilient multi-attribute descriptor bundle:
```javascript
function generateSelectorBundle(element) {
    return {
        testId: element.getAttribute('data-testid') || element.getAttribute('data-cy') || null,
        ariaLabel: element.getAttribute('aria-label') || null,
        role: element.getAttribute('role') || element.tagName.toLowerCase(),
        name: element.name || null,
        id: element.id && !element.id.match(/\d{4,}/) ? `#${element.id}` : null,
        cssPath: getResilientCssPath(element),
        xpath: getRelativeXPath(element),
        textAnchor: (element.innerText || '').trim().slice(0, 40) || null
    };
}
```
5. **Tab & Origin Guarding**:
   - Navigation away from the initial demonstration origin triggers a confirmation prompt in the recording overlay. If the user navigates to an untrusted domain, recording is automatically paused.

### Desktop Telemetry Collection Safety (`backend/agent/skills/desktop_observer.py`)
1. **Target Window & PID Pinning**:
   - Observation utilizes Win32 hooks (`SetWinEventHook` with `EVENT_SYSTEM_FOREGROUND`).
   - Recording is pinned strictly to the PID and HWND of the application selected when teaching began (e.g., `EXCEL.EXE`).
   - If the user switches focus to another application (e.g., Slack, browser, system settings), desktop event capture **drops all events** until the target application is refocused.
2. **Credential & System Dialog Masking**:
   - Detects Windows security dialogs (`Credential Dialog`, `User Account Control`, `Windows Security`).
   - Keystroke hooks are immediately suspended while system security dialogs or password fields are active.
3. **Noise Filtering at Ingestion**:
   - Mouse moves without clicks are dropped.
   - Keystrokes are debounced and grouped into coherent text-entry blocks rather than individual keydown events.

### Data Retention & Artifact Privacy
- **Zero Raw Recording Persistence**: Video files or continuous keystroke logs are **never** stored on disk.
- **Ephemeral In-Memory Buffer**: Demonstration events reside only in a volatile in-memory queue (`DemonstrationBuffer`) during the active session.
- **Automatic Purge**: Upon compilation or user cancellation, the raw event buffer is wiped from memory immediately. Only the approved, compiled JSON workflow is persisted.

---

# 5. Database Schema & Lifecycle Rules

The persistence architecture extends `backend/database/models.py` with strict foreign key constraints, cascading deletion, compound indexes, and health tracking.

```python
# Proposed Schema Additions to backend/database/models.py

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
import uuid

class Skill(Base):
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=False, default="general", index=True)
    environment = Column(String(32), nullable=False, default="mixed") # "browser" | "desktop" | "mixed"

    trigger_phrases = Column(JSONB, nullable=False, default=list) # ["download monthly invoices", "get stripe billing"]
    parameters_schema = Column(JSONB, nullable=False, default=list) 
    # [{"name": "billing_month", "type": "string", "required": True, "description": "Target month"}]

    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_draft = Column(Boolean, default=False, nullable=False)
    current_version = Column(Integer, default=1, nullable=False)

    # Health & Reliability Metrics
    health_status = Column(String(32), default="healthy", nullable=False) # "healthy" | "degraded" | "suspended"
    consecutive_failures = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    recovery_count = Column(Integer, default=0, nullable=False)
    selector_failure_count = Column(Integer, default=0, nullable=False)
    verification_failure_count = Column(Integer, default=0, nullable=False)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)
    last_failed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="skills")
    versions = relationship("SkillVersion", back_populates="skill", cascade="all, delete-orphan", order_by="desc(SkillVersion.version_number)")
    executions = relationship("SkillExecution", back_populates="skill", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_skills_user_active_health", "user_id", "is_active", "health_status"),
        Index("ix_skills_user_name_unique", "user_id", "name", unique=True),
    )


class SkillVersion(Base):
    __tablename__ = "skill_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id = Column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)

    steps_json = Column(JSONB, nullable=False) # List of validated SemanticAction objects
    preconditions = Column(JSONB, nullable=False, default=list) # Initial environment checks
    postconditions = Column(JSONB, nullable=False, default=list) # Final workflow success checks
    change_summary = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    skill = relationship("Skill", back_populates="versions")

    __table_args__ = (
        Index("ix_skill_version_unique", "skill_id", "version_number", unique=True),
    )


class SkillExecution(Base):
    __tablename__ = "skill_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id = Column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String(32), nullable=False) # "completed" | "failed" | "recovered"
    parameters_used = Column(JSONB, nullable=False, default=dict)
    step_results = Column(JSONB, nullable=False, default=list)
    recovery_attempts = Column(JSONB, nullable=False, default=list)
    error_message = Column(Text, nullable=True)
    failed_step_index = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    executed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    skill = relationship("Skill", back_populates="executions")

    __table_args__ = (
        Index("ix_skill_executions_user_skill", "user_id", "skill_id", "executed_at"),
    )
```

### Version Lifecycle Rules
1. **Immutability of Versions**: Once a `SkillVersion` is written to the database, its `steps_json` is frozen and never updated in place. Any edits or repairs increment `Skill.current_version` and create a new `SkillVersion` record.
2. **Optimistic Locking**: Every mutation requires passing `expected_version`. If a concurrent update has bumped the version, the transaction aborts with HTTP 409 Conflict.
3. **Rollback Semantics**: Reverting to version $N$ creates a new version $M = \text{current\_version} + 1$ with steps cloned from version $N$, ensuring the audit log remains purely append-only.
4. **User Deletion Cascade**: Deleting a user cascade-deletes all associated skills, versions, and execution records (`ondelete="CASCADE"`).

---

# 6. Semantic Compilation & Validation Pipeline

The compilation engine bridges raw interaction telemetry into resilient automation specifications.

```
Raw Telemetry Event Stream 
       │
       ▼
[Noise & Jitter Filter] ──────► Drops micro-moves, transient focus, redundant clicks
       │
       ▼
[Action Semanticizer]   ──────► Elevates inputs to high-level actions (click, type, navigate)
       │
       ▼
[Parameter Generalizer] ──────► Maps variable values (dates, terms) to {{param}} templates
       │
       ▼
[Condition Synthesizer] ──────► Synthesizes URL checks, element visibility, and file presence
       │
       ▼
[Pydantic Schema Gate]  ──────► Enforces strict structural typing and rejection of malformed drafts
       │
       ▼
[User Review Modal]     ──────► Human inspection, parameter renaming, secret masking, approval
```

### 1. Semantic Action Representation Schema
Every step in `steps_json` must adhere strictly to the `SemanticAction` schema:
```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any

class SelectorBundle(BaseModel):
    test_id: Optional[str] = None
    aria_label: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    id_selector: Optional[str] = None
    css_path: str
    xpath: str
    text_anchor: Optional[str] = None

class Precondition(BaseModel):
    check_type: Literal["url_contains", "element_visible", "window_active", "file_exists"]
    target: str
    timeout_seconds: float = 5.0

class Postcondition(BaseModel):
    check_type: Literal["url_changed", "element_hidden", "element_appeared", "file_created"]
    target: str
    timeout_seconds: float = 8.0

class SemanticAction(BaseModel):
    step_id: str
    title: str
    action_type: Literal[
        "browser_navigate", "browser_click", "browser_type", "browser_select", 
        "desktop_focus", "desktop_click", "desktop_type", "desktop_hotkey",
        "file_verify_download", "wait_condition"
    ]
    execution_engine: Literal["browser", "desktop", "system"]
    target_app: Optional[str] = None
    selector_bundle: Optional[SelectorBundle] = None
    value_template: Optional[str] = None # e.g. "Report-{{year}}-{{month}}"
    parameter_references: List[str] = Field(default_factory=list) # ["year", "month"]
    is_idempotent: bool = False
    preconditions: List[Precondition] = Field(default_factory=list)
    postconditions: List[Postcondition] = Field(default_factory=list)
    failure_behavior: Literal["retry_with_fallback", "abort_to_human", "skip"] = "retry_with_fallback"
```

### 2. Parameter Generalization Engine (`backend/agent/skills/compiler.py`)
- **Token Diffing**: Compares the user prompt that initiated teaching (e.g., `"Download invoice for March 2026"`) against strings entered during demonstration (e.g., `"March 2026"`).
- **Entity Detection**: Matches dynamic data patterns:
  - Dates: `YYYY-MM-DD`, `Month YYYY`, `DD/MM/YYYY`.
  - Email addresses: `[\w\.-]+@[\w\.-]+\.\w+`.
  - File paths & names: `*.xlsx`, `*.csv`, `*.pdf`.
  - Search queries and customer IDs.
- **Template Synthesis**: Replaces hardcoded literals with `{{parameter_name}}` and populates `parameters_schema` with parameter types and human-readable descriptions.
- **Sensitive Value Scrubber**: Strings matching credentials, tokens, or private patterns are scrubbed from templates and replaced with explicit user-prompt requirements.

### 3. Formal Schema Validation
Before saving any skill draft or version to PostgreSQL:
- The compiler validates `steps_json` against `List[SemanticAction]`.
- Rejects any action with undefined parameter references (references missing from `parameters_schema`).
- Rejects steps with incompatible engine mappings (e.g., `browser_click` mapped to `desktop` engine).
- Ensures at least one valid selector exists in every browser `selector_bundle`.

---

# 7. Skill Matching & Retrieval Architecture

The matching engine reconciles incoming user requests against the user's personal skill store with high accuracy and fast response times.

### Latency Profile & Design Objectives
- **Target Performance**:
  - Exact phrase match (Tier 1): **< 15ms**.
  - Semantic vector similarity & context filter (Tier 2): **< 60ms**.
  - Bypassing the LLM planner saves **1.5s to 3.5s** of token generation overhead on every replay.
- **No Blanket Guarantees**: Matching latency is monitored as a measured service metric; complex parameter resolutions gracefully adapt without failing.

### Multi-Stage Matching Pipeline

```
User Prompt Entered in Spotlight
               │
               ▼
┌────────────────────────────────────────────────────────┐
│ Stage 1: Authenticated User Isolation                  │
│ Filter: WHERE user_id = :current_user AND is_active    │
└──────────────────────────────┬─────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────┐
│ Stage 2: Normalized Trigger Match (Fastest Path)       │
│ Checks exact match against normalized trigger_phrases   │
└──────────────────────────────┬─────────────────────────┘
        │ (Matched)            │ (No exact match)
        │                      ▼
        │        ┌────────────────────────────────────────────────────────┐
        │        │ Stage 3: Semantic Similarity & Intent Filter           │
        │        │ Cosine similarity between prompt and skill embeddings  │
        │        │ (Requires similarity >= 0.88 to proceed)               │
        │        └─────────────────────┬──────────────────────────────────┘
        │                              │ (Passed threshold)
        ▼                              ▼
┌────────────────────────────────────────────────────────┐
│ Stage 4: Parameter Extractability Verification         │
│ Can all required parameters be parsed from the prompt  │
│ or active context? (If missing, flag for user prompt)  │
└──────────────────────────────┬─────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────┐
│ Stage 5: Environment & Context Compatibility Check     │
│ Are target apps/URLs reachable or already active?      │
│ Check if skill is marked 'suspended' or 'degraded'     │
└──────────────────────────────┬─────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────┐
│ Stage 6: Ambiguity Resolution Gate                     │
│ - Single distinct match (> 0.88)  ──► Dispatch Replay  │
│ - Competing matches (diff < 0.05) ──► Prompt User      │
│ - Sub-threshold (< 0.88)          ──► Fall back to LLM │
└────────────────────────────────────────────────────────┘
```

### Safeguards Against False Autonomy
- **Pure Semantic Similarity Cannot Authorize Execution**: An embedding score alone (> 0.88) is insufficient. Execution is blocked if:
  1. The skill is currently `suspended` due to repeated health failures.
  2. Required parameters cannot be resolved from the prompt or user input.
  3. Preconditions fail the feasibility probe.
- **Ambiguity Clarification**: If two skills match with similar confidence (e.g., `"Download Stripe receipts"` vs `"Download Stripe monthly payout report"`), NEXUS displays a lightweight clarification chip in the Spotlight bar asking the user to choose, rather than making an arbitrary guess.

---

# 8. Execution Runtime & Recovery Strategy

The execution runtime (`backend/agent/skills/runtime.py`) turns compiled steps into actions with checkpointing and self-healing.

### Execution Tracking & Checkpointing
Every skill execution records a stateful ledger in `SkillExecution`:
- `current_step_index`: Pointer to currently executing `SemanticAction`.
- `completed_checkpoints`: Array of successfully verified step outcomes.
- `step_results`: Granular log of execution duration, selector used, and outcome.
- `recovery_attempts`: Log of fallbacks or retries executed.

### Failure Handling & Self-Healing Matrix

| Failure Mode | Detection Signal | Automated Self-Healing Response | Terminal Action |
| :--- | :--- | :--- | :--- |
| **Missing DOM Element / Stale Selector** | Primary selector query returns null after 3s timeout. | Cascade through `SelectorBundle` in order: `testId` $\to$ `ariaLabel` $\to$ `name` $\to$ `id` $\to$ `xpath` $\to$ `textAnchor`. | If all selectors fail, take DOM snapshot, mark step failed, and invoke visual locator or prompt user. |
| **Desktop Application Focus Loss** | Active foreground window HWND does not match expected target process. | Call `win32gui.SetForegroundWindow(expected_hwnd)`; re-check focus after 300ms. | If window was closed, attempt to re-launch target application or abort. |
| **Unexpected URL / Navigation Drift** | Precondition `url_contains` check fails. | Check if current URL matches an expected authentication or redirection step; wait up to 4s. | If off-target, navigate back to expected URL or request user intervention. |
| **File Download Timeout** | Downloaded artifact not found within `timeout_seconds`. | Check default browser download directory for matching pattern; inspect extension download status API. | Prompt user: "File download not detected. Retry or point to file." |
| **Failed Postcondition Assertion** | Verification condition fails after step execution. | If action is marked `is_idempotent=True`, retry step once. | If non-idempotent (e.g. "Submit Payment"), **never blind-retry**; pause and request human verification. |

### Idempotency & Safe Recovery Rules
1. **Never Re-Execute Side-Effect Actions**: Actions marked with `is_idempotent: false` (e.g., clicking `"Pay Now"`, `"Delete"`, `"Send Email"`, or executing destructive terminal commands) are strictly blocked from automatic retries upon postcondition failure. The runtime immediately pauses and requests human confirmation.
2. **Resume from Checkpoint**: In mixed workflows, if failure occurs at Step 6 (Desktop Excel Formatting) after Steps 1-5 (Browser Ingestion) have succeeded, recovery resumes strictly from Step 6. Steps 1-5 are never repeated.

---

# 9. Skill Health Management & Guided Repair

Skills can degrade over time due to website redesigns, DOM class updates, or application changes. NEXUS actively tracks and repairs failing skills.

### Health Classification Algorithm
Health status is evaluated automatically after every execution:
- **`healthy`**:
  - Success rate $\ge 85\%$ over the last 10 runs, AND
  - `consecutive_failures` $< 2$.
- **`degraded`**:
  - `consecutive_failures` == 2, OR
  - Primary selector failed on $\ge 50\%$ of recent runs (relying on fallbacks).
  - *Action*: Displays a yellow warning badge in UI; suggests skill maintenance.
- **`suspended`**:
  - `consecutive_failures` $\ge 3$, OR
  - Catastrophic non-idempotent verification failure.
  - *Action*: **Auto-replay is locked.** The skill will not execute automatically on prompt match. The user is prompted to repair or run via standard LLM planning.

### Guided Skill Repair Workflow
When a skill is flagged for repair:
1. **Step-Level Diagnostic**: NEXUS highlights the exact step and selector that failed, showing the historical screenshot or DOM snippet alongside the current live state.
2. **Interactive Re-Demonstration**: The user is invited to re-demonstrate *only the broken step* rather than re-recording the entire workflow.
3. **Visual Diff Inspection**:
   - The UI displays a side-by-side diff comparing `Version N` vs `Proposed Version N+1`.
4. **Mandatory Human Approval**: Repaired workflows are **never** auto-promoted to active status without explicit user confirmation.
5. **Instant Rollback**: If a repaired version introduces regressions, the user can click "Rollback to Version N" with zero data loss.

---

# 10. Frontend Integration & UI Workflow

The frontend implementation is developed incrementally alongside backend modules.

### 1. Spotlight Bar Enhancements ([`src/components/SpotlightBar.tsx`](file:///d:/Codes/nexus/src/components/SpotlightBar.tsx))
- **Teach Mode Toggle**: Accessible next to the model selector. Hidden/disabled for guest sessions.
- **Recording HUD**: When recording is active, the bar morphs into a persistent status pill:
  - Pulsing red recording dot.
  - Active session timer.
  - Scope badge (e.g., `"Scope: Chrome (Stripe Dashboard)"`).
  - Action buttons: `[Pause]`, `[Resume]`, `[Finish]`, `[Discard]`.
- **Replay Progress Indicator**: When a skill matches:
  - Displays a dedicated `Skill Matched: [Skill Name]` badge with current version.
  - Live progress stepper showing current step execution and recovery events.

### 2. Skill Review Modal (`src/components/SkillReviewModal.tsx`)
Triggered automatically when a demonstration is finished:
- **Workflow Inspector**: Visual step-by-step card list displaying action type, target element/window, and pre/postconditions.
- **Parameter Manager**: Table of detected dynamic parameters with editable names, default values, and data type selectors.
- **Sensitive Data Check**: Scans for suspected passwords or secrets; allows the user to redact or mask any field before persistence.
- **Save Actions**: `[Save as Active Skill]`, `[Save as Draft]`, or `[Discard]`.

### 3. Skill Library Panel (`src/components/SkillLibraryPanel.tsx`)
A dedicated panel in NEXUS settings:
- **Skill Overview Cards**: Filterable by category, environment, and health status (`Healthy`, `Degraded`, `Suspended`).
- **Detail View**:
  - Trigger phrase editor (add/remove activation phrases).
  - Version history table with side-by-side step diffing and one-click rollback.
  - Execution audit logs: duration, success rate, and failure history.
  - Manual controls: `[Test Run]`, `[Suspend]`, `[Reactivate]`, `[Repair]`, `[Delete]`.

### 4. Client State Hook (`src/hooks/useSkills.ts`)
- Manages cached skill listings, recording session state, optimistic health updates, and real-time execution telemetry via WebSocket notifications.

---

# 11. Security, Authorization & Tenancy Requirements

1. **Authentication Enforcement**:
   - Every endpoint under `/api/skills/*` requires a verified Firebase ID token via FastAPI's `Depends(get_current_user)`.
   - Anonymous/guest sessions receive HTTP 403 Forbidden on all persistent skill endpoints.
2. **Strict Multi-Tenant Row Isolation**:
   - Every database query in `SkillRepository` explicitly includes `WHERE user_id = :authenticated_user_id`.
   - Querying a skill ID belonging to another user returns HTTP 404 Not Found (preventing existence probing).
3. **Data Sanitization**:
   - Keystrokes inside password fields or financial inputs are masked prior to extension transmission.
   - Text inputs stored in `steps_json` are scrubbed of sensitive authorization tokens and session keys.
4. **Shell & Desktop Permission Sandboxing**:
   - Desktop steps requiring elevated privileges or system execution continue to route through NEXUS's existing `permission_gate.py` node.

---

# 12. Testing Strategy & Acceptance Criteria

### Unit Test Suite
- `test_selector_bundle_generation`: Verifies fallback hierarchy across mock HTML elements.
- `test_parameter_generalization`: Asserts date, email, and query pattern extraction into `{{param}}` templates.
- `test_action_schema_validation`: Confirms Pydantic rejection of malformed actions and missing parameters.
- `test_multi_stage_matcher`: Tests exact trigger hits, embedding thresholds, and ambiguity detection across sample query sets.
- `test_health_status_transitions`: Validates transition from `healthy` $\to$ `degraded` $\to$ `suspended` based on failure triggers.

### Integration Test Suite
- `test_authenticated_skill_crud`: Tests creation, versioning, rollback, and deletion of skills with mocked Firebase tokens.
- `test_cross_user_isolation`: Confirms User B cannot read, modify, or execute User A's skills.
- `test_extension_bridge_telemetry`: Simulates Chrome extension WebSocket connection and asserts interaction event ingestion.
- `test_desktop_observer_window_filter`: Simulates background window focus shifts and asserts out-of-scope event dropping.

### End-to-End Acceptance Lifecycle Test
1. **Teach**: User activates Teach Mode $\to$ navigates mock web portal $\to$ downloads CSV $\to$ opens desktop Excel $\to$ formats header $\to$ stops recording.
2. **Compile & Review**: Verifies generated workflow contains 1 browser step, 1 handoff checkpoint, and 1 desktop step with parameter `{{report_date}}`.
3. **Store**: Approves skill in review modal $\to$ persists to PostgreSQL.
4. **Retrieve**: Submits prompt `"Download report for April 2026 and format in Excel"` $\to$ asserts skill match $\to$ parameter extracted.
5. **Replay & Verify**: Replays workflow deterministically $\to$ verifies file creation and cell formatting $\to$ records successful execution log.

---

# 13. Revised Phased Implementation Roadmap

The implementation roadmap integrates backend persistence, observer pipelines, and frontend interfaces incrementally:

```
[Phase 1: Persistence] ─────► [Phase 2: Security & API] ─────► [Phase 3: Browser Capture + UI HUD]
                                                                          │
[Phase 5: Compilation + Review] ◄── [Phase 4: Desktop Capture] ───────────┘
               │
               ▼
[Phase 6: Multi-Stage Matcher] ──► [Phase 7: Runtime & Self-Healing] ──► [Phase 8: Library & Health]
```

### Phase 1: Database & Persistence Foundation
- **Deliverables**: SQLAlchemy models (`Skill`, `SkillVersion`, `SkillExecution`) added to `backend/database/models.py`; Alembic migration `002_skill_learning_tables.py`; `SkillRepository` in `backend/database/repositories/skill_repo.py`.
- **Dependencies**: Existing PostgreSQL session in `backend/database/session.py`.
- **Acceptance Criteria**: All models pass migration; CRUD operations verified with Pytest; foreign key cascades confirmed.

### Phase 2: Authentication Security & API Endpoints
- **Deliverables**: Authenticated FastAPI routes in `backend/api/skills.py` (`POST /`, `GET /`, `GET /{id}`, `PUT /{id}`, `POST /{id}/rollback`, `POST /{id}/execute`); registered in `backend/main.py`.
- **Dependencies**: Phase 1, `backend/core/firebase_auth.py`.
- **Acceptance Criteria**: Strict user isolation enforced; guest requests rejected with 403; cross-user ID tampering returns 404.

### Phase 3: Browser Demonstration Observation & Recording HUD
- **Deliverables**: Ingestion hooks in `extension/content.js` and `extension/background.js`; Shadow DOM recording indicator; telemetry handlers in `extension_bridge.py`; Teach Mode toggle in `SpotlightBar.tsx`.
- **Dependencies**: Phase 2 WebSocket bridge.
- **Acceptance Criteria**: Starting Teach Mode attaches listeners to designated tab only; sensitive inputs redacted; events streamed over WebSocket.

### Phase 4: Desktop Demonstration Observation
- **Deliverables**: `backend/agent/skills/desktop_observer.py` utilizing Win32 focus hooks and `TargetManager` process filtering.
- **Dependencies**: Phase 3 event pipeline, `backend/core/targets.py`.
- **Acceptance Criteria**: Window focus switches outside target process drop events; credential dialogs trigger immediate hook suspension.

### Phase 5: Skill Compiler, Semanticizer & Review Modal
- **Deliverables**: `semanticizer.py` (noise reduction), `compiler.py` (parameter extraction and schema validation); `SkillReviewModal.tsx` in frontend.
- **Dependencies**: Phases 3 and 4 observation buffers.
- **Acceptance Criteria**: Raw telemetry converted into validated `SemanticAction` steps; dynamic parameters templated; user approval commits skill to DB.

### Phase 6: Skill Matcher & LangGraph Planner Fast-Path
- **Deliverables**: Multi-stage matcher in `backend/agent/skills/matcher.py`; fast-path plan interception in `backend/agent/nodes/planner.py` and `intent.py`.
- **Dependencies**: Phase 1 repository, Phase 5 compiled schemas.
- **Acceptance Criteria**: Exact trigger match in <15ms; semantic match in <60ms; sub-threshold or ambiguous queries fall back to standard LLM planning.

### Phase 7: Execution Runtime, Checkpointing & Recovery
- **Deliverables**: `backend/agent/skills/runtime.py`; handoff contracts; evaluator assertion checks in `backend/agent/nodes/evaluator.py`.
- **Dependencies**: Phase 6 plan emission, `backend/agent/nodes/executor.py`.
- **Acceptance Criteria**: Successful step-by-step replay; fallback selectors resolve broken primary elements; non-idempotent actions never blind-retried.

### Phase 8: Skill Health Management, Repair & Library Panel
- **Deliverables**: Health evaluator service; guided repair workflow; `SkillLibraryPanel.tsx` in frontend settings.
- **Dependencies**: All prior phases.
- **Acceptance Criteria**: Auto-suspension after 3 consecutive failures; visual step diff viewer; one-click version rollback operational in UI.

---

# 14. Implementation Tracking Checklist

### Phase 1: Database & Persistence Foundation
- [ ] Add `Skill`, `SkillVersion`, and `SkillExecution` to [`backend/database/models.py`](file:///d:/Codes/nexus/backend/database/models.py).
- [ ] Generate and apply Alembic migration `migrations/versions/002_skill_learning_tables.py`.
- [ ] Implement `SkillRepository` with user-scoped queries in `backend/database/repositories/skill_repo.py`.
- [ ] Write unit tests for repository CRUD, pagination, and cascade deletion.

### Phase 2: Authentication Security & API Endpoints
- [ ] Implement `backend/api/skills.py` with full Pydantic request/response schemas.
- [ ] Enforce `Depends(get_current_user)` on all skill endpoints.
- [ ] Register `/api/skills` router in [`backend/main.py`](file:///d:/Codes/nexus/backend/main.py).
- [ ] Write security tests for guest blocking and cross-tenant access prevention.

### Phase 3: Browser Demonstration Observation & Recording HUD
- [ ] Implement selector bundle generator in [`extension/content.js`](file:///d:/Codes/nexus/extension/content.js).
- [ ] Implement sensitive input masking and shadow DOM recording overlay in `extension/content.js`.
- [ ] Implement active-tab scope gating and event forwarding in [`extension/background.js`](file:///d:/Codes/nexus/extension/background.js).
- [ ] Add `teach_event` handling to [`backend/agent/tools/web_automation/extension_bridge.py`](file:///d:/Codes/nexus/backend/agent/tools/web_automation/extension_bridge.py).
- [ ] Add Teach Mode toggle button and recording pill to [`src/components/SpotlightBar.tsx`](file:///d:/Codes/nexus/src/components/SpotlightBar.tsx).

### Phase 4: Desktop Demonstration Observation
- [ ] Implement `backend/agent/skills/desktop_observer.py` with Win32 foreground hook.
- [ ] Link desktop observer to [`backend/core/targets.py`](file:///d:/Codes/nexus/backend/core/targets.py) for process filtering.
- [ ] Implement credential dialog detection and keylogging suppression.
- [ ] Write unit tests verifying out-of-scope window event suppression.

### Phase 5: Skill Compiler, Semanticizer & Review Modal
- [ ] Implement `backend/agent/skills/semanticizer.py` (noise, jitter, double-click reduction).
- [ ] Implement `backend/agent/skills/compiler.py` with Pydantic `SemanticAction` schema and parameter templating.
- [ ] Create `src/components/SkillReviewModal.tsx` for parameter inspection and human approval.
- [ ] Wire `useSkills.ts` to submit reviewed skill drafts to `/api/skills`.

### Phase 6: Skill Matcher & LangGraph Planner Fast-Path
- [ ] Implement multi-stage matcher in `backend/agent/skills/matcher.py`.
- [ ] Integrate skill matching check in [`backend/agent/nodes/intent.py`](file:///d:/Codes/nexus/backend/agent/nodes/intent.py).
- [ ] Inject pre-compiled plan emission into [`backend/agent/nodes/planner.py`](file:///d:/Codes/nexus/backend/agent/nodes/planner.py).
- [ ] Write unit tests for trigger phrase matching, confidence thresholds, and ambiguity fallbacks.

### Phase 7: Execution Runtime, Checkpointing & Recovery
- [ ] Implement execution runtime and parameter resolver in `backend/agent/skills/runtime.py`.
- [ ] Add cross-engine file readiness synchronization check.
- [ ] Add selector bundle fallback iteration and idempotency guard.
- [ ] Connect step telemetry and assertion logging to [`backend/agent/nodes/evaluator.py`](file:///d:/Codes/nexus/backend/agent/nodes/evaluator.py).

### Phase 8: Skill Health Management, Repair & Library Panel
- [ ] Add automated health status updater (`healthy` / `degraded` / `suspended`) in repository.
- [ ] Implement version rollback endpoint (`POST /api/skills/{id}/rollback`).
- [ ] Create `src/components/SkillLibraryPanel.tsx` with health badges, version history, and execution logs.
- [ ] Implement guided single-step repair flow in frontend.
- [ ] Run full end-to-end integration and lifecycle test suite.
