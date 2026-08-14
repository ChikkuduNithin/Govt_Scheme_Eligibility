import { useState } from "react";
import { api } from "./api";

const EMERGENCY_TYPES = [
  "TRAUMA",
  "STROKE",
  "CARDIAC",
  "RESPIRATORY",
  "BURN",
  "PEDIATRIC",
  "OBSTETRIC",
  "GENERAL_CRITICAL",
];

const SEVERITIES = ["LOW", "MEDIUM", "HIGH"];

const STEP_LABELS = {
  1: "Emergency type",
  2: "Patient vitals",
  3: "Recommendation",
};

export default function App() {
  const [step, setStep] = useState(1);
  const [emergencyType, setEmergencyType] = useState("TRAUMA");
  const [severity, setSeverity] = useState("HIGH");
  const [form, setForm] = useState({
    age: "",
    conscious: true,
    spo2: "",
    heart_rate: "",
    bp: "",
    ambulance_id: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [caseId, setCaseId] = useState(null);
  const [recommendation, setRecommendation] = useState(null);
  const [hospitals, setHospitals] = useState({});
  const [accepted, setAccepted] = useState(null);

  const setField = (key, value) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  function reset() {
    setStep(1);
    setError(null);
    setCaseId(null);
    setRecommendation(null);
    setHospitals({});
    setAccepted(null);
  }

  async function submitCase(event) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const created = await api("/emergencies", {
        method: "POST",
        body: JSON.stringify({
          emergency_type: emergencyType,
          severity,
          patient: {
            age: Number(form.age),
            conscious: form.conscious,
            spo2: Number(form.spo2),
            heart_rate: Number(form.heart_rate),
            bp: form.bp.trim(),
          },
          ambulance_id: form.ambulance_id.trim(),
        }),
      });

      const rec = await api(`/emergencies/${created.case_id}/recommend`, {
        method: "POST",
      });

      let nameMap = {};
      try {
        const allHospitals = await api("/hospitals");
        nameMap = Object.fromEntries(allHospitals.map((h) => [h._id, h.name]));
      } catch {
        // hospital names are a nice-to-have; fall back to ids below
      }

      setCaseId(created.case_id);
      setRecommendation(rec);
      setHospitals(nameMap);
      setStep(3);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function accept() {
    if (!caseId || !recommendation?.recommended_hospital_id) return;
    setError(null);
    setLoading(true);
    try {
      const hospitalId = recommendation.recommended_hospital_id;
      const result = await api(`/recommendations/${caseId}/accept`, {
        method: "POST",
        body: JSON.stringify({ hospital_id: hospitalId }),
      });
      setAccepted(result);
      try {
        await api("/hospital-alerts", {
          method: "POST",
          body: JSON.stringify({ case_id: caseId, hospital_id: hospitalId }),
        });
      } catch {
        // alert broadcast failure should not block the accept confirmation
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const progress = `Step ${step} of 3 — ${STEP_LABELS[step]}`;

  return (
    <div className="app">
      <header className="app-header">
        <h1>Ambulance App</h1>
        <p className="progress">{progress}</p>
      </header>

      <main className="card">
        {error && <p className="error">{error}</p>}

        {step === 1 && (
          <EmergencyTypeScreen
            emergencyType={emergencyType}
            setEmergencyType={setEmergencyType}
            severity={severity}
            setSeverity={setSeverity}
            onNext={() => {
              setError(null);
              setStep(2);
            }}
          />
        )}

        {step === 2 && (
          <PatientVitalsScreen
            form={form}
            setField={setField}
            loading={loading}
            onSubmit={submitCase}
            onBack={() => {
              setError(null);
              setStep(1);
            }}
          />
        )}

        {step === 3 && (
          <RecommendationScreen
            caseId={caseId}
            recommendation={recommendation}
            hospitals={hospitals}
            accepted={accepted}
            loading={loading}
            onAccept={accept}
            onReset={reset}
          />
        )}
      </main>
    </div>
  );
}

function EmergencyTypeScreen({
  emergencyType,
  setEmergencyType,
  severity,
  setSeverity,
  onNext,
}) {
  return (
    <section>
      <h2>Select emergency type</h2>

      <div className="radio-group">
        {EMERGENCY_TYPES.map((type) => (
          <label
            key={type}
            className={`radio-card${emergencyType === type ? " selected" : ""}`}
          >
            <input
              type="radio"
              name="emergency_type"
              value={type}
              checked={emergencyType === type}
              onChange={() => setEmergencyType(type)}
            />
            {type.replace("_", " ")}
          </label>
        ))}
      </div>

      <label className="field">
        <span>Severity</span>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {SEVERITIES.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </label>

      <button className="btn primary" onClick={onNext}>
        Next
      </button>
    </section>
  );
}

function PatientVitalsScreen({ form, setField, loading, onSubmit, onBack }) {
  return (
    <section>
      <h2>Patient vitals</h2>

      <form onSubmit={onSubmit}>
        <label className="field">
          <span>Age</span>
          <input
            type="number"
            min="0"
            max="120"
            required
            value={form.age}
            onChange={(e) => setField("age", e.target.value)}
          />
        </label>

        <div className="field">
          <span>Conscious</span>
          <div className="radio-inline">
            <label>
              <input
                type="radio"
                name="conscious"
                checked={form.conscious === true}
                onChange={() => setField("conscious", true)}
              />
              Yes
            </label>
            <label>
              <input
                type="radio"
                name="conscious"
                checked={form.conscious === false}
                onChange={() => setField("conscious", false)}
              />
              No
            </label>
          </div>
        </div>

        <label className="field">
          <span>SpO₂ (%)</span>
          <input
            type="number"
            min="0"
            max="100"
            required
            value={form.spo2}
            onChange={(e) => setField("spo2", e.target.value)}
          />
        </label>

        <label className="field">
          <span>Heart rate (bpm)</span>
          <input
            type="number"
            min="0"
            max="300"
            required
            value={form.heart_rate}
            onChange={(e) => setField("heart_rate", e.target.value)}
          />
        </label>

        <label className="field">
          <span>Blood pressure</span>
          <input
            type="text"
            placeholder="e.g. 120/80"
            required
            value={form.bp}
            onChange={(e) => setField("bp", e.target.value)}
          />
        </label>

        <label className="field">
          <span>Ambulance ID</span>
          <input
            type="text"
            required
            value={form.ambulance_id}
            onChange={(e) => setField("ambulance_id", e.target.value)}
          />
        </label>

        {loading && <p className="loading">Creating case and computing recommendation…</p>}

        <div className="button-row">
          <button type="button" className="btn" onClick={onBack} disabled={loading}>
            Back
          </button>
          <button type="submit" className="btn primary" disabled={loading}>
            {loading ? "Working…" : "Get recommendation"}
          </button>
        </div>
      </form>
    </section>
  );
}

function RecommendationScreen({
  caseId,
  recommendation,
  hospitals,
  accepted,
  loading,
  onAccept,
  onReset,
}) {
  const rec = recommendation;
  const recommendedId = rec?.recommended_hospital_id;
  const hospitalName = (id) => (hospitals[id] ? hospitals[id] : id);
  const recommendedName = recommendedId ? hospitalName(recommendedId) : null;
  const noEligible = Boolean(rec?.no_eligible_hospital);
  const alternatives = rec?.alternatives ?? [];

  return (
    <section>
      <h2>Recommended destination</h2>
      <p className="muted">Case: {caseId}</p>

      {noEligible || !recommendedId ? (
        <p className="error">
          No eligible hospital found for this case. See eliminated hospitals
          below.
        </p>
      ) : (
        <div className="summary">
          <p className="hospital-name">{recommendedName}</p>
          <p className="eta">
            ETA ≈ {rec.eta_minutes != null ? `${Math.round(rec.eta_minutes)} min` : "unknown"}
          </p>
          {rec.total_care_delay_minutes != null && (
            <p className="muted">
              Total care delay ≈ {rec.total_care_delay_minutes} min
            </p>
          )}
        </div>
      )}

      {rec?.reasons?.length > 0 && (
        <ul className="reasons">
          {rec.reasons.map((reason, index) => (
            <li key={index}>
              <span className="check">✓</span> {reason}
            </li>
          ))}
        </ul>
      )}

      {alternatives.length > 0 && (
        <details className="alternatives">
          <summary>Alternatives considered ({alternatives.length})</summary>
          <ul>
            {alternatives.map((alt, index) => (
              <li key={index}>
                <strong>{hospitalName(alt.hospital_id)}</strong>
                {alt.eliminated_reason ? (
                  <p className="muted">Excluded — {alt.eliminated_reason}</p>
                ) : (
                  <p className="muted">
                    Eligible alternative — total care delay{" "}
                    {alt.total_care_delay_minutes} min
                  </p>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {accepted && (
        <p className="success">
          Accepted at {hospitalName(accepted.accepted_hospital_id)}. Hospital
          alert sent.
        </p>
      )}

      {loading && <p className="loading">Sending acceptance…</p>}

      <div className="button-row">
        <button className="btn" onClick={onReset} disabled={loading}>
          Start over
        </button>
        {!accepted && (
          <button
            className="btn primary"
            onClick={onAccept}
            disabled={loading || noEligible || !recommendedId}
          >
            Accept
          </button>
        )}
      </div>
    </section>
  );
}
