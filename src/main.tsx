import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import type { Language } from "@elevenlabs/client";
import { Background, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Activity,
  Bot,
  CalendarDays,
  FileClock,
  LayoutDashboard,
  Phone,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  UsersRound,
  X,
} from "lucide-react";
import "./styles.css";

type Patient = {
  id: string;
  external_ref: string;
  first_name?: string;
  last_name?: string;
  name: string;
  initials: string;
  pathway: string;
  procedure: string;
  appointment: string | null;
  site: string | null;
  status: string;
  blocker: string | null;
  offer_status?: string | null;
  next_wake_at: string | null;
  phone: string | null;
  email: string | null;
  date_of_birth?: string | null;
  language: string;
  preference: string;
  note: string | null;
  constraints: Record<string, boolean>;
  active_call_action_id?: string | null;
  active_call_status?: string | null;
  timeline?: TimelineItem[];
  case_notes?: CaseNote[];
  agent_steps?: AgentStep[];
  case_documents?: CaseDocument[];
};
type CaseDocumentVersion = {
  id?: string;
  version: number | string;
  content?: string | Record<string, unknown>;
  provenance?: string;
  created_at?: string;
  created_by?: string;
};
type CaseDocument = {
  id: string;
  document_type?: string;
  type?: string;
  title: string;
  current_version?: number | string;
  version?: number | string;
  content?: string | Record<string, unknown>;
  provenance?: string;
  created_at?: string;
  updated_at?: string;
  versions?: CaseDocumentVersion[];
  version_history?: CaseDocumentVersion[];
};
type AgentDefinition = {
  key: string;
  name?: string;
  role?: string;
  status?: string;
  model?: string;
  active_version?: string | number;
  version?: string | number;
  instructions?: string;
  skill?: string;
  allowed_tools?: Array<string | { name?: string; description?: string }>;
  tools?: Array<string | { name?: string; description?: string }>;
  versions?: Array<Record<string, unknown>>;
  recent_executions?: AgentStep[];
  executions?: AgentStep[];
  last_run_at?: string;
};
type ElevenLabsStatus = {
  available?: boolean;
  configured?: boolean;
  agent_id?: string | null;
  agent_name?: string | null;
  agent_version?: string | number | null;
  version?: string | number | null;
  branch?: string | null;
  tools?: Array<string | { name?: string }>;
  attached_tools?: Array<string | { name?: string }>;
  phone_number?: string | null;
  phone_number_id?: string | null;
  webhook_status?: string | null;
  webhook_url?: string | null;
  last_sync_at?: string | null;
  last_error?: string | null;
  browser_available?: boolean;
  browser_authentication?: string | null;
  browser_session_endpoint?: string | null;
  telephone_transport?: string | null;
  simulated_outcomes?: boolean;
  message?: string | null;
};
type CaseHistoryPage = {
  steps: AgentStep[];
  events: TimelineItem[];
  documents: CaseDocument[];
  next_cursor?: string | null;
  has_more?: boolean;
};
type CaseNote = {
  id: string;
  category: string;
  text: string;
  language: string;
  source: string;
  created_at: string;
};
type ToolCall = {
  id: string;
  sequence: number;
  tool_name: string;
  tool_input: Record<string, unknown>;
  result_text: string;
  status: string;
  duration_ms?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
};
type AgentStep = {
  id: string;
  goal_id: string;
  kind: "AGENT_STEP";
  label: string;
  summary: string;
  mode: string;
  model: string | null;
  agent_role?: string | null;
  agent_spec_version_id?: string | null;
  agent_version?: string | number | null;
  fallback: boolean;
  stop_reason: string | null;
  decision: string | null;
  error: string | null;
  context: Record<string, unknown>;
  input_tokens: number;
  output_tokens: number;
  tool_calls: ToolCall[];
  created_at: string;
  duration_ms?: number | null;
  completed_at?: string | null;
};
type Slot = {
  id: string;
  time: string;
  site: string;
  procedure: string;
  state: string;
  duration_minutes: number;
};
type AppointmentType = {
  id: string;
  name: string;
  code?: string;
  procedure?: string;
  default_duration_minutes?: number;
  duration_minutes?: number;
  preparation_requirements?: string | null;
  preparation_note?: string | null;
};
type Metrics = {
  active: number;
  needs_attention: number;
  completed: number;
  open_slots: number;
  reminder_lead_hours?: number;
  reminder_policy?: string;
};
type DemoResetResponse = {
  operation_id: string;
  scope: "DEMO-*";
  changes: Record<string, number>;
  before_counts: Record<string, number>;
  after_counts: Record<string, number>;
  validation: { valid: boolean; violations: Array<{ code: string; ref: string; detail: string }> };
  retained_patients: string[];
};
type TimelineItem = {
  id: string;
  type: string;
  source: string;
  payload: Record<string, unknown>;
  created_at: string;
};
type Call = {
  id: string;
  goal_id: string;
  channel: string;
  direction: string;
  provider_id: string | null;
  summary: string | null;
  purpose?: string;
  outcome?: string;
  language?: string;
  created_at: string;
};
type ActivityItem = {
  id: string;
  goal_id: string;
  kind: string;
  label: string;
  summary: string;
  created_at: string;
  mode?: string;
  model?: string | null;
  fallback?: boolean;
  stop_reason?: string | null;
  decision?: string | null;
  error?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  tool_calls?: ToolCall[];
};
type OverseerWorkflowData = {
  active: boolean;
  run_state?: "RUNNING" | "NEXT_SCAN_SCHEDULED";
  decision_id?: string;
  updated_at?: string;
  slot?: { id: string; starts_at: string | null; procedure: string | null; site: string | null };
  policy?: string;
  rationale?: string;
  candidates: Array<{ rank: number; goal_id: string; patient_name: string; patient_external_ref?: string | null; score?: number; reasons: string[]; selected: boolean }>;
  selected_patient?: { goal_id: string; name: string; external_ref?: string | null };
  action?: { id: string; status: string; phone_status: string } | null;
  stages: Array<{ key: string; label: string; complete: boolean; active?: boolean; at?: string | null }>;
  iteration?: number;
  total_delegations?: number;
  iteration_started_at?: string;
  next_wake_seconds?: number;
  next_wake_at?: string;
  last_iteration_summary?: string;
  scan_stats?: { slots_checked?: number; compatible_patients?: number };
};

const emptyMetrics: Metrics = {
  active: 0,
  needs_attention: 0,
  completed: 0,
  open_slots: 0,
  reminder_lead_hours: 48,
  reminder_policy: "Reminder scheduled 48 hours before the appointment",
};
const fmt = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "Not booked";
const toolLabel = (name: string) => ({
  read_case_notes: "Read appointment notes",
  read_case_documents: "Read appointment documents",
  write_case_note: "Add versioned note",
  write_case_document: "Update appointment document",
  search_slots: "Find matching appointments",
  offer_slot: "Offer appointment",
  queue_patient_call: "Queue ElevenLabs call",
  wait_until: "Schedule next wake",
  request_human: "Pause case",
  complete_goal: "Complete appointment journey",
  end_step: "Finish agent step",
  nous_get_case: "Read appointment context",
  nous_list_offered_slots: "List offered appointments",
  nous_accept_slot: "Accept offered appointment",
  nous_reject_slot: "Decline offered appointment",
  nous_patient_constraint: "Record patient preference",
  nous_request_human: "Pause case",
  nous_verify_identity: "Verify date of birth",
  rank_released_slot: "Rank patients for released slot",
}[name] || name.replaceAll("_", " "));

const inFlightJson = new Map<string, Promise<unknown>>();
async function fetchJson<T>(path: string): Promise<T> {
  const current = inFlightJson.get(path);
  if (current) return current as Promise<T>;
  const request = fetch(path)
    .then((response) => {
      if (!response.ok) throw new Error("The database is not ready yet.");
      return response.json() as Promise<T>;
    })
    .finally(() => inFlightJson.delete(path));
  inFlightJson.set(path, request);
  return request;
}

let workflowCache: OverseerWorkflowData | null = null;
let workflowRequest: Promise<OverseerWorkflowData> | null = null;
function loadWorkflow(): Promise<OverseerWorkflowData> {
  if (workflowRequest) return workflowRequest;
  workflowRequest = fetchJson<OverseerWorkflowData>("/api/overseer/workflow")
    .then((workflow) => (workflowCache = workflow))
    .finally(() => { workflowRequest = null; });
  return workflowRequest;
}

