import { useCallback, useEffect, useRef, useState } from "react";
import { api, hospitalWsUrl } from "./api.js";

const CAPABILITY_STATUS = ["AVAILABLE", "UNAVAILABLE"];
const DEPARTMENT_FIELDS = [
  "trauma_status",
  "cardiology_status",
  "neurology_status",
  "ct_status",
  "cath_lab_status",
];

function humanizeCapability(key) {
  const special = { icu: "ICU", ct: "CT", cath_lab: "Cath lab", blood_bank: "Blood bank" };
  if (special[key]) return special[key];
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function emptyForm() {
  return {
    icu_available: 0,
    icu_total: 0,
    emergency_beds_available: 0,
    emergency_beds_total: 0,
    trauma_status: "AVAILABLE",
    cardiology_status: "AVAILABLE",
    neurology_status: "AVAILABLE",
    ct_status: "AVAILABLE",
    cath_lab_status: "AVAILABLE",
    accepting_patients: true,
  };
}

function formFromStatus(status) {
  if (!status) return emptyForm();
  const form = emptyForm();
  for (const key of Object.keys(form)) form[key] = status[key];
  return form;
}

function Vitals({ patient }) {
  return (
    <ul className="vitals">
      <li>Age {patient.age}</li>
      <li>{patient.conscious ? "Conscious" : "Unconscious"}</li>
      <li>SpO2 {patient.spo2}%</li>
      <li>HR {patient.heart_rate} bpm</li>
      <li>BP {patient.bp}</li>
    </ul>
  );
}

function RequiredCapabilities({ capabilities }) {
  const items = Object.entries(capabilities).filter(([, value]) => value !== false);
  return (
    <ul className="capabilities">
      {items.map(([key, value]) => (
        <li key={key}>
          <span className={value === true ? "tag required" : "tag preferred"}>
            {value === true ? "Required" : "Preferred"}
          </span>
          {humanizeCapability(key)}
        </li>
      ))}
    </ul>
  );
}

function AlertCard({ alert, onRespond }) {
  const { snapshot } = alert;
  const responding = alert.responding;
  const error = alert.error;

  return (
    <div className={`alert-card status-${alert.status.toLowerCase()}`}>
      <div className="alert-head">
        <span className="emergency-type">{snapshot.emergency_type}</span>
        <span className={`severity severity-${snapshot.severity.toLowerCase()}`}>
          {snapshot.severity}
        </span>
      </div>
      <p className="case-ref">Case {alert.case_id}</p>
      <div className="alert-section">
        <strong>Patient</strong>
        <Vitals patient={snapshot.patient} />
      </div>
      <div className="alert-section">
        <strong>Required capabilities</strong>
        <RequiredCapabilities capabilities={snapshot.required_capabilities} />
      </div>
      <p className="eta">
        ETA {snapshot.eta_minutes != null ? `${snapshot.eta_minutes} min` : "—"}
      </p>
      {error && <p className="error">{error}</p>}
      <div className="button-row">
        <button
          className="btn accept"
          disabled={responding || alert.status !== "PENDING"}
          onClick={() => onRespond(alert, "accept")}
        >
          ACCEPT
        </button>
        <button
          className="btn reject"
          disabled={responding || alert.status !== "PENDING"}
          onClick={() => onRespond(alert, "reject")}
        >
          UNABLE TO RECEIVE
        </button>
      </div>
      {alert.status !== "PENDING" && (
        <p className="muted">
          {alert.status === "ACCEPTED"
            ? "Accepted — ambulance en route"
            : "Rejected — case re-routed"}
        </p>
      )}
    </div>
  );
}

function StatusForm({ status, form, onChange, onUpdate, updating, message }) {
  return (
    <div className="card">
      <h2>Capacity status</h2>
      <p className="muted">
        {status
          ? `Last updated ${new Date(status.updated_at).toLocaleTimeString()}`
          : "No status reported yet"}
      </p>

      <div className="grid-2">
        <label className="field">
          <span>ICU beds available</span>
          <input
            type="number"
            min="0"
            value={form.icu_available}
            onChange={(e) => onChange("icu_available", e.target.value)}
          />
        </label>
        <label className="field">
          <span>ICU beds total</span>
          <input
            type="number"
            min="0"
            value={form.icu_total}
            onChange={(e) => onChange("icu_total", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Emergency beds available</span>
          <input
            type="number"
            min="0"
            value={form.emergency_beds_available}
            onChange={(e) => onChange("emergency_beds_available", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Emergency beds total</span>
          <input
            type="number"
            min="0"
            value={form.emergency_beds_total}
            onChange={(e) => onChange("emergency_beds_total", e.target.value)}
          />
        </label>
      </div>

      {DEPARTMENT_FIELDS.map((field) => (
        <label className="field" key={field}>
          <span>{humanizeCapability(field).replace("Status", " status")}</span>
          <select
            value={form[field]}
            onChange={(e) => onChange(field, e.target.value)}
          >
            {CAPABILITY_STATUS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      ))}

      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.accepting_patients}
          onChange={(e) => onChange("accepting_patients", e.target.checked)}
        />
        Accepting patients
      </label>

      {message && (
        <p className={message.kind === "error" ? "error" : "success"}>{message.text}</p>
      )}
      <div className="button-row">
        <button className="btn primary" disabled={updating} onClick={onUpdate}>
          {updating ? "Updating…" : "Update Status"}
        </button>
      </div>
    </div>
  );
}

function HospitalSelect({ hospitals, hospitalId, onSelect, onOpen, error, loading }) {
  return (
    <div className="card">
      <h2>Hospital dashboard</h2>
      {loading && <p className="loading">Loading hospitals…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && (
        <>
          <label className="field">
            <span>Select hospital</span>
            <select value={hospitalId} onChange={(e) => onSelect(e.target.value)}>
              {hospitals.map((hospital) => (
                <option key={hospital._id} value={hospital._id}>
                  {hospital.name}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              className="btn primary"
              disabled={!hospitalId}
              onClick={onOpen}
            >
              Open dashboard
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function App() {
  const [hospitals, setHospitals] = useState([]);
  const [hospitalId, setHospitalId] = useState("");
  const [hospitalName, setHospitalName] = useState("");
  const [hospitalsError, setHospitalsError] = useState("");
  const [hospitalsLoading, setHospitalsLoading] = useState(true);

  const [view, setView] = useState("select");
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [updating, setUpdating] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null);

  const [alerts, setAlerts] = useState([]);
  const [wsStatus, setWsStatus] = useState("idle");
  const wsRef = useRef(null);
  const alertsRef = useRef([]);

  useEffect(() => {
    let cancelled = false;
    setHospitalsLoading(true);
    api("/hospitals")
      .then((data) => {
        if (cancelled) return;
        setHospitals(data);
        if (data.length > 0) setHospitalId(data[0]._id);
      })
      .catch((err) => !cancelled && setHospitalsError(err.message))
      .finally(() => !cancelled && setHospitalsLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const loadStatus = useCallback((id) => {
    setStatusMessage(null);
    setStatus(null);
    api(`/hospitals/${id}/status`)
      .then((data) => {
        setStatus(data);
        setForm(formFromStatus(data));
      })
      .catch((err) => {
        if (err.message.includes("not found")) {
          setForm(emptyForm());
        } else {
          setStatusMessage({ kind: "error", text: err.message });
        }
      });
  }, []);

  const openDashboard = useCallback(() => {
    const hospital = hospitals.find((h) => h._id === hospitalId);
    setHospitalName(hospital ? hospital.name : "");
    setAlerts([]);
    alertsRef.current = [];
    setView("dashboard");
    setWsStatus("connecting");
    loadStatus(hospitalId);
  }, [hospitals, hospitalId, loadStatus]);

  useEffect(() => {
    if (view !== "dashboard" || !hospitalId) return undefined;

    let socket;
    let closed = false;
    let reconnectTimer = null;

    const connect = () => {
      setWsStatus("connecting");
      socket = new WebSocket(hospitalWsUrl(hospitalId));

      socket.onopen = () => {
        if (closed) return;
        setWsStatus("open");
      };

      socket.onmessage = (event) => {
        if (closed) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === "ping" || !message.case_id) return;
          setAlerts((prev) => {
            if (prev.some((a) => a.id === message.id)) return prev;
            const next = [...prev, { ...message, status: "PENDING", responding: false, error: "" }];
            alertsRef.current = next;
            return next;
          });
        } catch {
          // ignore malformed messages
        }
      };

      socket.onclose = () => {
        if (closed) return;
        setWsStatus("closed");
        reconnectTimer = setTimeout(connect, 3000);
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) socket.close();
    };
  }, [view, hospitalId]);

  const handleUpdateStatus = useCallback(async () => {
    setUpdating(true);
    setStatusMessage(null);
    try {
      const saved = await api(`/hospitals/${hospitalId}/status`, {
        method: "POST",
        body: JSON.stringify({ hospital_id: hospitalId, ...form }),
      });
      setStatus(saved);
      setForm(formFromStatus(saved));
      setStatusMessage({ kind: "success", text: "Status updated" });
    } catch (err) {
      setStatusMessage({ kind: "error", text: err.message });
    } finally {
      setUpdating(false);
    }
  }, [hospitalId, form]);

  const handleRespond = useCallback(
    async (alert, action) => {
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === alert.id ? { ...a, responding: true, error: "" } : a
        )
      );
      try {
        const saved = await api(`/hospital-alerts/${alert.id}/${action}`, {
          method: "POST",
        });
        setAlerts((prev) =>
          prev.map((a) =>
            a.id === alert.id ? { ...a, status: saved.status, responding: false } : a
          )
        );
      } catch (err) {
        setAlerts((prev) =>
          prev.map((a) =>
            a.id === alert.id
              ? { ...a, responding: false, error: err.message }
              : a
          )
        );
      }
    },
    []
  );

  if (view === "select") {
    return (
      <div className="app">
        <header className="app-header">
          <h1>Hospital Dashboard</h1>
        </header>
        <HospitalSelect
          hospitals={hospitals}
          hospitalId={hospitalId}
          onSelect={setHospitalId}
          onOpen={openDashboard}
          error={hospitalsError}
          loading={hospitalsLoading}
        />
        <Footer />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Hospital Dashboard</h1>
        <p className="hospital-name">{hospitalName}</p>
        <button className="link-button" onClick={() => setView("select")}>
          Switch hospital
        </button>
      </header>

      <p className={`ws-badge ${wsStatus}`}>
        {wsStatus === "open"
          ? "Live — receiving alerts"
          : wsStatus === "connecting"
          ? "Connecting…"
          : "Disconnected — retrying"}
      </p>

      <StatusForm
        status={status}
        form={form}
        onChange={(key, value) => setForm((prev) => ({ ...prev, [key]: value }))}
        onUpdate={handleUpdateStatus}
        updating={updating}
        message={statusMessage}
      />

      <h2 className="section-title">Incoming alerts ({alerts.length})</h2>
      {alerts.length === 0 && (
        <p className="muted">
          Waiting for alerts on this hospital's channel…
        </p>
      )}
      {alerts.map((alert) => (
        <AlertCard key={alert.id} alert={alert} onRespond={handleRespond} />
      ))}

      <Footer />
    </div>
  );
}

function Footer() {
  return (
    <footer className="footer">
      Demo tool for evaluation only — not production hospital software.
    </footer>
  );
}