function App() {
  const presenterMode = new URLSearchParams(window.location.search).get("demo") === "1";
  const [page, setPage] = useState<
    "dashboard" | "appointments" | "patients" | "capacity" | "calls" | "caseworkers" | "overseer"
  >("dashboard");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [appointmentTypes, setAppointmentTypes] = useState<AppointmentType[]>([]);
  const [appointmentTypesError, setAppointmentTypesError] = useState("");
  const [metrics, setMetrics] = useState(emptyMetrics);
  const [calls, setCalls] = useState<Call[]>([]);
  const [callsLoading, setCallsLoading] = useState(false);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState("");
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [agentsError, setAgentsError] = useState("");
  const [elevenLabs, setElevenLabs] = useState<ElevenLabsStatus | null>(null);
  const [elevenLabsError, setElevenLabsError] = useState("");
  const [dialog, setDialog] = useState<"referral" | "reset" | null>(null);
  const [selected, setSelected] = useState<Patient | null>(null);
  const [historyPatient, setHistoryPatient] = useState<Patient | null>(null);
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState<{ message: string; kind: "success" | "error" } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string | null>(null);
  const load = async () => {
    setLoading(true);
    try {
      const [patientRows, slotRows, dashboardMetrics] = await Promise.all([
        fetchJson<Patient[]>("/api/patients"),
        fetchJson<Slot[]>("/api/slots"),
        fetchJson<Metrics>("/api/dashboard"),
      ]);
      setPatients(patientRows);
      setSlots(slotRows);
      setMetrics(dashboardMetrics);
      setError("");
      window.setTimeout(() => {
        void fetchJson<Call[]>("/api/calls").then(setCalls).catch(() => undefined);
        void fetchJson<ActivityItem[]>("/api/activity").then(setActivity).catch(() => undefined);
        void loadWorkflow().catch(() => undefined);
      }, 250);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load data");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
    void fetch("/api/appointment-types?active=true")
      .then(async (response) => {
        if (!response.ok) throw new Error("Appointment types are unavailable.");
        const body = await response.json();
        setAppointmentTypes(Array.isArray(body) ? body : Array.isArray(body.appointment_types) ? body.appointment_types : []);
        setAppointmentTypesError("");
      })
      .catch((reason) => setAppointmentTypesError(reason instanceof Error ? reason.message : "Appointment types are unavailable."));
  }, []);
  useEffect(() => {
    if (page === "calls") {
      setCallsLoading(true);
      void fetchJson<Call[]>("/api/calls")
        .then(setCalls)
        .catch((reason) => action(reason instanceof Error ? reason.message : "Unable to load calls", "error"))
        .finally(() => setCallsLoading(false));
    }
    if (page === "caseworkers") {
      setActivityLoading(true);
      void fetch("/api/activity")
        .then(async (response) => {
          if (!response.ok) throw new Error("Agent runs are temporarily unavailable.");
          const body = await response.json();
          setActivity(Array.isArray(body) ? body : []);
          setActivityError("");
        })
        .catch((reason) => setActivityError(reason instanceof Error ? reason.message : "Unable to load agent runs."))
        .finally(() => setActivityLoading(false));
    }
  }, [page]);
  const loadAgents = async (showLoading = true) => {
    if (showLoading) setAgentsLoading(true);
    try {
      const [response, voiceResponse] = await Promise.all([
        fetch("/api/agents"),
        fetch("/api/integrations/elevenlabs"),
      ]);
      if (!response.ok) throw new Error("Agent definitions are not available yet.");
      const body = await response.json();
      setAgents(Array.isArray(body) ? body : Array.isArray(body.agents) ? body.agents : []);
      setAgentsError("");
      if (voiceResponse.ok) {
        setElevenLabs(await voiceResponse.json());
        setElevenLabsError("");
      } else {
        setElevenLabs(null);
        setElevenLabsError("Configuration status is not exposed by the service yet.");
      }
    } catch (e) {
      setAgentsError(e instanceof Error ? e.message : "Unable to load agents");
    } finally {
      if (showLoading) setAgentsLoading(false);
    }
  };
  useEffect(() => {
    if (page === "caseworkers") void loadAgents();
  }, [page]);
  const openPatient = async (p: Patient) => {
    setSelected(p);
    setPending(`patient:${p.id}`);
    try {
      const r = await fetch(`/api/patients/${p.id}`);
      if (!r.ok) throw new Error("Unable to load the latest appointment details");
      setSelected(await r.json());
    } catch (e) {
      action(e instanceof Error ? e.message : "Unable to load appointment", "error");
    } finally {
      setPending(null);
    }
  };
  const filtered = useMemo(
    () =>
      patients.filter((p) =>
        (p.name + p.external_ref + p.pathway + p.procedure)
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [patients, query],
  );
  const action = (message: string, kind: "success" | "error" = "success") => {
    setToast({ message, kind });
    window.setTimeout(() => setToast(null), 3200);
  };
  const post = async (path: string, body: unknown, success: string, key = path) => {
    if (pending) return false;
    setPending(key);
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        action(detail.detail || "Action failed", "error");
        return false;
      }
      action(success);
      await load();
      return true;
    } catch (e) {
      action(e instanceof Error ? e.message : "Action failed", "error");
      return false;
    } finally {
      setPending(null);
    }
  };
  const resetDemo = async () => {
    if (pending) return;
    setPending("demo-reset");
    try {
      const response = await fetch("/api/demo/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Nous-Demo": "1" },
        body: JSON.stringify({
          operation_id: crypto.randomUUID(),
          scope: "DEMO-*",
          confirmation: "RESET DEMO-* RECORDS",
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message || "Demo reset failed");
      const result = body as DemoResetResponse;
      if (!result.validation.valid) throw new Error("Demo reset did not pass validation");
      inFlightJson.clear();
      workflowCache = null;
      workflowRequest = null;
      setSelected(null);
      setHistoryPatient(null);
      const [callRows, activityRows] = await Promise.all([
        fetchJson<Call[]>("/api/calls"),
        fetchJson<ActivityItem[]>("/api/activity"),
        load(),
        loadWorkflow(),
      ]);
      setCalls(callRows);
      setActivity(activityRows);
      setDialog(null);
      const removed = (result.changes.appointments_removed || 0) + (result.changes.actions_removed || 0) + (result.changes.decisions_removed || 0) + (result.changes.events_removed || 0);
      action(`Demo reset complete · ${result.after_counts.patients} patients · ${result.after_counts.appointments} booked appointments · ${removed} stale records cleared`);
    } catch (reason) {
      action(reason instanceof Error ? reason.message : "Demo reset failed", "error");
    } finally {
      setPending(null);
    }
  };
  return (
    <div className="app-shell">
      <aside>
        <div className="brand">
          <div className="brand-mark">
            <Activity size={18} />
          </div>
          <span>nous</span>
        </div>
        <nav>
          <button
            className={page === "dashboard" ? "active" : ""}
            onClick={() => setPage("dashboard")}
          >
            <LayoutDashboard />
            Overview
          </button>
          <button
            className={page === "appointments" ? "active" : ""}
            onClick={() => setPage("appointments")}
          >
            <CalendarDays />
            Appointments <em>{patients.length}</em>
          </button>
          <button
            className={page === "patients" ? "active" : ""}
            onClick={() => setPage("patients")}
          >
            <UsersRound />
            Patients <em>{patients.length}</em>
          </button>
          <button
            className={page === "capacity" ? "active" : ""}
            onClick={() => setPage("capacity")}
          >
            <CalendarDays />
            Capacity
          </button>
          <button
            className={page === "calls" ? "active" : ""}
            onClick={() => setPage("calls")}
          >
            <Phone />
            Calls
          </button>
        </nav>
        <div className="side-label">OPERATIONS</div>
        <nav>
          <button
            className={page === "caseworkers" ? "active" : ""}
            onClick={() => setPage("caseworkers")}
          >
            <Bot />
            Caseworkers
          </button>
          <button
            className={page === "overseer" ? "active" : ""}
            onClick={() => setPage("overseer")}
          >
            <Activity />
            Overseer
          </button>
        </nav>
        {presenterMode && (
          <div className="side-bottom presenter-controls">
            <span>Presenter controls</span>
            <button onClick={() => setDialog("reset")}>
              <RotateCcw />
              Reset demo
            </button>
          </div>
        )}
      </aside>
      <main>
        <header>
          <div>
            <strong>
              {page === "dashboard"
                ? "Overview"
                : page === "appointments"
                  ? "Appointments"
                : page === "patients"
                  ? "Patients"
                  : page === "capacity"
                    ? "Capacity"
                    : page === "calls"
                      ? "Calls"
                      : page === "caseworkers"
                        ? "Caseworkers"
                        : page === "overseer"
                          ? "Overseer"
                        : "nous"}
            </strong>
            <span>
              {new Intl.DateTimeFormat("en-GB", { dateStyle: "full" }).format(
                new Date(),
              )}
            </span>
          </div>
          <div className="header-actions">
            {(page === "dashboard" || page === "appointments" || page === "patients") && (
              <button className="primary" onClick={() => setDialog("referral")}>
                <Plus />
                New referral
              </button>
            )}
          </div>
        </header>
        {error && (
          <div className="page">
            <section className="cascade">
              <Activity />
              <div>
                <strong>Database setup required</strong>
                <p>
                  {error} Add the Modal database secret and run the committed
                  migration.
                </p>
              </div>
              <button onClick={() => void load()}>Retry</button>
            </section>
          </div>
        )}
        {!error && page === "dashboard" && (
          loading ? <PageSkeleton /> : <Dashboard
            patients={patients}
            slots={slots}
            metrics={metrics}
            loading={false}
            openPatient={openPatient}
            goCapacity={() => setPage("capacity")}
          />
        )}{" "}
        {!error && page === "appointments" && (
          loading ? <PageSkeleton /> : <Appointments
            rows={filtered}
            total={patients.length}
            query={query}
            setQuery={setQuery}
            select={openPatient}
          />
        )}{" "}
        {!error && page === "patients" && (
          loading ? <PageSkeleton /> : <PatientDirectory rows={patients} select={openPatient} />
        )}{" "}
        {!error && page === "capacity" && (
          loading ? <PageSkeleton /> : <Capacity slots={slots} />
        )}
        {!error && page === "calls" && (
          loading || (callsLoading && !calls.length) ? <PageSkeleton /> : <CallsPage calls={calls} patients={patients} openPatient={openPatient} />
        )}
        {!error && page === "overseer" && (loading ? <PageSkeleton /> : <OverseerWorkflow patients={patients} openPatient={openPatient} />)}
        {!error && page === "caseworkers" && (
          <CaseworkersPage
            agents={agents}
            loading={agentsLoading}
            error={agentsError}
            elevenLabs={elevenLabs}
            elevenLabsError={elevenLabsError}
            pending={pending}
            activity={activity}
            activityLoading={activityLoading}
            activityError={activityError}
            patients={patients}
            openPatient={openPatient}
            retry={() => void loadAgents()}
            run={async (key) => {
              const ok = await post(
                `/api/agents/${encodeURIComponent(key)}/run`,
                {},
                "Manual agent run requested",
                `agent:${key}`,
              );
              if (ok) await loadAgents(false);
              return ok;
            }}
          />
        )}
        {historyPatient && <PatientAgentHistoryPage patient={historyPatient} close={() => { setSelected(historyPatient); setHistoryPatient(null); }} />}
      </main>
      {selected && (
        <PatientPanel
          patient={selected}
          loading={pending === `patient:${selected.id}`}
          actionPending={pending}
          slots={slots.filter(
            (slot) =>
              slot.state === "AVAILABLE" &&
              slot.procedure === selected.procedure,
          )}
          close={() => setSelected(null)}
          viewAgentHistory={() => { setHistoryPatient(selected); setSelected(null); }}
          reschedule={(slotId) =>
            void post(
              "/api/appointments/reschedule",
              { goal_id: selected.id, slot_id: slotId },
              "Appointment rescheduled",
              "reschedule",
            )
          }
          addNote={async (category, text) => {
            const response = await fetch(`/api/patients/${selected.id}/notes`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ category, text }),
            });
            if (!response.ok) {
              const detail = await response.json().catch(() => ({}));
              action(detail.detail || "Unable to save note", "error");
              return false;
            }
            action("Appointment note saved");
            await openPatient(selected);
            return true;
          }}
          updatePatient={async (body) => {
            setPending("patient-update");
            try {
              const response = await fetch(`/api/patients/${selected.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
              if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                action(detail.detail || "Unable to update patient", "error");
                return false;
              }
              action("Patient details updated");
              await load();
              await openPatient(selected);
              return true;
            } finally { setPending(null); }
          }}
        />
      )}{" "}
      {toast && (
        <div className={`toast ${toast.kind}`} role="status" aria-live="polite">
          <span>{toast.kind === "success" ? "✓" : "!"}</span>
          {toast.message}
        </div>
      )}
      {dialog === "referral" && (
        <ReferralDialog
          appointmentTypes={appointmentTypes}
          catalogueError={appointmentTypesError}
          close={() => setDialog(null)}
          save={async (body) => {
            if (await post("/api/referrals", body, "Referral created", "referral"))
              setDialog(null);
          }}
          saving={pending === "referral"}
        />
      )}
      {dialog === "reset" && (
        <DemoResetDialog
          close={() => setDialog(null)}
          reset={() => void resetDemo()}
          resetting={pending === "demo-reset"}
        />
      )}
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div
      style={{
        padding: "42px",
        textAlign: "center",
        color: "#69756f",
        fontSize: 12,
      }}
    >
      {label}
    </div>
  );
}
function PageSkeleton() {
  return (
    <div className="page page-skeleton" role="status" aria-live="polite" aria-label="Loading live appointment data">
      <div className="skeleton-title"><i /><i /></div>
      <div className="skeleton-metrics"><i /><i /><i /><i /></div>
      <div className="skeleton-card"><i /><i /><i /></div>
      <span>Loading live appointment data…</span>
    </div>
  );
}
function Dashboard({
  patients,
  slots,
  metrics,
  loading,
  openPatient,
  goCapacity,
}: {
  patients: Patient[];
  slots: Slot[];
  metrics: Metrics;
  loading: boolean;
  openPatient: (p: Patient) => void;
  goCapacity: () => void;
}) {
  const [workflow, setWorkflow] = useState<OverseerWorkflowData | null>(() => workflowCache);
  useEffect(() => {
    let cancelled = false;
    const refresh = () => loadWorkflow().then((body) => { if (!cancelled) setWorkflow(body); }).catch(() => undefined);
    void refresh();
    const timer = window.setInterval(refresh, 500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  return (
    <div className="page">
      <section className="intro">
        <div>
          <span className="eyebrow">OPERATIONS OVERVIEW</span>
          <h1>Patient appointments</h1>
          <p>Every referral has a persistent administrative scheduling agent.</p>
        </div>
      </section>
      <div className="metrics metrics-one">
        <Metric
          n={String(metrics.active)}
          label="Active appointments"
          hint="Currently being managed"
        />
      </div>
      <div className="policy-strip"><FileClock /><div><strong>Reminder policy</strong><span>{metrics.reminder_policy || "Reminder scheduled 48 hours before the appointment"}</span></div></div>
      <DashboardOverseer workflow={workflow} patients={patients} openPatient={openPatient} />
    </div>
  );
}
const visibleOverseerStages = (workflow: OverseerWorkflowData) => {
  const scheduled = workflow.run_state === "NEXT_SCAN_SCHEDULED";
  const stages = workflow.stages.length === 1 && workflow.stages[0]?.key === "scan"
    ? [
        { key: "scan", label: "Scan available slots", complete: scheduled },
        { key: "evaluate", label: "Evaluate candidates", complete: scheduled },
        { key: "rank", label: "Rank and select", complete: scheduled },
        { key: "wake", label: "Wake caseworker", complete: scheduled },
      ]
    : workflow.stages;
  return [...stages, { key: "schedule", label: "Schedule next scan", complete: false, active: scheduled }];
};

const overseerStageOutcome = (workflow: OverseerWorkflowData, key: string) => {
  const selectedFromSummary = workflow.last_iteration_summary?.match(/^Woke caseworker for (.+)$/i)?.[1];
  if (key === "scan") return `${workflow.scan_stats?.slots_checked || 0} available appointments found`;
  if (key === "evaluate") return `${workflow.scan_stats?.compatible_patients || 0} active patients checked`;
  if (key === "rank") return workflow.selected_patient?.name
    ? `Selected ${workflow.selected_patient.name}`
    : selectedFromSummary ? `Selected ${selectedFromSummary}` : "No patient selected";
  if (key === "wake") return workflow.last_iteration_summary || "No caseworker needed";
  if (key === "schedule") return workflow.next_wake_at ? `Resumes ${fmt(workflow.next_wake_at)}` : `Resumes within ${workflow.next_wake_seconds || 60} seconds`;
  return "No outcome recorded";
};

function OverseerLoop({ workflow, detailed = false }: { workflow: OverseerWorkflowData; detailed?: boolean }) {
  const stages = visibleOverseerStages(workflow);
  const scheduled = workflow.run_state === "NEXT_SCAN_SCHEDULED";
  const currentStage = stages.find((stage) => stage.active) || stages[0];
  const loopLayout: Record<string, { x: number; y: number; source: Position; target: Position }> = {
    scan: { x: 376, y: 18, source: Position.Right, target: Position.Left },
    evaluate: { x: 690, y: 112, source: Position.Bottom, target: Position.Top },
    rank: { x: 596, y: 270, source: Position.Left, target: Position.Right },
    wake: { x: 156, y: 270, source: Position.Top, target: Position.Right },
    schedule: { x: 62, y: 112, source: Position.Right, target: Position.Bottom },
  };
  const nodes: Node[] = stages.map((stage, index) => {
    const current = Boolean(stage.active);
    const state = stage.complete ? "complete" : current ? "active" : "waiting";
    const detail = stage.at ? fmt(stage.at) : stage.complete ? "Completed" : current ? scheduled ? "Next run scheduled" : "Running now" : "Waiting";
    const layout = loopLayout[stage.key] || { x: 42 + index * 194, y: 56, source: Position.Right, target: Position.Left };
    return {
      id: stage.key,
      position: { x: layout.x, y: layout.y },
      sourcePosition: layout.source,
      targetPosition: layout.target,
      draggable: false,
      selectable: false,
      className: `overseer-flow-node ${state}`,
      data: {
        label: <div className="overseer-node-content">
          <span className="overseer-node-state" aria-hidden="true">{stage.complete ? "✓" : index + 1}</span>
          <span><strong>{stage.label}</strong><small>{detail}</small></span>
        </div>,
      },
    };
  });
  const flowColour = "#4b9275";
  const idleColour = "#cad7d1";
  const edges: Edge[] = stages.slice(0, -1).map((stage, index) => ({
    id: `${stage.key}-${stages[index + 1].key}`,
    source: stage.key,
    target: stages[index + 1].key,
    animated: Boolean(stage.active),
    type: "smoothstep",
    style: { stroke: stage.complete ? flowColour : idleColour, strokeWidth: stage.complete || stage.active ? 2.25 : 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color: stage.complete ? flowColour : idleColour, width: 14, height: 14 },
  }));
  edges.push({
    id: "schedule-scan-loop",
    source: "schedule",
    target: "scan",
    sourceHandle: null,
    animated: scheduled,
    type: "smoothstep",
    style: { stroke: scheduled ? "#cc8a28" : idleColour, strokeWidth: scheduled ? 2.25 : 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color: scheduled ? "#cc8a28" : idleColour, width: 14, height: 14 },
  });
  return <div className={`dashboard-loop ${detailed ? "overseer-loop-detailed" : ""}`} aria-label="Live overseer workflow: scan, evaluate, rank, wake a caseworker, then schedule the next scan">
    <div className="dashboard-loop-visual">
      <div className="overseer-flow-status"><span>Current state</span><strong>{scheduled ? "Next scan scheduled" : currentStage?.label || "Monitoring"}</strong><small>{workflow.next_wake_at ? `Next run ${fmt(workflow.next_wake_at)}` : "Updates automatically"}</small></div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.12, minZoom: 0.72, maxZoom: 1 }}
        minZoom={0.65}
        maxZoom={1.05}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#dce6e1" gap={22} size={1} />
      </ReactFlow>
    </div>
    {detailed && <div className="overseer-stage-outcomes" aria-label="Latest Overseer outcomes">
      {stages.map((stage) => <div key={stage.key}><span>{stage.label}</span><strong>{overseerStageOutcome(workflow, stage.key)}</strong></div>)}
    </div>}
  </div>;
}

function DashboardOverseer({ workflow, patients, openPatient }: { workflow: OverseerWorkflowData | null; patients: Patient[]; openPatient: (patient: Patient) => void }) {
  const patient = workflow?.selected_patient ? patients.find((item) => item.id === workflow.selected_patient?.goal_id) : undefined;
  return <section className="card dashboard-overseer">
    <header><div><span className="eyebrow">AUTOMATIC CAPACITY RECOVERY</span><h2>Overseer workflow</h2></div>{workflow?.active && <span className="live-indicator"><i /> Live</span>}</header>
    {!workflow ? <Empty label="Loading recent automation…" /> : !workflow.active ? <div className="dashboard-overseer-empty"><strong>Waiting for an appointment to be released</strong><span>The overseer will triage compatible patients automatically when someone reschedules.</span></div> : <>
      <OverseerLoop workflow={workflow} />
      {workflow.slot && workflow.selected_patient && workflow.action ? <div className="dashboard-overseer-result"><div><span>Released appointment</span><strong>{workflow.slot.procedure || "Appointment"}{workflow.slot.starts_at ? ` · ${fmt(workflow.slot.starts_at)}` : ""}</strong></div><div><span>Selected for earlier appointment</span><strong>{workflow.selected_patient.name}</strong></div><div><span>Caseworker</span><strong>{workflow.action.phone_status || "Caseworker woken"}</strong></div>{patient && <button onClick={() => openPatient(patient)}>View patient</button>}</div> : <div className="dashboard-overseer-result"><div><span>Current scan</span><strong>Next 7 days</strong></div><div><span>Capacity checked</span><strong>{workflow.scan_stats?.slots_checked || 0} available appointments</strong></div><div><span>Result</span><strong>{workflow.last_iteration_summary || "No actionable release this pass"}</strong></div></div>}
    </>}
  </section>;
}
function Metric({
  n,
  label,
  hint,
  warn,
  good,
}: {
  n: string;
  label: string;
  hint: string;
  warn?: boolean;
  good?: boolean;
}) {
  return (
    <div className="metric">
      <span className={warn ? "warn" : good ? "good" : ""}>{n}</span>
      <strong>{label}</strong>
      <small>{hint}</small>
    </div>
  );
}
function Avatar({ p }: { p: Patient }) {
  return <div className="avatar">{p.initials}</div>;
}
const displayStatus = (status: string) => {
  const normalized = status.toUpperCase();
  return normalized === "HUMAN_REVIEW_REQUIRED" ? "PAUSED" : normalized === "WAITING" ? "ON TRACK" : normalized.replaceAll("_", " ");
};
function Status({ status }: { status: string }) {
  const normalized = status.toUpperCase();
  const c = ["FAILED", "ERROR"].includes(normalized)
    ? "red"
    : ["AVAILABLE", "COMPLETED"].includes(normalized)
      ? "green"
      : ["BOOKED", "ACTIVE"].includes(normalized)
        ? "blue"
        : ["HELD", "OFFERED", "WAITING", "QUEUED"].includes(normalized)
          ? "amber"
          : "neutral";
  return (
    <b className={`status ${c}`}>
      <i></i>
      {displayStatus(normalized)}
    </b>
  );
}
const appointmentProgress = (p: Patient) => {
  if (p.blocker) return "Case paused";
  if (p.offer_status === "OFFERED") return "Ready to contact — caseworker selected an appointment to offer";
  if (p.status === "WAITING") return p.appointment ? "Caseworker monitoring the appointment" : "Awaiting the next scheduling event";
  if (p.status === "ACTIVE") return p.appointment ? "Agent monitoring appointment" : "Agent finding an appointment";
  if (p.status === "COMPLETED") return "Appointment completed";
  return "Workflow can continue automatically";
};
function CaseRow({ p, open }: { p: Patient; open: (p: Patient) => void }) {
  return (
    <button className="case-row" onClick={() => open(p)}>
      <Avatar p={p} />
      <div className="case-person">
        <strong>{p.name}</strong>
        <span>
          {p.external_ref} · {p.procedure}
        </span>
      </div>
      <div className="case-state">
        <Status status={p.status} />
        <span>{appointmentProgress(p)}</span>
      </div>
      <div className="case-next">
        <strong>{fmt(p.next_wake_at)}</strong>
        <span>Next wake</span>
      </div>
      <b className="arrow">›</b>
    </button>
  );
}
function Appointments({
  rows,
  total,
  query,
  setQuery,
  select,
}: {
  rows: Patient[];
  total: number;
  query: string;
  setQuery: (s: string) => void;
  select: (p: Patient) => void;
}) {
  return (
    <div className="page directory-page">
      <section className="page-title directory-page-title">
        <div>
          <span className="eyebrow">PATIENT APPOINTMENTS</span>
          <h1>Appointments</h1>
          <p>Live referrals and their persistent scheduling progress.</p>
        </div>
      </section>
      <section className="card table-card record-directory appointment-directory">
        <div className="directory-filters appointment-filters">
          <label className="directory-search-field">
            <span>Search appointments</span>
            <span className="search directory-search-control">
              <Search />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Patient, reference or appointment type…"
              />
            </span>
          </label>
        </div>
        <div className="directory-result-count"><strong>{rows.length}</strong> of {total} appointments</div>
        <div className="table-head directory-head appointment-directory-grid">
          <span>PATIENT</span>
          <span>APPOINTMENT TYPE &amp; BOOKING</span>
          <span>STATE</span>
          <span>NEXT WAKE</span>
          <span></span>
        </div>
        {rows.length ? (
          rows.map((p) => (
            <button
              className="patient-row directory-row appointment-directory-grid"
              key={p.id}
              onClick={() => select(p)}
            >
              <div className="patient-cell">
                <Avatar p={p} />
                <strong>
                  {p.name}
                  <small>{p.external_ref}</small>
                </strong>
              </div>
              <div>
                <strong>{p.procedure}</strong>
                <small>
                  {fmt(p.appointment)} · {p.site || "Site not selected"}
                </small>
              </div>
              <div>
                <Status status={p.status} />
                <small>{appointmentProgress(p)}</small>
              </div>
              <div>
                <strong>{fmt(p.next_wake_at)}</strong>
                <small>via {p.preference}</small>
              </div>
              <b className="arrow">›</b>
            </button>
          ))
        ) : (
          <Empty label="No referrals have been added yet." />
        )}
      </section>
    </div>
  );
}
function PatientDirectory({ rows, select }: { rows: Patient[]; select: (p: Patient) => void }) {
  const [search, setSearch] = useState("");
  const [language, setLanguage] = useState("ALL");
  const [appointmentType, setAppointmentType] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const languages = Array.from(new Set(rows.map((row) => row.language).filter(Boolean))).sort();
  const appointmentTypes = Array.from(new Set(rows.map((row) => row.procedure).filter(Boolean))).sort();
  const visible = rows.filter((row) => {
    const term = search.trim().toLowerCase();
    const matchesSearch = !term || `${row.name} ${row.external_ref}`.toLowerCase().includes(term);
    const matchesLanguage = language === "ALL" || row.language === language;
    const matchesType = appointmentType === "ALL" || row.procedure === appointmentType;
    const matchesStatus = status === "ALL" || row.status === status;
    return matchesSearch && matchesLanguage && matchesType && matchesStatus;
  });
  return (
    <div className="page directory-page">
      <section className="page-title patient-page-title directory-page-title">
        <div><span className="eyebrow">PATIENT WORKSPACE</span><h1>Patients</h1><p>Find a person once, then see their appointment, preferences and caseworker progress together.</p></div>
      </section>
      <section className="card patient-directory record-directory">
        <div className="patient-filters directory-filters">
          <label className="patient-search-field directory-search-field"><span>Search patients</span><span className="search patient-search-control directory-search-control"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name or patient reference…" /></span></label>
          <label><span>Language</span><select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="ALL">All languages</option>{languages.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label><span>Appointment type</span><select value={appointmentType} onChange={(event) => setAppointmentType(event.target.value)}><option value="ALL">All types</option>{appointmentTypes.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="ALL">All statuses</option><option value="ACTIVE">Active</option><option value="WAITING">Waiting</option><option value="COMPLETED">Completed</option></select></label>
        </div>
        <div className="patient-result-count directory-result-count"><strong>{visible.length}</strong> of {rows.length} patients</div>
        <div className="patient-directory-head directory-head patient-directory-grid"><span>PATIENT</span><span>APPOINTMENT</span><span>PREFERENCES</span><span>CASEWORKER</span><span></span></div>
        {visible.length ? visible.map((p) => (
          <button className="patient-directory-row directory-row patient-directory-grid" key={p.id} onClick={() => select(p)}>
            <div className="patient-cell"><Avatar p={p} /><strong>{p.name}<small>{p.external_ref}</small></strong></div>
            <div><strong>{p.procedure}</strong><small>{p.appointment ? fmt(p.appointment) : "Not yet booked"}{p.site ? ` · ${p.site}` : ""}</small></div>
            <div><strong>{p.language}</strong><small>{p.preference || "No contact preference"}</small></div>
            <div><Status status={p.status} /><small>{appointmentProgress(p)}</small></div>
            <b className="arrow">›</b>
          </button>
        )) : <Empty label="No patients match these filters." />}
      </section>
    </div>
  );
}
function Capacity({ slots }: { slots: Slot[] }) {
  const appointmentTypes = Array.from(new Set(slots.map((slot) => slot.procedure))).sort();
  const [appointmentType, setAppointmentType] = useState("ALL");
  const visibleSlots = appointmentType === "ALL"
    ? slots
    : slots.filter((slot) => slot.procedure === appointmentType);
  return (
    <div className="page">
      <section className="page-title">
        <div>
          <span className="eyebrow">GLOBAL SCHEDULING AGENT</span>
          <h1>Capacity</h1>
          <p>Available appointments by type, date and location.</p>
        </div>
      </section>
      <section className="card table-card">
        <div className="toolbar">
          <label className="capacity-filter">
            <span>Appointment type</span>
            <select value={appointmentType} onChange={(event) => setAppointmentType(event.target.value)}>
              <option value="ALL">All appointment types</option>
              {appointmentTypes.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
          </label>
          <span>{visibleSlots.length} slots</span>
        </div>
        <div className="slot-head">
          <span>DATE & TIME</span>
          <span>SITE</span>
          <span>APPOINTMENT TYPE</span>
          <span>STATUS</span>
          <span>DURATION</span>
        </div>
        {visibleSlots.length ? (
          visibleSlots.map((s) => (
            <div className="slot-row" key={s.id}>
              <strong>{fmt(s.time)}</strong>
              <span>{s.site}</span>
              <span>{s.procedure}</span>
              <Status status={s.state} />
              <span>{s.duration_minutes} min</span>
            </div>
          ))
        ) : (
          <Empty label={appointmentType === "ALL" ? "No future slots are available." : `No future ${appointmentType} slots are available.`} />
        )}
      </section>
    </div>
  );
}
function CaseworkersPage({
  activity,
  activityLoading,
  activityError,
  patients,
  openPatient,
  ...agentsProps
}: Parameters<typeof AgentsPage>[0] & {
  activity: ActivityItem[];
  activityLoading: boolean;
  activityError: string;
  patients: Patient[];
  openPatient: (patient: Patient) => void;
}) {
  const [section, setSection] = useState<"definitions" | "runs">("definitions");
  return <div className="page caseworkers-page">
    <section className="page-title">
      <div><span className="eyebrow">OPERATIONS</span><h1>Caseworkers</h1><p>Agent definitions, tools, versions and recorded appointment work.</p></div>
    </section>
    <div className="section-tabs" role="tablist" aria-label="Caseworker sections">
      <button type="button" role="tab" aria-selected={section === "definitions"} className={section === "definitions" ? "active" : ""} onClick={() => setSection("definitions")}><Bot />Definitions &amp; tools</button>
      <button type="button" role="tab" aria-selected={section === "runs"} className={section === "runs" ? "active" : ""} onClick={() => setSection("runs")}><Sparkles />Recorded runs</button>
    </div>
    {section === "definitions" ? <AgentsPage {...agentsProps} embedded /> : <AgentActivity rows={activity} patients={patients} openPatient={openPatient} loading={activityLoading} error={activityError} embedded />}
  </div>;
}

function AgentsPage({
  agents,
  loading,
  error,
  elevenLabs,
  elevenLabsError,
  pending,
  retry,
  run,
  embedded = false,
}: {
  agents: AgentDefinition[];
  loading: boolean;
  error: string;
  elevenLabs: ElevenLabsStatus | null;
  elevenLabsError: string;
  pending: string | null;
  retry: () => void;
  run: (key: string) => Promise<boolean>;
  embedded?: boolean;
}) {
  const [lastStarted, setLastStarted] = useState<string | null>(null);
  return (
    <div className={embedded ? "embedded-page" : "page"}>
      {!embedded && <section className="page-title">
        <div>
          <span className="eyebrow">AUTOMATED SCHEDULING</span>
          <h1>Agents</h1>
          <p>Active definitions, skills, tools, versions and execution traces.</p>
        </div>
      </section>}
      {error && (
        <section className="cascade agent-api-error">
          <Bot />
          <div><strong>Agent registry unavailable</strong><p>{error}</p></div>
          <button onClick={retry}>Retry</button>
        </section>
      )}
      <ElevenLabsCard status={elevenLabs} error={elevenLabsError} loading={loading} />
      {loading ? <section className="card"><Empty label="Loading agent definitions…" /></section> : !error && agents.length ? (
        <div className="agents-grid">
          {agents.map((agent) => <AgentCard key={agent.key} agent={agent} pending={pending === `agent:${agent.key}`} started={lastStarted === agent.key} run={async () => { if (await run(agent.key)) { setLastStarted(agent.key); window.setTimeout(() => setLastStarted((current) => current === agent.key ? null : current), 5000); } }} />)}
        </div>
      ) : !error ? <section className="card"><Empty label="No versioned agent definitions are registered yet." /></section> : null}
    </div>
  );
}

function ElevenLabsCard({ status, error, loading }: { status: ElevenLabsStatus | null; error: string; loading: boolean }) {
  const tools = status?.attached_tools || status?.tools || [];
  const capabilities = Array.from(new Map([
    ...(status ? [["language-detection", "Language detection"]] as Array<[string, string]> : []),
    ...tools.map((tool, index) => {
      const raw = typeof tool === "string" ? tool : tool.name || `Tool ${index + 1}`;
      const normalized = raw.toLowerCase().replace(/^nous[_\s-]*/, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      return [normalized, toolLabel(raw)] as [string, string];
    }),
  ]).values());
  const connected = Boolean(status?.configured ?? status?.available);
  const browserReady = Boolean(status?.browser_available);
  const telephoneLabel = status?.telephone_transport === "simulated" ? "Simulated outcomes · no phone call" : status?.telephone_transport === "elevenlabs_phone" ? "ElevenLabs phone calling" : "Not configured";
  return (
    <section className="card eleven-card">
      <div className="agent-card-head">
        <div className="agent-icon voice-icon"><Phone /></div>
        <div><h2>ElevenLabs voice agent</h2><p>Calling configuration and callback health</p></div>
        {loading ? <span className="integration-state muted">Checking…</span> : <span className={`integration-state ${connected ? "ok" : "muted"}`}>{connected ? "Configured" : "Unavailable"}</span>}
      </div>
      {status ? <>
        <div className="voice-metadata">
          <Detail label="Agent" value={status.agent_name || status.agent_id || "Not reported"} />
          <Detail label="Version / branch" value={[status.agent_version ?? status.version, status.branch].filter(Boolean).join(" · ") || "Not reported"} />
          <Detail label="Browser conversations" value={browserReady ? "Ready · signed sessions" : "Unavailable"} />
          <Detail label="Telephone" value={telephoneLabel} />
          <Detail label="Webhook" value={status.webhook_status || (status.webhook_url ? "Configured" : "Not reported")} />
          <Detail label="Last sync" value={fmt(status.last_sync_at || null)} />
        </div>
        {status.message && <p className="integration-summary">{status.message}</p>}
        <div className="agent-block"><h3>Voice capabilities <small>{capabilities.length} configured</small></h3>{capabilities.length ? <div className="tool-chips">{capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div> : <Empty label="ElevenLabs did not return any attached tools." />}</div>
        {status.last_error && <div className="integration-error"><strong>Last error</strong><span>{status.last_error}</span></div>}
      </> : <div className="integration-unavailable"><p>{error || "Waiting for configuration status…"}</p><span>The voice integration can continue operating; this panel will populate when its status endpoint is available.</span></div>}
    </section>
  );
}

function AgentCard({ agent, pending, started, run }: { agent: AgentDefinition; pending: boolean; started: boolean; run: () => void }) {
  const tools = agent.allowed_tools || agent.tools || [];
  const executions = agent.recent_executions || agent.executions || [];
  const version = agent.active_version ?? agent.version;
  const instructions = agent.instructions || agent.skill;
  return (
    <section className="card agent-card">
      <div className="agent-card-head">
        <div className="agent-icon"><Bot /></div>
        <div><h2>{agent.name || agent.role || agent.key}</h2><p>{agent.role && agent.name ? agent.role : agent.key}</p></div>
        <Status status={agent.status || "ACTIVE"} />
      </div>
      <div className="agent-runtime">
        <Detail label="Active version" value={version !== undefined ? String(version) : "Not reported"} />
        <Detail label="Model" value={agent.model || "Not reported"} />
        <Detail label="Last execution" value={agent.last_run_at ? fmt(agent.last_run_at) : "No agent run yet"} />
      </div>
      <div className="agent-block">
        <h3>Instructions and skill</h3>
        {instructions ? <p className="agent-instructions">{instructions}</p> : <Empty label="No instructions returned by the registry." />}
      </div>
      <div className="agent-block">
        <h3>Allowed tools</h3>
        {tools.length ? <div className="tool-chips">{tools.map((tool, index) => {
          const name = typeof tool === "string" ? tool : tool.name || `Tool ${index + 1}`;
          const description = typeof tool === "string" ? undefined : tool.description;
          return <span key={`${name}-${index}`} title={description}>{toolLabel(name)}</span>;
        })}</div> : <Empty label="No allowed tools reported." />}
      </div>
      <details className="agent-block disclosure">
        <summary>Version history <b>{agent.versions?.length || 0}</b></summary>
        {agent.versions?.length ? <div className="version-list">{agent.versions.map((item, index) => (
          <div key={String(item.id || item.version || index)}><strong>Version {String(item.version || item.number || index + 1)}</strong><span>{fmt((item.created_at || item.activated_at || null) as string | null)}</span><small>{String(item.summary || item.change_note || item.status || "")}</small></div>
        ))}</div> : <Empty label="No earlier versions recorded." />}
      </details>
      <details className="agent-block disclosure">
        <summary>Recent executions <b>{executions.length}</b></summary>
        {executions.length ? executions.map((step) => <AgentTrace key={step.id} step={step} />) : <Empty label="No executions recorded for this agent." />}
      </details>
      <div className="agent-manual">
        <div><strong>Manual recovery</strong><span>{started ? "Run started. Its activity will appear in the trace." : "Agents normally run automatically. Use this only for inspection or recovery."}</span></div>
        <button type="button" className="primary" onClick={run} disabled={pending}>{pending ? "Starting…" : started ? "Started" : "Run once"}</button>
      </div>
    </section>
  );
}
function PatientPanel({
  patient: p,
  slots,
  close,
  viewAgentHistory,
  reschedule,
  addNote,
  updatePatient,
  loading,
  actionPending,
}: {
  patient: Patient;
  slots: Slot[];
  close: () => void;
  viewAgentHistory: () => void;
  reschedule: (slotId: string) => void;
  addNote: (category: string, text: string) => Promise<boolean>;
  updatePatient: (body: Record<string, unknown>) => Promise<boolean>;
  loading: boolean;
  actionPending: string | null;
}) {
  const [slotId, setSlotId] = useState("");
  const [editingDetails, setEditingDetails] = useState(false);
  const reminderAt = p.appointment
    ? new Date(new Date(p.appointment).getTime() - 48 * 60 * 60 * 1000).toISOString()
    : null;
  const latestStep = [...(p.agent_steps || [])].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  const nextCaseworkerAction = p.blocker
    ? "Caseworker paused until the scheduling exception is resolved"
    : p.next_wake_at
      ? `Wake automatically ${fmt(p.next_wake_at)}`
      : p.status === "COMPLETED" ? "No further action" : "Wait for the next appointment event";
  return (
    <div
      className="overlay"
      onMouseDown={(e) => e.target === e.currentTarget && close()}
    >
      <aside className="drawer">
        <div className="drawer-head">
          <span>Patient appointment</span>
          <button onClick={close} aria-label="Close patient appointment">
            <X />
          </button>
        </div>
        <div className="profile">
          <Avatar p={p} />
          <div>
            <h2>{p.name}</h2>
            <span>{p.external_ref}</span>
          </div>
          <Status status={p.status} />
        </div>
        {loading && <div className="panel-progress" role="status">Refreshing appointment details…</div>}
        <div className="patient-summary-grid">
          <article><span>APPOINTMENT</span><strong>{p.procedure}</strong><p>{p.appointment ? fmt(p.appointment) : "Not yet booked"}<br />{p.site || "Site not selected"}</p></article>
          <article><span>PREFERENCES</span><strong>{p.language}</strong><p>{p.preference || "No contact preference"}{p.note ? <><br />{p.note}</> : null}</p></article>
          <article><span>CASEWORKER</span><strong>{loading ? "Loading activity…" : latestStep ? runTitle(latestStep) : "No run yet"}</strong><p><button type="button" className="text-link" onClick={viewAgentHistory}>View agent history</button></p></article>
          <article><span>NEXT ACTION</span><strong>{p.blocker ? "Paused" : displayStatus(p.status)}</strong><p>{nextCaseworkerAction}</p></article>
        </div>
        <div className="appointment-reminder"><FileClock /><div><span>Reminder call</span><strong>{reminderAt ? fmt(reminderAt) : "Scheduled when an appointment is booked"}</strong><small>Automatically queued 48 hours before the appointment</small></div></div>
        <div className="section">
          <div className="section-title-row"><h3>Contact &amp; preferences</h3><button type="button" className="text-link" onClick={() => setEditingDetails((value) => !value)}>{editingDetails ? "Cancel" : "Edit details"}</button></div>
          {editingDetails ? <form className="form-grid patient-details-form" onSubmit={async (event) => {
            event.preventDefault();
            if (await updatePatient(Object.fromEntries(new FormData(event.currentTarget)))) setEditingDetails(false);
          }}>
            <Field name="first_name" label="First name" value={p.first_name || p.name.split(" ")[0]} required />
            <Field name="last_name" label="Last name" value={p.last_name || p.name.split(" ").slice(1).join(" ")} required />
            <Field name="date_of_birth" label="Date of birth" type="date" value={p.date_of_birth || ""} required />
            <Field name="phone" label="Phone" type="tel" value={p.phone || ""} required />
            <Field name="email" label="Email" type="email" value={p.email || ""} />
            <Field name="preferred_language" label="Language" value={p.language} required />
            <Field name="preferred_contact_method" label="Preferred contact" value={p.preference || "VOICE"} required />
            <div className="drawer-actions"><button className="primary" type="submit" disabled={actionPending !== null}>{actionPending === "patient-update" ? "Saving…" : "Save details"}</button></div>
          </form> : <>
            <Detail label="Phone" value={p.phone || "Not provided"} />
            <Detail label="Email" value={p.email || "Not provided"} />
            <Detail label="Date of birth" value={p.date_of_birth || "Not provided"} />
            <Detail label="Language" value={p.language} />
            <Detail label="Preferred contact" value={p.preference} />
          </>}
        </div>
        <div className="section">
          <h3>Case files</h3>
          <p className="section-help">Operators and caseworkers share these three versioned Markdown files.</p>
          <CaseFilesEditor goalId={p.id} initialDocuments={p.case_documents || []} />
        </div>
        <div className="drawer-actions">
          <select
            value={slotId}
            disabled={!slots.length || actionPending !== null}
            onChange={(event) => setSlotId(event.target.value)}
          >
            <option value="">Choose replacement slot</option>
            {slots.map((slot) => (
              <option key={slot.id} value={slot.id}>
                {fmt(slot.time)} · {slot.site}
              </option>
            ))}
          </select>
          <button disabled={!slotId || actionPending !== null} onClick={() => reschedule(slotId)}>
            {actionPending === "reschedule" ? "Rescheduling…" : "Reschedule"}
          </button>
          <PatientCallLauncher patient={p} disabled={actionPending !== null} />
          <button
            className="demo-phone-link"
            type="button"
            onClick={() => window.open(`/phone?claim=${encodeURIComponent(p.external_ref)}`, "_blank", "noopener,noreferrer")}
            title="Open this patient's hackathon browser phone in a new tab"
          >
            Open patient phone <small>Demo only</small>
          </button>
        </div>
      </aside>
    </div>
  );
}

type BrowserSession = {
  signed_url: string;
  dynamic_variables: Record<string, string>;
  language_code: Language;
};

function PatientCallLauncher({
  patient,
  disabled,
}: {
  patient: Patient;
  disabled: boolean;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [queuedActionId, setQueuedActionId] = useState<string | null>(patient.active_call_action_id || null);

  useEffect(() => {
    setQueuedActionId(patient.active_call_action_id || null);
  }, [patient.id, patient.active_call_action_id]);

  useEffect(() => {
    if (!queuedActionId) return;
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(`/api/demo-phone/action-status?goal_id=${encodeURIComponent(patient.id)}&action_id=${encodeURIComponent(queuedActionId)}`, { cache: "no-store" });
        if (response.status === 404) { if (active) setQueuedActionId(null); return; }
        if (!response.ok) return;
        const result = await response.json() as { live: boolean };
        if (active && !result.live) setQueuedActionId(null);
      } catch { /* The next poll or visibility refresh will retry. */ }
    };
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    void refresh();
    const timer = window.setInterval(refresh, 1500);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [patient.id, queuedActionId]);

  const start = async () => {
    setStarting(true);
    setError("");
    try {
      const response = await fetch("/api/demo-phone/queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal_id: patient.id, purpose: "REMINDER" }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "The patient call could not be queued.");
      }
      const result = await response.json() as { action_id: string };
      setQueuedActionId(result.action_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The patient call could not be queued.");
    } finally { setStarting(false); }
  };

  const cancel = async () => {
    if (!queuedActionId) return;
    await fetch("/api/demo-phone/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal_id: patient.id, action_id: queuedActionId }) });
    setQueuedActionId(null);
  };

  return (
    <div className="browser-caseworker">
      {queuedActionId ? <div className="browser-caseworker active" role="status">
        <div className="voice-live-dot speaking" />
        <div><strong>Waiting on {patient.name.split(" ")[0]}’s phone</strong><span>The call will ring only on their open demo phone page.</span></div>
        <button type="button" onClick={() => void cancel()}>Cancel</button>
      </div> : <button className="primary voice-action" type="button" disabled={disabled || starting} onClick={() => void start()} title="Ring this patient's browser demo phone">
        <Phone />
        <span>{starting ? "Starting…" : "Run caseworker"}<small>Rings the patient’s demo phone</small></span>
      </button>}
      {error && <div className="browser-voice-error"><span>{error}</span></div>}
    </div>
  );
}

type DemoIncomingCall = {
  waiting: boolean;
  goal_id: string;
  action_id: string | null;
  receiver_token: string | null;
  patient_first_name: string;
  preferred_language: string;
};

function DemoPhone() {
  const claimCode = new URLSearchParams(window.location.search).get("claim")?.trim() || "";
  const [incoming, setIncoming] = useState<DemoIncomingCall | null>(null);
  const [state, setState] = useState<"waiting" | "ringing" | "connecting" | "connected" | "declined" | "error">("waiting");
  const [message, setMessage] = useState("");
  const completedAction = useRef<string | null>(null);
  const completionRequest = useRef<Promise<boolean> | null>(null);
  const conversation = useConversation({
    onConnect: () => setState("connected"),
    onDisconnect: () => setState((current) => current === "connected" ? "waiting" : current),
    onError: () => { setMessage("The call could not connect. Please try again."); setState("error"); },
  });

  useEffect(() => {
    if (!claimCode) { setMessage("This phone link is missing its code."); setState("error"); return; }
    let active = true;
    const poll = async () => {
      try {
        const response = await fetch(`/api/demo-phone/incoming?claim_code=${encodeURIComponent(claimCode)}`);
        if (!response.ok) throw new Error(response.status === 404 ? "This phone link is not recognised." : "Could not check for calls.");
        const body = await response.json() as DemoIncomingCall;
        if (!active) return;
        setIncoming(body);
        if (!body.waiting && state === "waiting") {
          setState("ringing");
          if ("vibrate" in navigator) navigator.vibrate([300, 180, 300]);
        } else if (body.waiting && state === "ringing") {
          setState("waiting");
        }
      } catch (reason) {
        if (active) { setMessage(reason instanceof Error ? reason.message : "Could not check for calls."); setState("error"); }
      }
    };
    void poll();
    const timer = window.setInterval(poll, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [claimCode, state]);

  useEffect(() => () => conversation.endSession(), []);

  const complete = async (outcome: "COMPLETED" | "FAILED" | "TIMED_OUT" = "COMPLETED") => {
    const call = incoming;
    if (!call?.action_id || !call.receiver_token) return false;
    if (completedAction.current === call.action_id && completionRequest.current) return completionRequest.current;
    completedAction.current = call.action_id;
    completionRequest.current = (async () => {
      const response = await fetch("/api/demo-phone/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal_id: call.goal_id, action_id: call.action_id, receiver_token: call.receiver_token, outcome }),
      }).catch(() => null);
      if (!response?.ok) {
        completedAction.current = null;
        completionRequest.current = null;
        return false;
      }
      setIncoming(null);
      return true;
    })();
    return completionRequest.current;
  };

  const previousConversationStatus = useRef(conversation.status);
  useEffect(() => {
    const previous = previousConversationStatus.current;
    previousConversationStatus.current = conversation.status;
    if (previous === "connected" && conversation.status !== "connected") void complete();
  }, [conversation.status, incoming?.action_id, incoming?.receiver_token]);

  const accept = async () => {
    if (!incoming) return;
    setState("connecting");
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const answerResponse = await fetch("/api/demo-phone/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ claim_code: claimCode, action_id: incoming.action_id }),
      });
      if (!answerResponse.ok) throw new Error("The call could not be answered.");
      const answered = await answerResponse.json() as Pick<DemoIncomingCall, "goal_id" | "action_id" | "receiver_token">;
      setIncoming((current) => current ? { ...current, ...answered } : current);
      const response = await fetch("/api/voice/browser-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(answered),
      });
      if (!response.ok) throw new Error("The call could not connect.");
      const session = await response.json() as BrowserSession;
      await conversation.startSession({
        signedUrl: session.signed_url,
        dynamicVariables: session.dynamic_variables,
        overrides: { agent: { language: session.language_code } },
      });
    } catch (reason) {
      await complete("FAILED");
      setMessage(reason instanceof Error && reason.name === "NotAllowedError" ? "Microphone access is needed to answer." : reason instanceof Error ? reason.message : "The call could not connect.");
      setState("error");
    }
  };

  const hangup = async () => {
    const recorded = await complete();
    await conversation.endSession();
    if (recorded) {
      setState("waiting");
      setMessage("");
    } else {
      setMessage("The call ended, but its outcome could not be saved. Please retry.");
      setState("error");
    }
  };

  const decline = async () => {
    setState("declined");
    if (!incoming) return;
    await fetch("/api/demo-phone/decline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_code: claimCode, action_id: incoming.action_id }),
    }).catch(() => undefined);
    setIncoming(null);
  };

  const live = state === "connected" || conversation.status === "connected";
  return <main className={`demo-phone state-${state}`}>
    <div className="demo-phone-glow" />
    <div className="demo-phone-content">
      <div className={`demo-caller-mark ${conversation.isSpeaking ? "speaking" : ""}`}><span>n</span></div>
      {live ? <>
        <p className="demo-call-state">{conversation.isSpeaking ? "nous is speaking" : "nous is listening"}</p>
        <h1>Connected</h1>
        <div className="demo-wave" aria-hidden="true"><i /><i /><i /><i /><i /></div>
        <button className="demo-call-button decline" onClick={() => void hangup()}><X /><span>End</span></button>
      </> : state === "ringing" || state === "connecting" ? <>
        <p className="demo-call-state">{state === "connecting" ? "Connecting…" : "Incoming call"}</p>
        <h1>nous</h1>
        <span className="demo-caller-subtitle">Your appointment caseworker</span>
        <div className="demo-phone-actions">
          <button className="demo-call-button decline" onClick={() => void decline()}><X /><span>Decline</span></button>
          <button className="demo-call-button accept" disabled={state === "connecting"} onClick={() => void accept()}><Phone /><span>Accept</span></button>
        </div>
      </> : <>
        <p className="demo-call-state">{state === "declined" ? "Call declined" : state === "error" ? "Phone unavailable" : "Waiting for a call"}</p>
        <h1>{incoming?.patient_first_name ? `${incoming.patient_first_name}’s phone` : "Your phone"}</h1>
        <span className="demo-caller-subtitle">{message || "Keep this page open"}</span>
        {state === "error" && <button className="demo-phone-retry" onClick={() => window.location.reload()}>Try again</button>}
      </>}
    </div>
    <footer>nous demo phone</footer>
  </main>;
}
type FlowItem = {
  id: string;
  at: string;
  kind: "wake" | "step" | "call" | "write" | "outcome";
  title: string;
  detail?: string;
  step?: AgentStep;
  source?: string;
  facts?: Array<{ label: string; value: string }>;
};
const flowLabel = (type: string) => {
  const labels: Record<string, string> = {
    APPOINTMENT_RESCHEDULED: "Appointment rescheduled",
    CASE_DOCUMENT_VERSION_CREATED: "Appointment document updated",
    CASE_NOTE_RECORDED: "Appointment note recorded",
    SLOT_ACCEPTED: "Slot accepted",
    SLOT_OFFERED: "Earlier slot offered",
    SLOT_REJECTED: "Slot declined",
    SLOT_RELEASED: "Previous slot released",
    VOICE_CALL_COMPLETED: "Patient call completed",
    VOICE_CALL_QUEUED: "Patient call queued",
    VOICE_CALL_REQUESTED: "Patient call requested",
  };
  return labels[type] || type.replaceAll("_", " ").toLowerCase().replace(/^./, (letter) => letter.toUpperCase());
};
const flowFacts = (payload: Record<string, unknown>) => {
  const ignored = new Set(["conversation_id", "document_id", "version_id", "appointment_id"]);
  const labels: Record<string, string> = {
    category: "Category", next_wake_at: "Next wake", note: "Note", outcome: "Outcome",
    reason: "Reason", released_slot_ids: "Released slots", score: "Match score",
    slot_id: "Slot", summary: "Summary", version: "Version",
  };
  return Object.entries(payload)
    .filter(([key, value]) => !ignored.has(key) && value !== null && value !== "" && value !== undefined)
    .slice(0, 4)
    .map(([key, value]) => ({ label: labels[key] || key.replaceAll("_", " "), value: Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value) }));
};
function CaseExecutionFlow({ patient, history }: { patient: Patient; history: CaseHistoryPage | null }) {
  const events = history?.events.length ? history.events : patient.timeline || [];
  const steps = history?.steps.length ? history.steps : patient.agent_steps || [];
  const documents = history?.documents.length ? history.documents : patient.case_documents || [];
  const capacityEvents = events.filter((event) => event.type.toUpperCase() === "CAPACITY_CHANGED");
  const eventItems: FlowItem[] = events.filter((event) => event.type.toUpperCase() !== "CAPACITY_CHANGED").map((event) => {
    const type = event.type.toUpperCase();
    const payload = event.payload || {};
    const kind: FlowItem["kind"] = type.includes("CALL") || type.includes("VOICE")
      ? "call"
      : type.includes("DOCUMENT") || type.includes("NOTE")
        ? "write"
        : type.includes("WAKE") || type.includes("REFERRAL")
          ? "wake"
          : "outcome";
    const facts = flowFacts(payload);
    return { id: `event-${event.id}`, at: event.created_at, kind, title: flowLabel(type), facts, detail: facts[0]?.value, source: event.source };
  });
  if (capacityEvents.length) {
    const latest = capacityEvents[capacityEvents.length - 1];
    eventItems.push({
      id: "capacity-summary",
      at: latest.created_at,
      kind: "wake",
      title: "Capacity re-evaluated",
      detail: `${capacityEvents.length} low-level capacity update${capacityEvents.length === 1 ? "" : "s"} coalesced`,
      source: latest.source,
    });
  }
  const stepItems: FlowItem[] = steps.map((step) => ({
    id: `step-${step.id}`,
    at: step.created_at,
    kind: "step",
    title: runTitle(step),
    detail: step.error || undefined,
    step,
  }));
  const documentItems: FlowItem[] = documents.flatMap((document) =>
    (document.versions || document.version_history || []).map((version) => ({
      id: `document-${document.id}-${version.id || version.version}`,
      at: version.created_at || document.updated_at || document.created_at || "",
      kind: "write" as const,
      title: `${document.title} · version ${version.version}`,
      detail: `Written by ${version.provenance || version.created_by || "source not reported"}`,
      source: "appointment document",
    })),
  );
  const items = [...eventItems, ...stepItems, ...documentItems]
    .filter((item) => item.at)
    .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  if (!items.length) return <Empty label="No execution history recorded for this appointment." />;
  const cycles: Array<{ trigger?: FlowItem; items: FlowItem[] }> = [];
  for (const item of items) {
    if (item.kind === "step" || cycles.length === 0) cycles.push({ trigger: item.kind === "step" ? item : undefined, items: [] });
    if (item.kind !== "step") cycles[cycles.length - 1].items.push(item);
  }
  const nextAction = patient.status === "COMPLETED"
    ? "Appointment complete"
    : patient.blocker
      ? "Case paused"
      : patient.next_wake_at
        ? `Automatic wake ${fmt(patient.next_wake_at)}`
        : "Awaiting the next appointment event";
  return <div className="case-flow">
    <div className="flow-current">
      <div><span>Current state</span><strong>{patient.status.replaceAll("_", " ")}</strong></div>
      <div><span>Next action</span><strong>{nextAction}</strong></div>
      <div><span>Meaningful runs</span><strong>{cycles.length}</strong></div>
    </div>
    <div className="wake-cycles">{cycles.map((cycle, cycleIndex) => {
      const cycleItems = cycle.trigger ? [cycle.trigger, ...cycle.items] : cycle.items;
      const outcome = [...cycle.items].reverse().find((item) => item.kind === "outcome" || item.kind === "call" || item.kind === "write");
      const triggerItem = cycle.items.find((item) => item.kind === "wake") || cycleItems[0];
      const changed = cycle.items.filter((item) => item.kind === "write" || item.kind === "outcome" || item.kind === "call");
      const toolChanges = cycle.trigger?.step?.tool_calls || [];
      const step = cycle.trigger?.step;
      const offerNeedsReview = Boolean(step?.tool_calls.some((call) => call.tool_name === "offer_slot" && call.status.toUpperCase() === "REJECTED"));
      const next = offerNeedsReview ? "Review the existing offer and choose which appointment slot to offer." : cycles[cycleIndex + 1]?.trigger?.title || (cycleIndex === cycles.length - 1 ? nextAction : "Caseworker continued to the next run");
      const triggerTitle = step?.context && "wake_reason" in step.context ? String(step.context.wake_reason) : triggerItem?.kind === "step" ? "Scheduled caseworker review" : triggerItem?.title || "Appointment state changed";
      return <article className="execution-cycle" key={`${cycle.trigger?.id || "initial"}-${cycleIndex}`}>
        <header><div><span>CYCLE {cycleIndex + 1}</span><strong>{step ? runTitle(step) : outcome?.title || "Recorded appointment activity"}</strong></div><time>{fmt(cycle.trigger?.at || cycleItems[0]?.at || null)}</time></header>
        <div className="cycle-narrative">
          <div><span>1 · Trigger</span><strong>{triggerTitle.replaceAll("_", " ")}</strong><p>A persisted appointment event woke the caseworker.</p></div>
          <div className={offerNeedsReview ? "cycle-decision-structured" : ""}><span>2 · Decision</span>{offerNeedsReview && step ? <OfferReviewFacts step={step} /> : <><strong>{step ? runTitle(step) : "Appointment context reviewed"}</strong><p>{step ? conciseDecision(step) : "The caseworker evaluated the current patient and appointment context."}</p></>}</div>
          <div><span>3 · What changed</span><strong>{changed.length || toolChanges.length ? `${changed.length + toolChanges.length} meaningful update${changed.length + toolChanges.length === 1 ? "" : "s"}` : "No durable change"}</strong><p>{changed.slice(0, 2).map((item) => item.title).concat(toolChanges.slice(0, 2).map((tool) => toolLabel(tool.tool_name))).join(" · ") || "The caseworker read context but did not change patient or appointment data."}</p></div>
          <div><span>4 · Outcome</span><strong>{outcome?.title || (step?.error ? "Run failed" : "Run completed")}</strong><p>{outcome?.facts?.[0]?.value || step?.error || "The decision and trace were saved."}</p></div>
          <div className="cycle-next-step"><span>5 · Next step</span><strong>{next}</strong></div>
        </div>
        <details className="raw-trace"><summary>View raw trace · {cycleItems.length} entr{cycleItems.length === 1 ? "y" : "ies"}</summary><div className="cycle-body">{cycleItems.map((item, index) => <FlowEntry key={item.id} item={item} last={index === cycleItems.length - 1} />)}</div></details>
      </article>;
    })}</div>
    <div className="next-wake"><span>Next wake</span><strong>{patient.next_wake_at ? fmt(patient.next_wake_at) : "No wake scheduled"}</strong><small>{patient.blocker ? "Case paused" : displayStatus(patient.status)}</small></div>
  </div>;
}
function FlowEntry({ item, last }: { item: FlowItem; last: boolean }) {
  return (
    <article className={`flow-item flow-${item.kind}`} key={item.id}>
      <div className="flow-rail"><i></i>{!last && <span />}</div>
      <div className="flow-content">
        <header><b>{item.kind}</b><time>{fmt(item.at)}</time></header>
        <strong>{item.title}</strong>
        {item.facts?.length ? <dl className="flow-facts">{item.facts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl> : (item.detail || item.source) && <p>{item.detail || item.source}{item.detail && item.source ? ` · ${item.source}` : ""}</p>}
        {item.step && <>
          <div className="flow-runtime"><span>{item.step.mode === "ANTHROPIC" && item.step.model ? item.step.model : item.step.fallback ? "Rules-based fallback" : item.step.mode || "Runtime not reported"}</span><span>{item.step.agent_version ? `v${item.step.agent_version}` : item.step.agent_spec_version_id ? `spec ${item.step.agent_spec_version_id.slice(0, 8)}` : "Version not reported"}</span></div>
          {item.step.tool_calls.length > 0 && <details className="flow-tools"><summary>{item.step.tool_calls.length} agent action{item.step.tool_calls.length === 1 ? "" : "s"}</summary>{item.step.tool_calls.map((tool) => { const result = toolOutcome(tool); return <div key={tool.id}><b>{toolLabel(tool.tool_name)}</b><span className={`tool-${result.tone}`} title={result.help}>{result.label}</span><p>{tool.result_text}</p></div>; })}</details>}
        </>}
      </div>
    </article>
  );
}
function PatientAgentHistoryPage({ patient, close }: { patient: Patient; close: () => void }) {
  const [history, setHistory] = useState<CaseHistoryPage | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setHistory(null); setError("");
    void fetch(`/api/patients/${patient.id}/agent-history?limit=100`)
      .then(async (response) => { if (!response.ok) throw new Error("Agent history is unavailable."); return response.json(); })
      .then((body) => setHistory({ steps: body.steps || [], events: body.events || [], documents: body.documents || [], next_cursor: body.next_cursor, has_more: body.has_more }))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Unable to load agent history."));
  }, [patient.id]);
  return <section className="patient-history-page">
    <div className="patient-history-head"><button type="button" onClick={close}>← Patient details</button><div><span>AGENT HISTORY</span><h1>{patient.name}</h1><p>Caseworker and overseer runs, tool actions, calls and durable updates.</p></div></div>
    {error ? <div className="history-notice">{error}</div> : !history ? <div className="execution-skeleton" role="status"><i /><i /><i /><span>Loading agent history…</span></div> : <CaseExecutionFlow patient={patient} history={history} />}
  </section>;
}

const CASE_FILE_ORDER = ["overview.md", "preferences.md", "call-notes.md"];
const CASE_FILE_TYPES: Record<string, string> = { "overview.md": "OVERVIEW", "preferences.md": "PREFERENCES", "call-notes.md": "CALL_NOTES" };

function CaseFilesEditor({ goalId, initialDocuments }: { goalId: string; initialDocuments: CaseDocument[] }) {
  const ordered = CASE_FILE_ORDER.map((title) => initialDocuments.find((document) => document.title.toLowerCase() === title)).filter(Boolean) as CaseDocument[];
  const [documents, setDocuments] = useState<CaseDocument[]>(ordered);
  const [activeTitle, setActiveTitle] = useState(CASE_FILE_ORDER[0]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    setDocuments(CASE_FILE_ORDER.map((title) => initialDocuments.find((document) => document.title.toLowerCase() === title)).filter(Boolean) as CaseDocument[]);
  }, [initialDocuments]);
  const document = documents.find((item) => item.title.toLowerCase() === activeTitle);
  const content = typeof document?.content === "string" ? document.content : "";
  const save = async () => {
    if (!draft.trim()) return;
    setSaving(true); setNotice("");
    try {
      const response = await fetch(`/api/goals/${goalId}/documents`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_type: CASE_FILE_TYPES[activeTitle], title: activeTitle, content: draft, metadata: { format: "markdown", provenance: "operator_edit" }, created_by: "OPERATOR" }) });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Unable to save case file.");
      const updated = await response.json();
      const refreshed = await fetch(`/api/goals/${goalId}/documents`).then((result) => result.json());
      setDocuments(refreshed); setEditing(false); setNotice(`${updated.title} saved as version ${updated.current_version}.`);
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : "Unable to save case file."); }
    finally { setSaving(false); }
  };
  return <div className="case-file-editor">
    <div className="case-file-tabs" role="tablist">{CASE_FILE_ORDER.map((title) => <button type="button" role="tab" aria-selected={activeTitle === title} className={activeTitle === title ? "active" : ""} onClick={() => { setActiveTitle(title); setEditing(false); setNotice(""); }} key={title}>{title}</button>)}</div>
    <div className="case-file-toolbar"><span>Version {document?.current_version || 1} · {document?.provenance || "SYSTEM"} · {fmt(document?.updated_at || null)}</span><button type="button" onClick={() => { setDraft(content); setEditing(!editing); }}>{editing ? "Cancel" : "Edit Markdown"}</button></div>
    {editing ? <><textarea className="markdown-editor" value={draft} onChange={(event) => setDraft(event.target.value)} aria-label={`Edit ${activeTitle}`} /><div className="case-file-actions"><button type="button" className="primary" disabled={saving || !draft.trim() || draft === content} onClick={() => void save()}>{saving ? "Saving…" : "Save new version"}</button></div></> : <MarkdownPreview content={content} />}
    {notice && <p className="case-file-notice" role="status">{notice}</p>}
    {document && <details className="case-file-history"><summary>Version history · {(document.versions || []).length}</summary>{(document.versions || []).map((version) => <div key={version.id || String(version.version)}><b>v{version.version}</b><span>{version.created_by || version.provenance || "Unknown"}</span><time>{fmt(version.created_at || null)}</time></div>)}</details>}
  </div>;
}

function MarkdownPreview({ content }: { content: string }) {
  const lines = content.split("\n");
  return <div className="markdown-preview">{lines.map((line, index) => line.startsWith("# ") ? <h4 key={index}>{line.slice(2)}</h4> : line.startsWith("## ") ? <h5 key={index}>{line.slice(3)}</h5> : line.startsWith("- ") ? <div className="markdown-list-item" key={index}>• {line.slice(2)}</div> : line.trim() ? <p key={index}>{line}</p> : <br key={index} />)}</div>;
}

function CaseDocumentCard({ document }: { document: CaseDocument }) {
  const versions = document.versions || document.version_history || [];
  const currentVersion = document.current_version ?? document.version;
  const preview = typeof document.content === "string" ? document.content : document.content ? JSON.stringify(document.content, null, 2) : "";
  return (
    <article className="case-document">
      <div className="case-document-head">
        <FileClock />
        <div><strong>{document.title}</strong><span>{(document.document_type || document.type || "APPOINTMENT DOCUMENT").replaceAll("_", " ")}</span></div>
        <b>v{currentVersion ?? "—"}</b>
      </div>
      <div className="case-document-meta"><span>{document.provenance || "Provenance not reported"}</span><span>Updated {fmt(document.updated_at || document.created_at || null)}</span></div>
      {preview && <p>{preview}</p>}
      <details>
        <summary>Version history <b>{versions.length}</b></summary>
        {versions.length ? <div className="document-versions">{versions.map((version, index) => (
          <div key={version.id || `${version.version}-${index}`}><strong>v{version.version}</strong><span>{version.provenance || version.created_by || "Source not reported"}</span><time>{fmt(version.created_at || null)}</time></div>
        ))}</div> : <Empty label="No earlier versions recorded." />}
      </details>
    </article>
  );
}
function SimpleFeed({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle: string;
  rows: Array<{
    id: string;
    label: string;
    summary: string;
    created_at: string;
  }>;
}) {
  return (
    <div className="page">
      <section className="page-title">
        <div>
          <span className="eyebrow">OPERATIONS</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
      </section>
      <section className="card table-card">
        {rows.length ? (
          rows.map((row) => (
            <div className="feed-row" key={row.id}>
              <div>
                <strong>{row.label.replaceAll("_", " ")}</strong>
                <small>{row.summary}</small>
              </div>
              <span>{fmt(row.created_at)}</span>
            </div>
          ))
        ) : (
          <Empty label={`No ${title.toLowerCase()} recorded yet.`} />
        )}
      </section>
    </div>
  );
}

const callChannelLabel = (channel: string) => {
  const value = channel.toLowerCase();
  if (value.includes("browser") || value.includes("eleven")) return "Browser voice";
  if (value.includes("simulat")) return "Simulated fallback";
  return channel.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
};
const callOutcomeLabel = (outcome?: string) => {
  if (!outcome) return "Pending";
  const value = outcome.toUpperCase();
  if (["FAILED", "ERROR"].includes(value)) return "Failed";
  return value.replaceAll("_", " ").toLowerCase().replace(/^./, (letter) => letter.toUpperCase());
};
const safeCallSummary = (call: Call) => {
  const raw = call.summary?.trim() || "No call summary recorded.";
  if (/404|stack|traceback|provider error|not found/i.test(raw)) return callOutcomeLabel(call.outcome) === "Failed" ? "The call could not be completed." : "Provider details are available in the call record.";
  return raw;
};

function CallsPage({ calls, patients, openPatient }: { calls: Call[]; patients: Patient[]; openPatient: (patient: Patient) => void }) {
  const [patientId, setPatientId] = useState("ALL");
  const [outcome, setOutcome] = useState("ALL");
  const [purpose, setPurpose] = useState("ALL");
  const [expanded, setExpanded] = useState<string | null>(null);
  const outcomes = Array.from(new Set(calls.map((call) => call.outcome).filter(Boolean) as string[])).sort();
  const purposes = Array.from(new Set(calls.map((call) => call.purpose).filter(Boolean) as string[])).sort();
  const visible = calls.filter((call) => patientId === "ALL" || call.goal_id === patientId).filter((call) => outcome === "ALL" || call.outcome === outcome).filter((call) => purpose === "ALL" || call.purpose === purpose);
  return <div className="page">
    <section className="page-title"><div><span className="eyebrow">OPERATIONS</span><h1>Calls</h1><p>Patient conversations handled by the browser voice agent or simulated fallback.</p></div></section>
    <section className="card calls-card">
      <div className="calls-filters">
        <label><span>Patient</span><select value={patientId} onChange={(event) => setPatientId(event.target.value)}><option value="ALL">All patients</option>{patients.map((patient) => <option value={patient.id} key={patient.id}>{patient.name}</option>)}</select></label>
        <label><span>Outcome</span><select value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="ALL">All outcomes</option>{outcomes.map((value) => <option value={value} key={value}>{callOutcomeLabel(value)}</option>)}</select></label>
        <label><span>Call type</span><select value={purpose} onChange={(event) => setPurpose(event.target.value)}><option value="ALL">All call types</option>{purposes.map((value) => <option value={value} key={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
        <span>{visible.length} call{visible.length === 1 ? "" : "s"}</span>
      </div>
      <div className="calls-table-wrap">
        <div className="calls-table-head"><span>Patient</span><span>Call type</span><span>Channel</span><span>Outcome</span><span>Language</span><span>Date &amp; time</span><span>Summary</span></div>
        {visible.map((call) => {
          const patient = patients.find((item) => item.id === call.goal_id);
          const open = expanded === call.id;
          return <div className="call-record" key={call.id}>
            <button className="call-row" type="button" aria-expanded={open} onClick={() => setExpanded(open ? null : call.id)}>
              <span>{patient ? <b className="call-patient-link" role="link" onClick={(event) => { event.stopPropagation(); openPatient(patient); }}>{patient.name}</b> : <b>Patient record</b>}<small>{patient?.external_ref || call.goal_id.slice(0, 8)}</small></span>
              <span><b>{(call.purpose || "Follow-up").replaceAll("_", " ")}</b><small>{call.direction.toLowerCase()}</small></span>
              <span><b>{callChannelLabel(call.channel)}</b></span>
              <span><Status status={callOutcomeLabel(call.outcome)} /></span>
              <span><b>{call.language || patient?.language || "—"}</b></span>
              <span><b>{fmt(call.created_at)}</b></span>
              <span><small>{safeCallSummary(call)}</small></span>
            </button>
            {open && <div className="call-detail"><div><span>Full summary</span><p>{safeCallSummary(call)}</p></div><dl><div><dt>Provider reference</dt><dd>{call.provider_id || "Not recorded"}</dd></div><div><dt>Transport</dt><dd>{callChannelLabel(call.channel)}</dd></div><div><dt>Outcome</dt><dd>{callOutcomeLabel(call.outcome)}</dd></div></dl></div>}
          </div>;
        })}
        {!visible.length && <Empty label="No calls match these filters." />}
      </div>
    </section>
  </div>;
}

function OverseerWorkflow({ patients, openPatient }: { patients: Patient[]; openPatient: (patient: Patient) => void }) {
  const [workflow, setWorkflow] = useState<OverseerWorkflowData | null>(() => workflowCache);
  const [error, setError] = useState("");
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoResult, setDemoResult] = useState<{ phone_url?: string; selected_patient?: string } | null>(null);
  const demoMode = new URLSearchParams(window.location.search).get("demo") === "1";
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const body = await loadWorkflow();
        if (!cancelled) { setWorkflow(body); setError(""); }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load the overseer workflow.");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  const triggerDemo = async () => {
    setDemoRunning(true); setError("");
    try {
      const response = await fetch("/api/demo/trigger-released-slot", { method: "POST", headers: { "X-Nous-Demo": "1" } });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Could not prepare the released-slot demo.");
      setDemoResult(body);
      const workflowResponse = await fetch("/api/overseer/workflow");
      if (workflowResponse.ok) {
        workflowCache = await workflowResponse.json();
        setWorkflow(workflowCache);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not prepare the released-slot demo."); }
    finally { setDemoRunning(false); }
  };
  const selectedPatient = workflow?.selected_patient ? patients.find((patient) => patient.id === workflow.selected_patient?.goal_id) : undefined;
  const scanScheduled = workflow?.run_state === "NEXT_SCAN_SCHEDULED";
  return <div className="page overseer-live-page">
    <section className="page-title"><div><span className="eyebrow">LIVE AUTOMATION</span><h1>{scanScheduled ? "Next scan scheduled" : "Scanning slots"}</h1><p>Continuously triaging available appointments in the next 7 days and waking patient caseworkers.</p></div><span className="live-indicator"><i /> {scanScheduled ? "Scheduled" : "Active · running"}</span></section>
    {demoMode && <details className="demo-controls"><summary>Demo controls</summary><div><button type="button" className="primary" disabled={demoRunning} onClick={() => void triggerDemo()}>{demoRunning ? "Preparing…" : "Trigger released-slot demo"}</button>{demoResult?.phone_url && <a href={demoResult.phone_url} target="_blank" rel="noreferrer">Open {demoResult.selected_patient || "selected patient"} phone</a>}</div></details>}
    <section className="card overseer-goal-strip">
      <div><span>Current step</span><strong>{scanScheduled ? "Next scan scheduled" : workflow?.action?.phone_status || "Scanning available appointments"}</strong></div>
      <div><span>Iteration started</span><strong>{fmt(workflow?.iteration_started_at || workflow?.updated_at || null)}</strong></div>
      <div><span>Next wake</span><strong>{workflow?.next_wake_at ? fmt(workflow.next_wake_at) : `Within ${workflow?.next_wake_seconds || 60} seconds`}</strong></div>
    </section>
    {error ? <section className="card trace-empty trace-error-text"><strong>Workflow unavailable</strong><span>{error}</span></section> : !workflow ? <section className="card trace-empty"><strong>Loading overseer activity…</strong></section> : !workflow.active ? <section className="card overseer-waiting"><Sparkles /><div><strong>Waiting for a released slot</strong><span>When an appointment is cancelled or rescheduled, the overseer will rank compatible patients automatically.</span></div></section> : <>
      {workflow.selected_patient && <section className="card overseer-hero">
        <div><span>Released appointment</span><strong>{workflow.slot?.procedure || "Appointment"} · {fmt(workflow.slot?.starts_at || null)}</strong><small>{workflow.slot?.site || "Site not recorded"}</small></div>
        <div><span>Selected patient</span><strong>{workflow.selected_patient?.name || "Selection pending"}</strong><small>{workflow.action?.phone_status || "Caseworker delegation pending"}</small></div>
        {selectedPatient && <button onClick={() => openPatient(selectedPatient)}>Open patient</button>}
      </section>}
      <section className="card overseer-loop-card"><OverseerLoop workflow={workflow} detailed /></section>
      <section className="overseer-iteration-summary"><div><span>Current pass</span><strong>{workflow.scan_stats ? `${workflow.scan_stats.slots_checked || 0} slots checked · ${workflow.scan_stats.compatible_patients || 0} active patients · ` : ""}{workflow.last_iteration_summary || "No actionable release this pass"}</strong></div><div><span>Total delegations</span><strong>{workflow.total_delegations || 0}</strong></div></section>
      {workflow.selected_patient && <section className="overseer-detail-grid">
        <div className="card overseer-shortlist"><header><div><span className="eyebrow">TRIAGE</span><h2>Ranked shortlist</h2></div><b>{workflow.candidates.length} evaluated</b></header>
          <div className="shortlist-rows">{workflow.candidates.map((candidate) => <div className={candidate.selected ? "selected" : ""} key={candidate.goal_id}>
            <strong>#{candidate.rank}</strong><span><b>{candidate.patient_name}</b><small>{candidate.reasons.join(" · ")}</small></span>{candidate.selected && <em>Selected</em>}
          </div>)}</div>
        </div>
        <div className="card overseer-rationale"><span className="eyebrow">WHY THIS PATIENT</span><h2>Clinician urgency, then appointment fit</h2><p>{workflow.rationale}</p><dl><div><dt>Policy</dt><dd>Clinician-recorded urgency first</dd></div><div><dt>Tiebreaker</dt><dd>Largest safe improvement in appointment date</dd></div><div><dt>Next</dt><dd>{workflow.action?.phone_status || "Delegate to caseworker"}</dd></div></dl></div>
      </section>}
    </>}
  </div>;
}

function AgentActivity({ rows, patients, openPatient, loading, error, embedded = false }: { rows: ActivityItem[]; patients: Patient[]; openPatient: (patient: Patient) => void; loading: boolean; error: string; embedded?: boolean }) {
  const runs = rows.filter((row) => row.kind === "AGENT_STEP") as AgentStep[];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [role, setRole] = useState<"all" | "caseworker" | "overseer">("all");
  const roleFor = (run: AgentStep) => (run.agent_role || String(run.context?.agent_spec && (run.context.agent_spec as Record<string, unknown>).role || "caseworker")).toLowerCase().includes("overseer") ? "overseer" : "caseworker";
  const filteredRuns = runs.filter((run) => role === "all" || roleFor(run) === role);
  const selected = filteredRuns.find((run) => run.id === selectedId) || filteredRuns[0];
  return (
    <div className={embedded ? "embedded-page" : "page"}>
      {!embedded && <section className="page-title"><div><span className="eyebrow">OPERATIONS</span><h1>Agent activity</h1><p>Persisted runs with model and tool-call spans. No inferred executions.</p></div></section>}
      <section className="card trace-explorer">
        {loading && !runs.length ? <div className="trace-empty"><strong>Loading recorded runs…</strong><span>Reading persisted model and tool-call traces.</span></div> : error && !runs.length ? <div className="trace-empty trace-error-text"><strong>Could not load agent activity</strong><span>{error}</span></div> : runs.length ? <>
          <nav className="run-list" aria-label="Recorded agent runs">
            <header><strong>Runs</strong><span>{filteredRuns.length} shown</span></header>
            <div className="trace-role-filter" role="group" aria-label="Filter by agent role">
              {(["all", "caseworker", "overseer"] as const).map((item) => <button key={item} className={role === item ? "active" : ""} onClick={() => { setRole(item); setSelectedId(null); }}>{item === "all" ? "All" : item === "caseworker" ? "Caseworker" : "Overseer"}</button>)}
            </div>
            {filteredRuns.map((run) => {
              const patient = patients.find((item) => item.id === run.goal_id);
              const outcome = runOutcome(run);
              return <button className={`run-list-item ${run.id === selected?.id ? "active" : ""}`} key={run.id} onClick={() => setSelectedId(run.id)}>
                <i className={`run-marker status-${outcome.tone}`} aria-hidden="true"></i>
                <span><strong>{runTitle(run)}</strong><small>{patient?.name || "Patient record"} · {roleFor(run) === "overseer" ? "Overseer" : "Caseworker"}</small><time>{fmt(run.created_at)}</time></span>
                <b>{run.tool_calls.length} {run.tool_calls.length === 1 ? "step" : "steps"}</b>
              </button>;
            })}
            {!filteredRuns.length && <p className="run-list-empty">No {role} runs recorded.</p>}
          </nav>
          {selected ? <RunWaterfall step={selected} patient={patients.find((patient) => patient.id === selected.goal_id)} openPatient={openPatient} /> : <div className="trace-empty"><strong>No matching runs</strong><span>Choose another agent filter to see recorded activity.</span></div>}
        </> : <div className="trace-empty"><strong>No agent runs yet</strong><span>Runs appear here automatically when a caseworker wakes for an appointment.</span></div>}
      </section>
    </div>
  );
}

const durationLabel = (duration?: number | null) => duration == null ? null : duration < 1000 ? `${duration} ms` : `${(duration / 1000).toFixed(2)} s`;
const toolCategory = (name: string) => name.includes("read") || name.includes("search") || name.includes("list") || name.includes("get_") ? "read" : name.includes("write") || name.includes("constraint") ? "write" : name.includes("offer") || name.includes("accept") || name.includes("reject") || name.includes("call") ? "action" : name.includes("human") ? "handoff" : "control";
const toolOutcome = (call: ToolCall) => {
  const status = call.status.toUpperCase();
  if (status === "OK" || status === "COMPLETED" || status === "SUCCESS") return { label: "Completed", tone: "ok", help: "The tool ran and saved or returned its result." };
  if (status === "REJECTED") return { label: "No change made", tone: "blocked", help: "A scheduling rule prevented this action. The agent continued safely; this is not a system error." };
  return { label: "Failed", tone: "bad", help: "The tool could not complete because of a technical error." };
};
type StructuredDecision = {
  title?: string;
  trigger?: string;
  reason?: string;
  candidate_slots?: Array<{ starts_at?: string; site?: string }>;
  actions_taken?: string[];
  booking_released?: boolean;
  outcome?: string;
  next_action?: string;
};
const structuredDecision = (step: AgentStep): StructuredDecision | null => {
  try {
    const value = JSON.parse(step.decision || "");
    return value && typeof value === "object" && !Array.isArray(value) ? value as StructuredDecision : null;
  } catch { return null; }
};
const runOutcome = (step: AgentStep) => {
  if (step.error) return { label: "Paused", tone: "bad" };
  if (step.tool_calls.some((call) => call.status.toUpperCase() === "REJECTED")) return { label: "Completed with no change", tone: "blocked" };
  return { label: "Completed", tone: "ok" };
};
const runTitle = (step: AgentStep) => {
  const structured = structuredDecision(step);
  if (structured?.title) return structured.title;
  if (step.error) return "Agent run paused";
  const calls = step.tool_calls;
  const rejected = calls.find((call) => call.status.toUpperCase() === "REJECTED");
  if (rejected?.tool_name === "offer_slot") return "Appointment offer paused";
  if (rejected) return `${toolLabel(rejected.tool_name)} was not applied`;
  const action = [...calls].reverse().find((call) => !["end_step", "read_case_notes", "read_case_documents", "nous_get_case"].includes(call.tool_name));
  return action ? `${toolLabel(action.tool_name)} completed` : "Appointment reviewed";
};
function OfferReviewFacts({ step }: { step: AgentStep }) {
  const structured = structuredDecision(step);
  const legacySlots = Array.from(step.decision?.matchAll(/(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})\s*UTC/g) || []).map((match) => ({ starts_at: `${match[1]}T${match[2]}:00Z`, site: (step.decision || "").match(/\(([^)]+site)\)/i)?.[1] || "Main site" }));
  const slots = structured?.candidate_slots?.length ? structured.candidate_slots : legacySlots;
  const actions = structured?.actions_taken?.length ? structured.actions_taken : ["Appointment note recorded", "Case paused"];
  const released = structured?.booking_released ?? !/no existing booking to release/i.test(step.decision || "");
  return <dl className="decision-facts">
    <div className="fact-reason"><dt>Reason</dt><dd>{structured?.reason || "An appointment offer is already open, so the agent did not create another one."}</dd></div>
    <div className="fact-slots"><dt>Alternative slots</dt><dd>{slots.length ? <ul>{slots.map((slot, index) => <li key={`${slot.starts_at}-${index}`}><strong>{slot.starts_at ? fmt(slot.starts_at) : "Time not reported"}</strong><span>{slot.site || "Site not reported"}</span></li>)}</ul> : "No alternative slots were recorded."}</dd></div>
    <div className="fact-actions"><dt>Action taken</dt><dd><ul>{actions.map((action) => <li key={action}>{action.replace(/^[-*]\s*/, "")}</li>)}</ul></dd></div>
    <div className="fact-release"><dt>Booking released</dt><dd><b className={`yes-no-badge ${released ? "yes" : "no"}`}>{released ? "Yes" : "No"}</b></dd></div>
  </dl>;
}
const conciseDecision = (step: AgentStep) => {
  if (step.error) return "The agent could not complete this run and scheduled follow-up work.";
  const decision = (step.decision || "").trim();
  const sentence = decision.split(/(?<=[.!?])\s/)[0];
  return sentence && sentence.length <= 180 ? sentence : `${step.tool_calls.length} recorded tool ${step.tool_calls.length === 1 ? "action" : "actions"}; ${toolLabel(step.tool_calls.at(-1)?.tool_name || "end_step").toLowerCase()}.`;
};
function RunWaterfall({ step, patient, openPatient }: { step: AgentStep; patient?: Patient; openPatient: (patient: Patient) => void }) {
  const tokenTotal = step.input_tokens + step.output_tokens;
  const hasTiming = Boolean(step.duration_ms && step.tool_calls.some((call) => call.started_at && call.duration_ms != null));
  const outcome = runOutcome(step);
  const offerNeedsReview = step.tool_calls.some((call) => call.tool_name === "offer_slot" && call.status.toUpperCase() === "REJECTED");
  const tickCount = 5;
  return <div className="waterfall-panel">
    <header className="waterfall-head">
      <div><span>{(step.agent_role || "CASEWORKER").toUpperCase()} RUN</span><h2>{runTitle(step)}</h2><p>{patient ? <>For <button className="patient-trace-link" onClick={() => openPatient(patient)}>{patient.name}</button> · {patient.external_ref} · {fmt(step.created_at)}</> : <>Patient record {step.goal_id.slice(0, 8)}… · {fmt(step.created_at)}</>}</p></div>
      <b className={`run-status status-${outcome.tone}`}>{outcome.label}</b>
    </header>
    {offerNeedsReview ? <OfferReviewFacts step={step} /> : <p className="decision-summary">{conciseDecision(step)}</p>}
    {step.decision && <details className="raw-decision"><summary>Show full agent reasoning</summary><p>{step.decision}</p></details>}
    <div className="waterfall-meta">
      <span>Agent model <b>{step.mode === "ANTHROPIC" && step.model ? step.model : step.fallback ? "Rules-based fallback" : step.mode}</b></span>
      {durationLabel(step.duration_ms) && <span>Duration <b>{durationLabel(step.duration_ms)}</b></span>}
      {tokenTotal > 0 && <span>Tokens <b>{step.input_tokens} in · {step.output_tokens} out</b></span>}
      <span>Run ended <b>{step.stop_reason === "tool_use" ? "After tool actions" : step.stop_reason === "end_turn" ? "Normally" : step.stop_reason || "Not reported"}</b></span>
    </div>
    {step.error && <p className="trace-error-text">{step.error}</p>}
    <div className={`waterfall-chart ${hasTiming ? "timed" : "sequence"}`}>
    <div className="waterfall-scale">{hasTiming ? Array.from({ length: tickCount }, (_, index) => <span key={index}>{durationLabel((step.duration_ms || 0) * index / (tickCount - 1))}</span>) : <><span>First action</span><strong>Sequence only · timing was not recorded</strong><span>Last action</span></>}</div>
    <div className="timeline-grid" aria-hidden="true">{Array.from({ length: tickCount }, (_, index) => <i key={index} style={{ left: `${index * 100 / (tickCount - 1)}%` }} />)}</div>
    <div className="span-row model-span"><span>Agent considered context</span><i title={`Agent model: ${step.model || step.mode}\nOutcome: ${outcome.label}\n${durationLabel(step.duration_ms) || "Timing unavailable"}`}></i><b title="This is the model reasoning step, before and between tool actions.">{step.error ? "Failed" : "Reasoning"}</b></div>
    {step.tool_calls.map((call, index) => {
      const callOutcome = toolOutcome(call);
      const width = hasTiming && step.duration_ms && call.duration_ms ? Math.max(2, Math.min(92, call.duration_ms / step.duration_ms * 100)) : 14;
      const left = hasTiming && step.duration_ms && call.started_at
        ? Math.max(0, Math.min(92, (new Date(call.started_at).getTime() - new Date(step.created_at).getTime()) / step.duration_ms * 100))
        : step.tool_calls.length === 1 ? 43 : index * 84 / (step.tool_calls.length - 1);
      const hover = `${toolLabel(call.tool_name)}\nOutcome: ${callOutcome.label}\n${callOutcome.help}\n${call.started_at ? `Started: ${fmt(call.started_at)}\n` : ""}${durationLabel(call.duration_ms) ? `Duration: ${durationLabel(call.duration_ms)}\n` : "Timing: not recorded\n"}Input: ${JSON.stringify(call.tool_input)}\nResult: ${call.result_text || "No result recorded"}`;
      return <details className={`span-detail category-${toolCategory(call.tool_name)} status-${callOutcome.tone}`} key={call.id}>
        <summary className="span-row tool-span"><span>#{call.sequence} {toolLabel(call.tool_name)}</span><i title={hover} style={{ marginLeft: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}></i><b className={`tool-${callOutcome.tone}`} title={callOutcome.help}>{callOutcome.label}{durationLabel(call.duration_ms) ? ` · ${durationLabel(call.duration_ms)}` : ""}</b></summary>
        <div className="span-io"><div><span>Input</span><pre>{JSON.stringify(call.tool_input, null, 2)}</pre></div><div><span>Result</span><pre>{call.result_text || "No result text recorded."}</pre></div></div>
      </details>;
    })}
    {!step.tool_calls.length && <p className="no-tools">This persisted run did not call any tools.</p>}
    </div>
  </div>;
}

function AgentTrace({ step }: { step: AgentStep }) {
  return (
    <details className={`agent-trace ${step.error ? "trace-error" : ""}`}>
      <summary>
        <div><strong>{step.decision || "Agent step"}</strong><small>{step.mode}{step.model ? ` · ${step.model}` : ""}{step.fallback ? " · fallback" : ""}</small></div>
        <div><b>{step.tool_calls.length} tools</b><span>{fmt(step.created_at)}</span></div>
      </summary>
      <div className="trace-body">
        <div className="trace-meta"><span>Stop: <b>{step.stop_reason || "—"}</b></span><span>Tokens: <b>{step.input_tokens} in / {step.output_tokens} out</b></span></div>
        {step.error && <p className="trace-error-text">{step.error}</p>}
        {step.tool_calls.length ? step.tool_calls.map((call) => (
          <article className="tool-call" key={call.id}>
            <header><span>#{call.sequence}</span><strong>{toolLabel(call.tool_name)}</strong><b className={call.status === "OK" ? "tool-ok" : "tool-bad"}>{call.status}</b></header>
            <div><span>Input</span><pre>{JSON.stringify(call.tool_input, null, 2)}</pre></div>
            <div><span>Result</span><pre>{call.result_text}</pre></div>
          </article>
        )) : <p className="no-tools">This step did not call any tools.</p>}
      </div>
    </details>
  );
}

function DemoResetDialog({ close, reset, resetting }: { close: () => void; reset: () => void; resetting: boolean }) {
  return (
    <div className="overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !resetting) close(); }}>
      <section className="dialog reset-demo-dialog" role="dialog" aria-modal="true" aria-labelledby="reset-demo-title">
        <div className="drawer-head">
          <span id="reset-demo-title">Reset demo?</span>
          <button type="button" onClick={close} disabled={resetting} aria-label="Close reset confirmation"><X /></button>
        </div>
        <div className="reset-demo-copy">
          <div className="reset-demo-icon"><RotateCcw /></div>
          <div>
            <strong>Restore the presenter starting state</strong>
            <p>This affects only patient records whose reference starts with <code>DEMO-</code>. It clears demo offers, call actions, Overseer selections and stale blockers, then validates five booked demo appointments.</p>
            <p>Non-demo patient records and capacity linked to them are never changed. Valid demo notes, documents and completed traces are preserved.</p>
          </div>
        </div>
        <div className="drawer-actions">
          <button type="button" onClick={close} disabled={resetting}>Cancel</button>
          <button className="danger-button" type="button" onClick={reset} disabled={resetting}>
            {resetting ? "Resetting and validating…" : "Reset demo"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ReferralDialog({
  close,
  save,
  saving,
  appointmentTypes,
  catalogueError,
}: {
  close: () => void;
  save: (body: Record<string, unknown>) => void;
  saving: boolean;
  appointmentTypes: AppointmentType[];
  catalogueError: string;
}) {
  const [appointmentTypeId, setAppointmentTypeId] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [dateOfBirthError, setDateOfBirthError] = useState("");
  const selectedType = appointmentTypes.find((type) => type.id === appointmentTypeId);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const latestBirthDate = [yesterday.getFullYear(), String(yesterday.getMonth() + 1).padStart(2, "0"), String(yesterday.getDate()).padStart(2, "0")].join("-");
  const validateDateOfBirth = (value: string) => {
    if (!value) return "Enter a date of birth.";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Enter a valid date of birth.";
    const [year, month, day] = value.split("-").map(Number);
    const parsed = new Date(year, month - 1, day);
    if (parsed.getFullYear() !== year || parsed.getMonth() !== month - 1 || parsed.getDate() !== day) return "Enter a valid date of birth.";
    const today = new Date(); today.setHours(0, 0, 0, 0);
    if (parsed >= today) return "Date of birth must be in the past.";
    return "";
  };
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const dobError = validateDateOfBirth(dateOfBirth);
    setDateOfBirthError(dobError);
    if (dobError) return;
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (!selectedType) return;
    save({ ...data, appointment_type_id: selectedType.id, procedure: selectedType.procedure || selectedType.code || selectedType.name });
  };
  return (
    <div className="overlay">
      <form className="dialog" onSubmit={submit}>
        <div className="drawer-head">
          <span>New referral</span>
          <button type="button" onClick={close} disabled={saving} aria-label="Close new referral form">
            <X />
          </button>
        </div>
        <div className="form-grid">
          <label className="field appointment-type-field">
            <span>Appointment type</span>
            <select name="appointment_type_id" value={appointmentTypeId} onChange={(event) => setAppointmentTypeId(event.target.value)} required disabled={!appointmentTypes.length}>
              <option value="">Select appointment type</option>
              {appointmentTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
            </select>
            <small>MRI, physio and other appointment types use different capacity and are matched independently.</small>
            {!appointmentTypes.length && <small className="field-error">{catalogueError || "No active appointment types are available."}</small>}
          </label>
          <Field name="external_ref" label="Patient reference" required />
          <Field name="first_name" label="First name" required />
          <Field name="last_name" label="Last name" required />
          <label className="field">
            <span>Date of birth</span>
            <input
              name="date_of_birth"
              type="date"
              value={dateOfBirth}
              max={latestBirthDate}
              required
              aria-invalid={Boolean(dateOfBirthError)}
              aria-describedby="date-of-birth-error"
              onChange={(event) => { setDateOfBirth(event.target.value); if (dateOfBirthError) setDateOfBirthError(validateDateOfBirth(event.target.value)); }}
              onBlur={() => setDateOfBirthError(validateDateOfBirth(dateOfBirth))}
            />
            {dateOfBirthError && <small id="date-of-birth-error" className="field-error">{dateOfBirthError}</small>}
          </label>
          <Field name="phone" label="Phone" type="tel" required />
          <Field name="email" label="Email" type="email" />
          <Field name="preferred_language" label="Language" value="English" />
          {selectedType && <div className="preparation-note"><strong>Preparation</strong><span>{selectedType.preparation_requirements || selectedType.preparation_note || "No preparation requirements recorded."}</span></div>}
          <input type="hidden" name="preferred_contact_method" value="VOICE" />
          <input type="hidden" name="pathway_type" value={selectedType?.name || "Appointment scheduling"} />
          <input type="hidden" name="provider_org" value="nous scheduling" />
          <input type="hidden" name="referring_org" value="" />
        </div>
        <div className="drawer-actions">
          <button type="button" onClick={close} disabled={saving}>
            Cancel
          </button>
          <button className="primary" type="submit" disabled={saving || !appointmentTypes.length || !appointmentTypeId}>
            {saving ? "Creating referral…" : "Create referral"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({
  name,
  label,
  type = "text",
  value,
  required = false,
}: {
  name: string;
  label: string;
  type?: string;
  value?: string;
  required?: boolean;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input name={name} type={type} defaultValue={value} required={required} />
    </label>
  );
}
function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <ConversationProvider>{window.location.pathname === "/phone" ? <DemoPhone /> : <App />}</ConversationProvider>,
);
