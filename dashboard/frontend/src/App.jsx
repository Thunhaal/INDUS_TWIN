import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cpu,
  Factory,
  Gauge,
  Grid3X3,
  HardHat,
  LayoutDashboard,
  Menu,
  RefreshCw,
  Shield,
  SlidersHorizontal,
  Sun,
  Moon,
  Thermometer,
  TimerReset,
  Waves,
  X,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./index.css";

const API = "https://electro-accommodations-brave-algebra.trycloudflare.com";

const NAV = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "energy", label: "Energy & Grid", icon: Zap },
  { id: "analytics", label: "Production & AI", icon: Activity },
  { id: "maintenance", label: "Maintenance", icon: HardHat },
  { id: "scenarios", label: "What-If Simulator", icon: SlidersHorizontal },
];

const MACHINE_POSITIONS = {
  CNC_01: { x: 15, y: 25 },
  CNC_02: { x: 32, y: 25 },
  CNC_03: { x: 49, y: 25 },
  FURNACE_01: { x: 33, y: 70 },
  COMP_01: { x: 55, y: 67 },
  PUMP_01: { x: 71, y: 67 },
  HVAC_01: { x: 83, y: 25 },
};

const SCENARIOS = [
  {
    id: "NORMAL",
    name: "Normal Operation",
    icon: Factory,
    text: "Baseline production with normal grid availability.",
  },
  {
    id: "GRID_STRESS",
    name: "Grid Stress",
    icon: Zap,
    text: "Trigger demand-response logic and deploy safe flexibility.",
  },
  {
    id: "PEAK_DEMAND",
    name: "Peak Demand",
    icon: Gauge,
    text: "Test the factory during a short high-demand window.",
  },
  {
    id: "LOW_RENEWABLE",
    name: "Low Renewable",
    icon: Waves,
    text: "Reduce renewable availability and observe grid response.",
  },
  {
    id: "CRITICAL_GRID",
    name: "Critical Grid",
    icon: Shield,
    text: "Stress the reserve layer with a tighter operating envelope.",
  },
  {
    id: "EQUIPMENT_ANOMALY",
    name: "Equipment Anomaly",
    icon: Thermometer,
    text: "Inject an equipment condition for AI detection and maintenance.",
  },
];

function number(value, digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function integer(value) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

function clean(value) {
  return String(value ?? "UNKNOWN").replaceAll("_", " ").toUpperCase();
}

function timeLabel(timestamp) {
  const t = Number(timestamp);
  if (!Number.isFinite(t)) return "—";
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stateClass(value) {
  const s = clean(value);
  if (s.includes("FAULT") || s.includes("CRITICAL")) return "critical";
  if (s.includes("MAINTENANCE") || s.includes("MEDIUM") || s.includes("WARNING")) return "warning";
  if (s.includes("REDUCED")) return "reduced";
  return "normal";
}

function healthClass(machine) {
  const anomaly = clean(machine?.anomaly_type);
  const maintenance = clean(machine?.maintenance_label);
  if (anomaly.includes("SEVERE") || maintenance === "CRITICAL" || maintenance === "HIGH") return "critical";
  if (anomaly !== "NORMAL" || maintenance === "MEDIUM") return "warning";
  return "normal";
}

function Status({ value, compact = false }) {
  const status = clean(value);
  let type = "neutral";
  if (status.includes("NORMAL") || status.includes("LIVE") || status.includes("ONLINE") || status.includes("RUNNING") || status.includes("COMPLETED")) type = "green";
  if (status.includes("REDUCED") || status.includes("STRESS") || status.includes("WARNING") || status.includes("ONGOING") || status.includes("MEDIUM")) type = "amber";
  if (status.includes("CRITICAL") || status.includes("FAULT") || status.includes("HIGH") || status.includes("INSUFFICIENT")) type = "red";
  return (
    <span className={`status ${type} ${compact ? "compact" : ""}`}>
      <span />
      {status}
    </span>
  );
}

function Metric({ label, value, unit, detail, icon: Icon, tone = "neutral", trend }) {
  return (
    <div className={`metric ${tone}`}>
      <div className="metric-top">
        <span>{label}</span>
        <Icon size={16} strokeWidth={1.8} />
      </div>
      <div className="metric-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      <div className="metric-bottom">
        <span>{detail}</span>
        {trend != null && (
          <b className={Number(trend) >= 0 ? "up" : "down"}>
            {Number(trend) >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {Math.abs(Number(trend)).toFixed(1)}%
          </b>
        )}
      </div>
    </div>
  );
}

function SectionTitle({ eyebrow, title, text, right }) {
  return (
    <div className="section-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {right}
    </div>
  );
}

function RangeToggle({ value, onChange }) {
  return (
    <div className="range-toggle">
      {[12, 24].map((hours) => (
        <button key={hours} className={value === hours ? "active" : ""} onClick={() => onChange(hours)}>
          {hours}H
        </button>
      ))}
    </div>
  );
}

function MachineNode({ machine, onSelect, selected, activeControl }) {
  const position = MACHINE_POSITIONS[machine.machine_id] || { x: 50, y: 50 };
  const health = healthClass(machine);
  const reduced = machine.state === "REDUCED" || activeControl;
  return (
    <button
      className={`machine-node ${health} ${reduced ? "controlled" : ""} ${selected ? "selected" : ""}`}
      style={{ left: `${position.x}%`, top: `${position.y}%` }}
      onClick={() => onSelect(machine)}
      title={`${machine.machine_id} · ${number(machine.power_kw, 1)} kW`}
    >
      <div className="machine-pulse" />
      <div className="machine-symbol"><Factory size={20} strokeWidth={1.5} /></div>
      <strong>{machine.machine_id}</strong>
      <span>{number(machine.power_kw, 1)} kW</span>
      <i />
      {reduced && <em>AI CONTROL</em>}
    </button>
  );
}

function ChartFrame({ children, className = "", style }) {
  return <div className={`chart-frame ${className}`} style={style}>{children}</div>;
}

function EmptyState({ text = "No data available" }) {
  return (
    <div className="empty-state">
      <CircleDot size={18} />
      <span>{text}</span>
    </div>
  );
}

function MachinePanel({ machine, detail, close }) {
  if (!machine) return null;
  const energyHistory = detail?.energy_history || [];
  const productionHistory = detail?.production_history || [];
  const efficiency = detail?.efficiency || {};
  const history = energyHistory.map((row) => ({
    time: timeLabel(row.timestamp),
    power: Number(row.power_kw || 0),
  }));
  // production_data.csv currently exposes actual_units rather than a
  // production_rate field in the machine history payload. The logger
  // records this as the current production-rate snapshot for the machine.
  const productionChart = productionHistory.map((row) => ({
    time: timeLabel(row.timestamp),
    rate: Number(row.production_rate ?? row.actual_units ?? 0),
  }));
  return (
    <>
      <div className="drawer-backdrop" onClick={close} />
      <aside className="machine-panel">
        <div className="drawer-head">
          <div>
            <div className="eyebrow">MACHINE DIGITAL TWIN</div>
            <h2>{machine.machine_id}</h2>
            <p>{machine.machine_name}</p>
          </div>
          <button className="icon-btn" onClick={close}><X size={18} /></button>
        </div>

        <div className={`health-banner ${healthClass(machine)}`}>
          <Shield size={20} />
          <div>
            <span>AI HEALTH</span>
            <strong>{clean(machine.maintenance_label || "NORMAL")}</strong>
          </div>
          <Status value={machine.state} compact />
        </div>

        <section className="drawer-section">
          <div className="drawer-title"><span>LIVE TELEMETRY</span><RadioDot /></div>
          <div className="telemetry-grid">
            <Telemetry label="POWER" value={`${number(machine.power_kw, 2)} kW`} />
            <Telemetry label="LOAD" value={`${number(machine.load_percent, 1)} %`} />
            <Telemetry label="TEMPERATURE" value={`${number(machine.temperature_c, 1)} °C`} />
            <Telemetry label="VIBRATION" value={`${number(machine.vibration_mm_s, 3)} mm/s`} />
            <Telemetry label="RPM" value={number(machine.rpm, 0)} />
            <Telemetry label="PRODUCTION RATE" value={`${number(machine.production_rate, 1)} u/min`} />
          </div>
        </section>

        <section className="drawer-section">
          <div className="drawer-title"><span>AI DECISION</span><Bot size={14} /></div>
          <div className="signal-list">
            <Signal label="ANOMALY" value={clean(machine.anomaly_type || "NORMAL")} />
            <Signal label="MAINTENANCE RISK" value={`${number(Number(machine.maintenance_risk || 0) * 100, 1)} %`} />
            <Signal label="REASON" value={clean(machine.maintenance_reason || "NORMAL")} />
          </div>
        </section>

        <section className="drawer-section">
          <div className="drawer-title"><span>ENERGY FLEXIBILITY</span><Zap size={14} /></div>
          <div className="flex-kpi-grid">
            <Telemetry label="PHYSICAL" value={`${number(machine.physical_flexibility_kw, 2)} kW`} />
            <Telemetry label="SAFE" value={`${number(machine.safe_flexibility_kw, 2)} kW`} />
            <Telemetry label="DEPLOYABLE" value={`${number(machine.deployable_flexibility_kw, 2)} kW`} />
            <Telemetry label="RESERVE" value={`${number(machine.flexible_energy_reserve_kwh, 2)} kWh`} />
          </div>
        </section>

        <section className="drawer-section">
          <div className="drawer-title"><span>POWER HISTORY · 12H</span><Activity size={14} /></div>
          <ChartFrame className="drawer-chart">
            {history.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" />
                  <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} width={38} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${number(v, 2)} kW`, "Power"]} />
                  <Line type="monotone" dataKey="power" stroke="var(--cyan)" strokeWidth={2.2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <EmptyState text="Waiting for machine history" />}
          </ChartFrame>
        </section>

        <section className="drawer-section">
          <div className="drawer-title"><span>PRODUCTION HISTORY</span><Gauge size={14} /></div>
          <ChartFrame className="drawer-chart small">
            {productionChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={productionChart}>
                  <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" />
                  <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} width={38} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${number(v, 2)} u/min`, "Rate"]} />
                  <Area type="monotone" dataKey="rate" stroke="var(--green)" fill="var(--green-fill)" strokeWidth={1.8} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <EmptyState text="Waiting for production history" />}
          </ChartFrame>
          <div className="mini-note">
            Energy / produced unit: <strong>{number(efficiency.energy_per_produced_unit_kwh, 2)} kWh/u</strong>
          </div>
        </section>
      </aside>
    </>
  );
}

function Telemetry({ label, value }) {
  return <div className="telemetry-cell"><span>{label}</span><strong>{value}</strong></div>;
}

function Signal({ label, value }) {
  return <div className="signal-row"><span>{label}</span><strong>{value}</strong></div>;
}

function RadioDot() {
  return <span className="radio-dot"><i /></span>;
}

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--line-strong)",
  borderRadius: 8,
  boxShadow: "var(--tooltip-shadow)",
  color: "var(--text)",
  fontSize: 11,
};

function Overview({ data, energy, energyRange, setEnergyRange, selectedMachine, setSelectedMachine, controlStatus }) {
  const factory = data?.factory || {};
  const machines = data?.machines?.machines || [];
  const events = data?.maintenance?.events || [];
  const ai = controlStatus?.latest_ai_decision || {};
  const activeControls = controlStatus?.active_controls || [];
  const history = energy?.history || [];
  const activeAlerts = machines.filter((machine) => healthClass(machine) !== "normal");
  const counts = useMemo(() => {
    return machines.reduce((acc, machine) => {
      const s = clean(machine.state);
      if (s.includes("FAULT")) acc.fault += 1;
      else if (s.includes("MAINTENANCE")) acc.maintenance += 1;
      else if (s.includes("IDLE")) acc.idle += 1;
      else acc.running += 1;
      return acc;
    }, { running: 0, idle: 0, maintenance: 0, fault: 0 });
  }, [machines]);
  const chartData = history.map((row) => ({
    time: row.time_label || timeLabel(row.timestamp),
    demand: Number(row.factory_power_kw || 0),
    active: Number(row.active_machines || 0),
  }));
  const machinePower = energy?.latest_machine_power || [];
  const maxPower = Math.max(...machinePower.map((row) => Number(row.power_kw || 0)), 1);
  const selectedIds = new Set(activeControls.map((x) => x.machine_id));

  return (
    <div className="content">
      <SectionTitle
        eyebrow="PLANT 01 · DIGITAL TWIN"
        title="Command Center"
        text="Production, energy, machine health and AI control in one operating view."
        right={<Status value={factory.grid_status || "NORMAL"} />}
      />

      <div className="state-strip">
        <StateCount label="RUNNING" value={counts.running} tone="green" />
        <StateCount label="IDLE" value={counts.idle} tone="neutral" />
        <StateCount label="MAINTENANCE" value={counts.maintenance} tone="amber" />
        <StateCount label="FAULT" value={counts.fault} tone="red" />
        <div className="state-strip-spacer" />
        <div className="live-tag"><RadioDot /> LIVE TELEMETRY</div>
      </div>

      <div className="metrics">
        <Metric label="FACTORY LOAD" value={number(factory.factory_power_kw, 1)} unit="kW" detail={`${counts.running}/${machines.length} production assets online`} icon={Zap} tone="cyan" />
        <Metric label="VIRTUAL RESERVE" value={number(factory.deployable_flexibility_kw, 2)} unit="kW" detail={clean(factory.reserve_status || "NO GRID RESPONSE") } icon={Shield} tone="green" />
        <Metric label="GRID HEADROOM" value={number(Number(factory.available_grid_power_kw || 0) - Number(factory.factory_power_kw || 0), 1)} unit="kW" detail={`Available ${number(factory.available_grid_power_kw, 0)} kW`} icon={Grid3X3} tone={Number(factory.reserve_margin_kw) < 0 ? "red" : "neutral"} />
        <Metric label="AI CONTROLS" value={activeControls.length} detail={activeControls.length ? "Safe flexibility currently deployed" : "No active load controls"} icon={Bot} tone={activeControls.length ? "amber" : "neutral"} />
      </div>

      <div className="overview-layout">
        <section className="panel floor-panel">
          <div className="panel-head">
            <div>
              <div className="eyebrow">LIVE FACTORY FLOOR</div>
              <h2>Interactive Plant Layout</h2>
            </div>
            <div className="panel-head-actions"><Status value="LIVE" compact /><span className="small-help">Click any machine</span></div>
          </div>
          <div className="factory-floor">
            <div className="floor-grid" />
            <div className="floor-frame" />
            <div className="zone zone-a">PRODUCTION LINE 01</div>
            <div className="zone zone-b">UTILITY</div>
            <div className="zone zone-c">HEAT PROCESS</div>
            <div className="conveyor conveyor-a" />
            <div className="conveyor conveyor-b" />
            <div className="utility-trace" />
            <div className="plant-core">
              <div className="core-ring"><Grid3X3 size={25} /></div>
              <strong>PLANT CORE</strong>
              <span>ROS 2 · AI ENGINE · FASTAPI</span>
            </div>
            {machines.map((machine) => (
              <MachineNode
                key={machine.machine_id}
                machine={machine}
                onSelect={setSelectedMachine}
                selected={selectedMachine?.machine_id === machine.machine_id}
                activeControl={selectedIds.has(machine.machine_id)}
              />
            ))}
            <div className="floor-legend">
              <span><i className="legend-dot green" />RUNNING</span>
              <span><i className="legend-dot amber" />AI CONTROL</span>
              <span><i className="legend-dot red" />FAULT</span>
            </div>
          </div>
          <div className="floor-footer">
            <div><span>TOTAL POWER</span><strong>{number(factory.factory_power_kw, 1)} kW</strong></div>
            <div><span>SYSTEM ACTION</span><strong>{factory.system_action || "NO GRID RESPONSE REQUIRED"}</strong></div>
            <div><span>LAST SYNC</span><strong>{timeLabel(factory.timestamp)}</strong></div>
          </div>
        </section>

        <div className="overview-side">
          <section className="panel ai-panel">
            <div className="panel-head">
              <div><div className="eyebrow">AI CONTROL LOOP</div><h2>Decision Engine</h2></div>
              <div className="ai-badge"><Bot size={17} /></div>
            </div>
            <div className="ai-callout">
              <span>CURRENT SYSTEM DECISION</span>
              <strong>{factory.system_action || ai.system_action || "NO GRID RESPONSE REQUIRED"}</strong>
            </div>
            <div className="ai-grid">
              <Signal label="GRID STRESS" value={`${number(Number(factory.grid_stress_level || 0) * 100, 0)} %`} />
              <Signal label="REQUIRED" value={`${number(factory.required_reduction_kw, 2)} kW`} />
              <Signal label="DEPLOYABLE" value={`${number(factory.deployable_flexibility_kw, 2)} kW`} />
              <Signal label="MARGIN" value={`${number(factory.reserve_margin_kw, 2)} kW`} />
            </div>
            <div className="controlled-list">
              {activeControls.length ? activeControls.map((control) => (
                <div className="control-row" key={control.machine_id}>
                  <div><strong>{control.machine_id}</strong><span>{control.state} · {number(control.power_kw, 1)} kW</span></div>
                  <Status value="AI CONTROL" compact />
                </div>
              )) : <EmptyState text="No active AI controls" />}
            </div>
          </section>

          <section className="panel alert-panel">
            <div className="panel-head compact">
              <div><div className="eyebrow">LIVE CONDITIONS</div><h2>Health Signals</h2></div>
              <span className="count-badge">{activeAlerts.length}</span>
            </div>
            {activeAlerts.length ? activeAlerts.slice(0, 5).map((machine) => (
              <button className="health-row" key={machine.machine_id} onClick={() => setSelectedMachine(machine)}>
                <span className={`signal-icon ${healthClass(machine)}`}><AlertTriangle size={14} /></span>
                <div><strong>{machine.machine_id}</strong><span>{clean(machine.maintenance_reason || machine.anomaly_type)}</span></div>
                <ChevronRight size={15} />
              </button>
            )) : <EmptyState text="No active health signals" />}
          </section>
        </div>
      </div>

      <div className="two-column-grid">
        <section className="panel chart-panel large">
          <div className="panel-head">
            <div><div className="eyebrow">ENERGY TELEMETRY</div><h2>Factory Demand History</h2></div>
            <RangeToggle value={energyRange} onChange={setEnergyRange} />
          </div>
          <ChartFrame className="main-chart">
            {chartData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="demandFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--cyan)" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="var(--cyan)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" />
                  <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={24} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} width={46} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${number(v, 2)} kW`, "Demand"]} />
                  <Area type="monotone" dataKey="demand" stroke="var(--cyan)" fill="url(#demandFill)" strokeWidth={2.4} name="Demand" />
                </AreaChart>
              </ResponsiveContainer>
            ) : <EmptyState text="Waiting for energy telemetry" />}
          </ChartFrame>
        </section>

        <section className="panel chart-panel">
          <div className="panel-head"><div><div className="eyebrow">MACHINE ENERGY</div><h2>Latest Power by Asset</h2></div></div>
          <div className="machine-bar-list">
            {machinePower.map((row) => (
              <div className="machine-bar-row" key={row.machine_id}>
                <div className="machine-bar-name"><strong>{row.machine_id}</strong><span>{number(row.power_kw, 2)} kW</span></div>
                <div className="bar-track"><i style={{ width: `${Math.min(100, Number(row.power_kw || 0) / maxPower * 100)}%` }} /></div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="bottom-summary-grid">
        <section className="panel compact-data-panel">
          <div className="panel-head compact"><div><div className="eyebrow">PRODUCTION</div><h2>Current Throughput</h2></div><Gauge size={17} /></div>
          <div className="data-kpis">
            <DataKpi label="TARGET" value={integer(data?.production?.summary?.target_units)} />
            <DataKpi label="PRODUCED" value={integer(data?.production?.summary?.actual_units)} />
            <DataKpi label="QUALITY" value={data?.production?.summary?.quality_percent != null ? `${number(data.production.summary.quality_percent, 1)}%` : "—"} />
          </div>
        </section>
        <section className="panel compact-data-panel">
          <div className="panel-head compact"><div><div className="eyebrow">MAINTENANCE</div><h2>Recent Work Orders</h2></div><HardHat size={17} /></div>
          {events.length ? (
            <div className="mini-events">{events.slice(-3).reverse().map((event) => <div key={event.event_id}><strong>{event.machine_id}</strong><span>{clean(event.event_type)} · {clean(event.status)}</span></div>)}</div>
          ) : <EmptyState text="No maintenance events" />}
        </section>
      </div>
    </div>
  );
}

function StateCount({ label, value, tone }) {
  return <div className={`state-count ${tone}`}><strong>{value}</strong><span>{label}</span></div>;
}

function DataKpi({ label, value }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function EnergyPage({ data, energy, energyRange, setEnergyRange }) {
  const factory = data?.factory || {};
  const rows = data?.flexibility?.data || [];
  const history = energy?.history || [];
  const machinePower = energy?.latest_machine_power || [];
  const chartData = history.map((row) => ({ time: row.time_label || timeLabel(row.timestamp), demand: Number(row.factory_power_kw || 0), available: Number(factory.available_grid_power_kw || 0) }));
  const max = Math.max(...machinePower.map((x) => Number(x.power_kw || 0)), 1);
  return (
    <div className="content">
      <SectionTitle eyebrow="ENERGY INTELLIGENCE" title="Energy & Grid" text="Trace plant demand, grid stress and the virtual energy reserve created from safe flexibility." right={<RangeToggle value={energyRange} onChange={setEnergyRange} />} />

      <div className="energy-top-grid">
        <section className="reserve-card panel">
          <div className="eyebrow">VIRTUAL ENERGY RESERVE</div>
          <strong>{number(factory.deployable_flexibility_kw, 2)} <small>kW</small></strong>
          <span>{clean(factory.reserve_status || "NO GRID RESPONSE REQUIRED")}</span>
          <div className="reserve-scale"><i style={{ width: `${Math.min(100, Math.max(0, Number(factory.deployable_flexibility_kw || 0) / Math.max(Number(factory.required_reduction_kw || 0), 1) * 100))}%` }} /></div>
          <div className="reserve-figures"><span>Required <b>{number(factory.required_reduction_kw, 2)} kW</b></span><span>Margin <b className={Number(factory.reserve_margin_kw) < 0 ? "negative" : "positive"}>{number(factory.reserve_margin_kw, 2)} kW</b></span></div>
        </section>
        <div className="energy-kpi-grid">
          <Metric label="FACTORY DEMAND" value={number(factory.factory_power_kw, 1)} unit="kW" detail="Current plant demand" icon={Zap} tone="cyan" />
          <Metric label="GRID AVAILABLE" value={number(factory.available_grid_power_kw, 0)} unit="kW" detail={clean(factory.grid_status || "NORMAL")} icon={Grid3X3} tone="neutral" />
          <Metric label="SOLAR AVAILABLE" value={number(data?.scenario?.latest?.solar_available_power_kw || data?.grid?.latest?.solar_available_power_kw, 1)} unit="kW" detail="Scenario supply" icon={Waves} tone="green" />
          <Metric label="ACTIVE CONTROLS" value={data?.control?.active_control_count || 0} detail="AI-deployed flexibility" icon={Bot} tone="amber" />
        </div>
      </div>

      <section className="panel chart-panel extra-large">
        <div className="panel-head"><div><div className="eyebrow">GRID MONITORING</div><h2>Demand vs Available Capacity</h2></div><Status value={factory.grid_status || "NORMAL"} /></div>
        <ChartFrame className="energy-chart">
          {chartData.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 12, right: 18, left: 0, bottom: 0 }}>
                <defs><linearGradient id="gridFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--blue)" stopOpacity={0.11} /><stop offset="100%" stopColor="var(--blue)" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" />
                <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={24} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} width={48} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => [`${number(v, 2)} kW`, name === "available" ? "Grid capacity" : "Demand"]} />
                <Legend wrapperStyle={{ fontSize: 10, paddingTop: 8 }} />
                <Area type="monotone" dataKey="demand" stroke="var(--cyan)" fill="transparent" strokeWidth={2.2} name="Demand" />
                <Area type="monotone" dataKey="available" stroke="var(--blue)" fill="url(#gridFill)" strokeWidth={1.8} name="Grid capacity" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <EmptyState text="Waiting for grid telemetry" />}
        </ChartFrame>
      </section>

      <div className="energy-bottom-grid">
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">LOAD BREAKDOWN</div><h2>Machine-wise Consumption</h2></div></div>
          <div className="machine-bar-list spacious">
            {machinePower.map((row) => <div className="machine-bar-row" key={row.machine_id}><div className="machine-bar-name"><strong>{row.machine_id}</strong><span>{number(row.power_kw, 2)} kW</span></div><div className="bar-track"><i style={{ width: `${Math.min(100, Number(row.power_kw || 0) / max * 100)}%` }} /></div></div>)}
          </div>
        </section>
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">FLEXIBILITY MAP</div><h2>Deployable Loads</h2></div></div>
          <div className="flex-table">
            {rows.map((row) => {
              const safe = Number(row.deployable_flexibility_kw || 0);
              return <div className="flex-table-row" key={row.machine_id}><div><strong>{row.machine_id}</strong><span>{clean(row.deployment_status)}</span></div><div className="bar-track"><i style={{ width: `${Math.min(100, safe * 20)}%` }} /></div><b>{number(safe, 2)} kW</b></div>;
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function AnalyticsPage({ data, production, efficiency, energyRange, setEnergyRange, energy }) {
  const machines = data?.machines?.machines || [];
  const summary = production?.summary || data?.production?.summary || {};
  const effSummary = efficiency?.summary || {};
  const contributors = efficiency?.machines || [];
  const chartData = (energy?.history || []).map((row) => ({ time: row.time_label || timeLabel(row.timestamp), power: Number(row.factory_power_kw || 0) }));
  return (
    <div className="content">
      <SectionTitle eyebrow="PRODUCTION + AI" title="Plant Intelligence" text="Connect throughput, quality, energy intensity and machine health without extrapolating inspection samples." right={<RangeToggle value={energyRange} onChange={setEnergyRange} />} />

      <div className="metrics">
        <Metric label="TARGET OUTPUT" value={integer(summary.target_units)} unit="u" detail="Current production target" icon={Gauge} tone="neutral" />
        <Metric label="ACTUAL OUTPUT" value={integer(summary.actual_units)} unit="u" detail={`Completion ${number(summary.completion_percent, 1)}%`} icon={CheckCircle2} tone="green" />
        <Metric label="QUALITY" value={summary.quality_percent != null ? number(summary.quality_percent, 1) : "—"} unit={summary.quality_percent != null ? "%" : ""} detail={summary.inspected_units != null ? `${integer(summary.inspected_units)} inspected units` : "Inspection sample only"} icon={Shield} tone={Number(summary.quality_percent) < 95 ? "amber" : "green"} />
        <Metric label="ENERGY / UNIT" value={number(effSummary.energy_per_produced_unit_kwh, 2)} unit="kWh/u" detail={`${number(effSummary.average_factory_power_kw, 1)} kW average`} icon={Zap} tone="cyan" />
      </div>

      <div className="analytics-grid">
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">MACHINE HEALTH</div><h2>Maintenance Risk Map</h2></div></div>
          <div className="health-grid">
            {machines.map((machine) => {
              const risk = Math.min(100, Number(machine.maintenance_risk || 0) * 100);
              return <div className={`risk-card ${healthClass(machine)}`} key={machine.machine_id}><div><strong>{machine.machine_id}</strong><span>{number(risk, 0)}%</span></div><div className="risk-track"><i style={{ width: `${risk}%` }} /></div><small>{clean(machine.maintenance_label || machine.anomaly_type)}</small></div>;
            })}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">POWER OUTLOOK</div><h2>Factory Demand · Selected Range</h2></div></div>
          <ChartFrame className="analytics-chart">
            {chartData.length ? <ResponsiveContainer width="100%" height="100%"><LineChart data={chartData}><CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" /><XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={25} /><YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 9 }} width={45} /><Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${number(v, 2)} kW`, "Demand"]} /><Line type="monotone" dataKey="power" stroke="var(--blue)" strokeWidth={2.2} dot={false} /></LineChart></ResponsiveContainer> : <EmptyState text="Waiting for telemetry" />}
          </ChartFrame>
        </section>
      </div>

      <section className="panel production-panel">
        <div className="panel-head"><div><div className="eyebrow">PRODUCTION + ENERGY COUPLING</div><h2>Machine Efficiency Contributors</h2></div><span className="small-help">Quality is not extrapolated beyond inspected units</span></div>
        <div className="production-table head"><span>MACHINE</span><span>OUTPUT</span><span>ENERGY / UNIT</span><span>INSPECTION</span><span>QUALITY</span></div>
        {contributors.length ? contributors.map((row) => <div className="production-table" key={row.machine_id}><strong>{row.machine_id}</strong><span>{number(row.estimated_output_units, 2)} u</span><span>{number(row.energy_per_produced_unit_kwh, 2)} kWh/u</span><span>{row.inspected_units != null ? integer(row.inspected_units) : "—"}</span><span>{row.quality_percent != null ? `${number(row.quality_percent, 1)}%` : "—"}</span></div>) : <EmptyState text="Waiting for production-aligned data" />}
      </section>
    </div>
  );
}

function MaintenancePage({ data, refresh }) {
  const machines = data?.machines?.machines || [];
  const events = data?.maintenance?.events || [];
  const [busy, setBusy] = useState(null);
  async function updateEvent(eventId, status) {
    setBusy(eventId);
    try {
      const response = await fetch(`${API}/api/maintenance/events/${eventId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await refresh();
    } catch (error) {
      console.error(error);
      alert("Unable to update maintenance event.");
    } finally {
      setBusy(null);
    }
  }
  const flagged = machines.filter((m) => healthClass(m) !== "normal");
  return (
    <div className="content">
      <SectionTitle eyebrow="MAINTENANCE CONTROL" title="Maintenance & Health" text="AI-detected conditions become operator-managed work orders with visible production and energy context." right={<div className="event-count"><strong>{events.length}</strong><span>OPEN / RECENT EVENTS</span></div>} />

      <div className="maintenance-top">
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">AI HEALTH</div><h2>Machine Risk Overview</h2></div><Status value={`${flagged.length} SIGNALS`} /></div>
          <div className="health-list">
            {machines.map((machine) => {
              const risk = Math.min(100, Number(machine.maintenance_risk || 0) * 100);
              return <div className="health-list-row" key={machine.machine_id}><div><strong>{machine.machine_id}</strong><span>{clean(machine.maintenance_reason || "NORMAL")}</span></div><div className="risk-track"><i className={healthClass(machine)} style={{ width: `${risk}%` }} /></div><b>{number(risk, 0)}%</b></div>;
            })}
          </div>
        </section>
        <section className="panel maintenance-callout">
          <div className="eyebrow">AI → MAINTENANCE WORKFLOW</div>
          <h2>Detect · Prioritise · Work</h2>
          <p>Sensor deviations, maintenance risk and operating state are carried together into the event queue.</p>
          <div className="workflow"><WorkflowStep label="SUBMITTED" /><ChevronRight size={15} /><WorkflowStep label="ONGOING" /><ChevronRight size={15} /><WorkflowStep label="COMPLETED" /></div>
        </section>
      </div>

      <section className="panel maintenance-table-panel">
        <div className="table-head"><span>EVENT</span><span>MACHINE</span><span>CONDITION</span><span>SEVERITY</span><span>STATUS</span></div>
        {events.length ? events.slice().reverse().map((event) => <div className="table-row" key={event.event_id}><div><strong>{event.event_id}</strong><span>{timeLabel(event.timestamp)}</span></div><strong>{event.machine_id}</strong><div><strong>{clean(event.event_type)}</strong><span>{event.description || "AI maintenance condition"}</span></div><Status value={event.severity} compact /><select value={event.status || "SUBMITTED"} disabled={busy === event.event_id} onChange={(e) => updateEvent(event.event_id, e.target.value)}><option>SUBMITTED</option><option>ONGOING</option><option>COMPLETED</option></select></div>) : <EmptyState text="No maintenance events" />}
      </section>
    </div>
  );
}

function WorkflowStep({ label }) {
  return <div className="workflow-step"><span /><strong>{label}</strong></div>;
}

const WHAT_IF_SCENARIO_DEFAULTS = {
  NORMAL: { multiplier: 1.00, reduction: 0, renewable: 100 },
  GRID_STRESS: { multiplier: 1.02, reduction: 15, renewable: 100 },
  PEAK_DEMAND: { multiplier: 1.05, reduction: 10, renewable: 90 },
  LOW_RENEWABLE: { multiplier: 1.00, reduction: 5, renewable: 35 },
  CRITICAL_GRID: { multiplier: 1.06, reduction: 25, renewable: 50 },
  EQUIPMENT_ANOMALY: { multiplier: 1.00, reduction: 0, renewable: 100 },
};

const OUTAGE_STATES = new Set(["FAULT", "MAINTENANCE", "OFFLINE", "STOPPED"]);
const PRODUCTION_MACHINES = new Set(["CNC_01", "CNC_02", "CNC_03"]);

function clampNumber(value, min, max, fallback = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function formatDelta(value, digits = 1, unit = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}${unit}`;
}

function WhatIfControl({ label, children, hint }) {
  return (
    <div style={{ padding: "13px 14px", border: "1px solid var(--line)", background: "var(--surface-2)", minWidth: 0 }}>
      <div className="eyebrow" style={{ marginBottom: 7 }}>{label}</div>
      {children}
      {hint && <div style={{ marginTop: 6, color: "var(--muted)", fontSize: 8, lineHeight: 1.4 }}>{hint}</div>}
    </div>
  );
}

function WhatIfValue({ label, baseline, projected, unit = "", reverse = false }) {
  const delta = Number(projected) - Number(baseline);
  const better = reverse ? delta <= 0 : delta >= 0;
  return (
    <div style={{ padding: "15px 14px", borderRight: "1px solid var(--line)", minWidth: 0 }}>
      <span style={{ display: "block", color: "var(--muted)", fontSize: 7, letterSpacing: ".11em" }}>{label}</span>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "end", marginTop: 7 }}>
        <div>
          <strong style={{ display: "block", fontSize: 18 }}>{number(projected, 1)}<small style={{ marginLeft: 4, fontSize: 9, color: "var(--muted)" }}>{unit}</small></strong>
          <span style={{ display: "block", marginTop: 3, color: "var(--muted)", fontSize: 7 }}>baseline {number(baseline, 1)} {unit}</span>
        </div>
        <b style={{ fontSize: 9, color: better ? "var(--green)" : "var(--amber)" }}>{formatDelta(delta, 1, unit)}</b>
      </div>
    </div>
  );
}

function ScenariosPage({ data, controlStatus, onScenario, busyScenario, message }) {
  const current = data?.scenario?.latest || controlStatus?.latest_scenario || {};
  const factory = data?.factory || {};
  const machines = data?.machines?.machines || [];
  const controls = controlStatus?.active_controls || [];
  const productionSummary = data?.production?.summary || {};

  const [selectedScenario, setSelectedScenario] = useState("GRID_STRESS");
  const [durationMin, setDurationMin] = useState(60);
  const [requiredReduction, setRequiredReduction] = useState(15);
  const [renewableAvailability, setRenewableAvailability] = useState(100);
  const [objective, setObjective] = useState("BALANCED");
  const [outages, setOutages] = useState([]);
  const [anomalyMachine, setAnomalyMachine] = useState("CNC_03");
  const [anomalyType, setAnomalyType] = useState("HIGH_LOAD");
  const [anomalySeverity, setAnomalySeverity] = useState("HIGH");
  const [simulation, setSimulation] = useState(null);
  const [simulating, setSimulating] = useState(false);

  const activeId = current.scenario_id || "NORMAL";
  const selectedScenarioConfig = WHAT_IF_SCENARIO_DEFAULTS[selectedScenario] || WHAT_IF_SCENARIO_DEFAULTS.GRID_STRESS;

  const liveBasePower = machines.reduce((sum, machine) => sum + clampNumber(machine.power_kw, 0, 100000), 0) || clampNumber(factory.factory_power_kw, 0, 100000);
  const productionMachines = machines.filter((machine) => PRODUCTION_MACHINES.has(machine.machine_id));
  const liveProductionRate = productionMachines.reduce((sum, machine) => sum + clampNumber(machine.production_rate, 0, 100000), 0);
  const liveQuality = clampNumber(productionSummary.quality_percent, 0, 100, 93.5);
  const liveTarget = clampNumber(productionSummary.target_units, 0, 100000, liveProductionRate);
  const liveActual = clampNumber(productionSummary.actual_units, 0, 100000, liveProductionRate);

  useEffect(() => {
    const cfg = WHAT_IF_SCENARIO_DEFAULTS[selectedScenario] || WHAT_IF_SCENARIO_DEFAULTS.GRID_STRESS;
    setRequiredReduction(selectedScenario === "EQUIPMENT_ANOMALY" || selectedScenario === "NORMAL" ? 0 : cfg.reduction);
    setRenewableAvailability(cfg.renewable);
  }, [selectedScenario]);

  function toggleOutage(machineId) {
    setOutages((currentOutages) => currentOutages.includes(machineId)
      ? currentOutages.filter((id) => id !== machineId)
      : [...currentOutages, machineId].slice(0, 7)
    );
  }

  function setScenarioAndKeepLive(scenarioId) {
    setSelectedScenario(scenarioId);
    if (scenarioId === "EQUIPMENT_ANOMALY" && !machines.some((m) => m.machine_id === anomalyMachine)) {
      setAnomalyMachine(machines[0]?.machine_id || "CNC_03");
    }
    setSimulation(null);
  }

  function buildSimulation() {
    const cfg = WHAT_IF_SCENARIO_DEFAULTS[selectedScenario] || WHAT_IF_SCENARIO_DEFAULTS.GRID_STRESS;
    const outageSet = new Set(outages);
    const effectiveReductionRequired = selectedScenario === "NORMAL" || selectedScenario === "EQUIPMENT_ANOMALY"
      ? 0
      : clampNumber(requiredReduction, 0, 1000, cfg.reduction);

    const anomalyPenaltyMap = { LOW: 0.04, MEDIUM: 0.08, HIGH: 0.15, CRITICAL: 0.25 };
    const anomalyQualityPenalty = selectedScenario === "EQUIPMENT_ANOMALY" ? ({ LOW: 0.2, MEDIUM: 0.7, HIGH: 1.5, CRITICAL: 3.0 }[anomalySeverity] || 0) : 0;

    const machineRows = machines.map((machine) => {
      const id = machine.machine_id;
      const power = clampNumber(machine.power_kw, 0, 100000);
      const rate = clampNumber(machine.production_rate, 0, 100000);
      const state = clean(machine.state);
      const fixed = clean(machine.controllability).includes("FIXED");
      const criticality = clean(machine.criticality);
      const baseFlex = clampNumber(
        machine.deployable_flexibility_kw ?? machine.safe_flexibility_kw ?? (power - clampNumber(machine.min_kw, 0, power)),
        0,
        power,
      );
      const outage = outageSet.has(id);
      const existingDown = OUTAGE_STATES.has(state);
      const anomaly = selectedScenario === "EQUIPMENT_ANOMALY" && id === anomalyMachine;

      return {
        id,
        power,
        rate,
        state,
        criticality,
        baseFlex,
        outage: outage || existingDown,
        anomaly,
        fixed,
        projectedPower: outage || existingDown ? 0 : power * cfg.multiplier,
        projectedRate: outage || existingDown ? 0 : rate,
        selectedReduction: 0,
        status: outage || existingDown ? "OFFLINE" : "AVAILABLE",
      };
    });

    if (selectedScenario === "EQUIPMENT_ANOMALY") {
      const target = machineRows.find((row) => row.id === anomalyMachine);
      if (target && !target.outage) {
        const severityFactor = 1 - (anomalyPenaltyMap[anomalySeverity] || 0.08);
        target.projectedRate *= severityFactor;
        target.projectedPower *= 1 + ((anomalySeverity === "CRITICAL" ? 0.10 : anomalySeverity === "HIGH" ? 0.07 : 0.04));
        target.status = "DEGRADED";
      }
    }

    const availableForControl = machineRows
      .filter((row) => !row.outage && !row.fixed && row.baseFlex > 0)
      .filter((row) => !row.anomaly)
      .filter((row) => {
        if (objective === "MAX_PRODUCTION") return !row.criticality.includes("HIGH") && !row.criticality.includes("CRITICAL");
        if (objective === "BALANCED") return !row.criticality.includes("CRITICAL");
        return true;
      })
      .sort((a, b) => b.baseFlex - a.baseFlex);

    let remainingReduction = effectiveReductionRequired;
    for (const row of availableForControl) {
      if (remainingReduction <= 0) break;
      const take = Math.min(row.baseFlex, remainingReduction);
      row.selectedReduction = take;
      row.status = "CONTROLLED";
      row.projectedPower = Math.max(0, row.projectedPower - take);
      remainingReduction -= take;
    }

    const outagePower = machineRows.filter((row) => row.outage).reduce((sum, row) => sum + row.power, 0);
    const baselinePower = liveBasePower;
    const scenarioPowerBeforeControl = Math.max(0, baselinePower * cfg.multiplier - outagePower);
    const projectedPower = Math.max(0, machineRows.reduce((sum, row) => sum + row.projectedPower, 0));
    const safeFlexibility = machineRows.reduce((sum, row) => sum + ((!row.outage && !row.fixed && !row.anomaly) ? row.baseFlex : 0), 0);
    const selectedReduction = machineRows.reduce((sum, row) => sum + row.selectedReduction, 0);

    const productionMachinesProjected = machineRows.filter((row) => PRODUCTION_MACHINES.has(row.id));
    const normalRate = productionMachinesProjected.reduce((sum, row) => sum + row.rate, 0);
    let projectedRate = productionMachinesProjected.reduce((sum, row) => sum + row.projectedRate, 0);

    for (const row of productionMachinesProjected) {
      if (row.selectedReduction > 0 && row.power > 0) {
        const controlFraction = row.selectedReduction / row.power;
        const controlPenalty = objective === "MAX_ENERGY" ? 0.45 : objective === "BALANCED" ? 0.30 : 0.15;
        row.projectedRate *= Math.max(0.5, 1 - controlFraction * controlPenalty);
      }
    }
    projectedRate = productionMachinesProjected.reduce((sum, row) => sum + row.projectedRate, 0);

    const outageProductionLoss = machineRows.filter((row) => row.outage && PRODUCTION_MACHINES.has(row.id)).reduce((sum, row) => sum + row.rate, 0);
    const effectiveProduction = Math.max(0, projectedRate);
    const productionDelta = effectiveProduction - normalRate;
    const projectedQuality = clampNumber(liveQuality - anomalyQualityPenalty - Math.max(0, -productionDelta) * 0.008, 0, 100, liveQuality);
    const projectedTarget = Math.max(0, liveTarget);
    const projectedActual = Math.max(0, liveActual + productionDelta * (durationMin / 60));
    const baselineEnergy = baselinePower * (durationMin / 60);
    const projectedEnergy = projectedPower * (durationMin / 60);
    const solarPower = Math.max(0, projectedPower * clampNumber(renewableAvailability, 0, 100) / 100 * 0.35);
    const gridImport = Math.max(0, projectedPower - solarPower);
    const baselineGridImport = Math.max(0, baselinePower - (baselinePower * 0.35));
    const downtimeMin = outages.length * durationMin + (selectedScenario === "EQUIPMENT_ANOMALY" ? Math.round(durationMin * (anomalySeverity === "CRITICAL" ? 0.50 : anomalySeverity === "HIGH" ? 0.30 : 0.15)) : 0);

    const reserveGap = Math.max(0, effectiveReductionRequired - selectedReduction);
    const reserveStatus = effectiveReductionRequired <= 0
      ? "NO REDUCTION REQUIRED"
      : reserveGap <= 0
        ? "RESERVE SUFFICIENT"
        : "RESERVE INSUFFICIENT";

    const projectedGoodUnits = Math.max(0, projectedActual * projectedQuality / 100);
    const baselineGoodUnits = Math.max(0, liveActual * liveQuality / 100);

    const timeline = Array.from({ length: 13 }, (_, index) => {
      const minute = Math.round((durationMin / 12) * index);
      const progress = index === 0 ? 0 : Math.min(1, index / 2);
      return {
        minute,
        label: `${minute}m`,
        baselinePower,
        projectedPower: scenarioPowerBeforeControl - (scenarioPowerBeforeControl - projectedPower) * progress,
        baselineProduction: normalRate,
        projectedProduction: normalRate - (normalRate - effectiveProduction) * progress,
      };
    });

    const decision = reserveStatus === "RESERVE SUFFICIENT"
      ? "SAFE FLEXIBILITY CAN MEET THE REQUESTED GRID REDUCTION"
      : reserveStatus === "RESERVE INSUFFICIENT"
        ? "DEPLOY AVAILABLE FLEXIBILITY AND REPORT THE REMAINING GRID GAP"
        : selectedScenario === "EQUIPMENT_ANOMALY"
          ? "ISOLATE THE DEGRADED ASSET AND WATCH PRODUCTION / MAINTENANCE RISK"
          : "NO GRID RESPONSE REQUIRED";

    const explanation = [];
    if (outages.length) explanation.push(`${outages.length} machine outage${outages.length > 1 ? "s" : ""} removes ${outagePower.toFixed(1)} kW and ${outageProductionLoss.toFixed(1)} units/h of production capacity.`);
    if (selectedReduction > 0) explanation.push(`${selectedReduction.toFixed(2)} kW is selected from controllable, non-outage assets under the ${objective.replaceAll("_", " ").toLowerCase()} objective.`);
    if (selectedScenario === "EQUIPMENT_ANOMALY") explanation.push(`${clean(anomalyType)} on ${anomalyMachine} at ${anomalySeverity.toLowerCase()} severity reduces the simulated output and increases modeled power.`);
    if (renewableAvailability < 100) explanation.push(`Renewable availability is reduced to ${renewableAvailability}% so the simulator exposes the resulting grid-import dependency.`);
    if (reserveGap > 0) explanation.push(`${reserveGap.toFixed(2)} kW remains uncovered after safe deployment.`);

    return {
      scenarioId: selectedScenario,
      durationMin,
      requiredReduction: effectiveReductionRequired,
      baselinePower,
      scenarioPowerBeforeControl,
      projectedPower,
      safeFlexibility,
      selectedReduction,
      reserveGap,
      reserveStatus,
      baselineEnergy,
      projectedEnergy,
      energyDelta: projectedEnergy - baselineEnergy,
      renewableAvailability,
      solarPower,
      gridImport,
      baselineGridImport,
      normalRate,
      projectedRate: effectiveProduction,
      productionDelta,
      targetUnits: projectedTarget,
      actualUnits: projectedActual,
      baselineActualUnits: liveActual,
      quality: projectedQuality,
      baselineQuality: liveQuality,
      goodUnits: projectedGoodUnits,
      baselineGoodUnits,
      downtimeMin,
      outageCount: outages.length,
      outageProductionLoss,
      decision,
      explanation,
      machineRows,
      timeline,
    };
  }

  async function simulateScenario() {
    setSimulating(true);
    try {
      // The simulator is intentionally non-destructive. It calculates the
      // consequence model locally from the live machine snapshot and never
      // sends a ROS control command. Live scenario execution remains available
      // through the separate RUN LIVE / STOP LIVE controls below.
      const result = buildSimulation();
      setSimulation(result);
    } finally {
      setSimulating(false);
    }
  }

  const selectedLive = SCENARIOS.find((scenario) => scenario.id === selectedScenario) || SCENARIOS[0];
  const sim = simulation;
  const donutData = sim ? [
    { name: "GOOD", value: Math.max(0, sim.goodUnits) },
    { name: "REJECT / LOSS", value: Math.max(0, sim.actualUnits - sim.goodUnits) },
  ] : [];
  const donutColors = ["var(--green)", "var(--amber)"];

  return (
    <div className="content">
      <SectionTitle
        eyebrow="OPERATIONAL WHAT-IFS"
        title="What-If Simulator"
        text="Explore factory consequences before changing the live digital twin: energy, production, quality, outages, flexibility and grid exposure."
        right={<Status value={sim ? "SIMULATED" : activeId} />}
      />

      {message && <div className="action-message"><CheckCircle2 size={15} /> {message}</div>}

      <section className="panel" style={{ marginBottom: 11 }}>
        <div className="panel-head">
          <div><div className="eyebrow">WHAT HAPPENS IF...</div><h2>Simulation Controls</h2></div>
          <span className="small-help">Analysis only · live controls are separate</span>
        </div>

        <div style={{ padding: 15, display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
          <WhatIfControl label="SCENARIO">
            <select value={selectedScenario} onChange={(e) => setScenarioAndKeepLive(e.target.value)} style={{ width: "100%", height: 34, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 9px", fontSize: 9 }}>
              {SCENARIOS.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.name}</option>)}
            </select>
          </WhatIfControl>

          <WhatIfControl label="HORIZON">
            <select value={durationMin} onChange={(e) => setDurationMin(Number(e.target.value))} style={{ width: "100%", height: 34, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 9px", fontSize: 9 }}>
              {[15, 30, 60, 90, 120].map((value) => <option key={value} value={value}>{value} minutes</option>)}
            </select>
          </WhatIfControl>

          <WhatIfControl label="OBJECTIVE">
            <select value={objective} onChange={(e) => setObjective(e.target.value)} style={{ width: "100%", height: 34, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 9px", fontSize: 9 }}>
              <option value="MAX_ENERGY">Maximum Energy Saving</option>
              <option value="BALANCED">Balanced</option>
              <option value="MAX_PRODUCTION">Maximum Production</option>
            </select>
          </WhatIfControl>

          <WhatIfControl label="RENEWABLE AVAILABILITY" hint={`${renewableAvailability}% available supply contribution used by the grid-import model.`}>
            <input type="range" min="0" max="100" step="5" value={renewableAvailability} onChange={(e) => setRenewableAvailability(Number(e.target.value))} style={{ width: "100%" }} />
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5, fontSize: 9 }}><span>0%</span><strong>{renewableAvailability}%</strong><span>100%</span></div>
          </WhatIfControl>
        </div>

        <div style={{ padding: "0 15px 15px", display: "grid", gridTemplateColumns: "1.2fr .8fr", gap: 10 }}>
          <WhatIfControl label="GRID REDUCTION REQUEST" hint="Set the demand reduction the simulator must try to achieve without violating the chosen objective.">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 85px", gap: 10, alignItems: "center" }}>
              <input type="range" min="0" max="40" step="0.5" value={requiredReduction} disabled={selectedScenario === "NORMAL" || selectedScenario === "EQUIPMENT_ANOMALY"} onChange={(e) => setRequiredReduction(Number(e.target.value))} style={{ width: "100%" }} />
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}><input type="number" min="0" max="40" step="0.5" value={requiredReduction} disabled={selectedScenario === "NORMAL" || selectedScenario === "EQUIPMENT_ANOMALY"} onChange={(e) => setRequiredReduction(Number(e.target.value))} style={{ width: 65, height: 31, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 7px", fontSize: 9 }} /><span style={{ fontSize: 8 }}>kW</span></div>
            </div>
          </WhatIfControl>

          <WhatIfControl label="SIMULATED ACTION">
            <button type="button" onClick={simulateScenario} disabled={simulating} style={{ width: "100%", height: 36, border: 0, background: "var(--cyan)", color: "#fff", fontSize: 9, fontWeight: 800, letterSpacing: ".11em", cursor: simulating ? "wait" : "pointer" }}>{simulating ? "RUNNING SIMULATION…" : "SIMULATE CONSEQUENCES"}</button>
          </WhatIfControl>
        </div>

        {selectedScenario === "EQUIPMENT_ANOMALY" && (
          <div style={{ padding: "0 15px 15px", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
            <WhatIfControl label="ANOMALY MACHINE">
              <select value={anomalyMachine} onChange={(e) => setAnomalyMachine(e.target.value)} style={{ width: "100%", height: 34, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 9px", fontSize: 9 }}>
                {machines.map((machine) => <option key={machine.machine_id} value={machine.machine_id}>{machine.machine_id}</option>)}
              </select>
            </WhatIfControl>
            <WhatIfControl label="ANOMALY TYPE">
              <select value={anomalyType} onChange={(e) => setAnomalyType(e.target.value)} style={{ width: "100%", height: 34, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 9px", fontSize: 9 }}>
                <option>HIGH_LOAD</option><option>THERMAL_OVERLOAD</option><option>VIBRATION_SPIKE</option><option>POWER_SURGE</option>
              </select>
            </WhatIfControl>
            <WhatIfControl label="SEVERITY">
              <select value={anomalySeverity} onChange={(e) => setAnomalySeverity(e.target.value)} style={{ width: "100%", height: 34, border: "1px solid var(--line-strong)", background: "var(--surface)", color: "var(--text)", padding: "0 9px", fontSize: 9 }}>
                <option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option>
              </select>
            </WhatIfControl>
          </div>
        )}
      </section>

      <section className="panel" style={{ marginBottom: 11 }}>
        <div className="panel-head"><div><div className="eyebrow">FAILURE / OUTAGE LAB</div><h2>Take Machines Offline</h2></div><span className="small-help">Select one, two or multiple machines</span></div>
        <div style={{ padding: 15, display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 8 }}>
          {machines.map((machine) => {
            const selected = outages.includes(machine.machine_id);
            const isLiveDown = OUTAGE_STATES.has(clean(machine.state));
            return (
              <button key={machine.machine_id} type="button" onClick={() => toggleOutage(machine.machine_id)} style={{ minHeight: 78, border: `1px solid ${selected ? "var(--amber)" : "var(--line)"}`, background: selected ? "rgba(183,128,25,.08)" : "var(--surface)", cursor: "pointer", padding: 9, textAlign: "left" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 5 }}><strong style={{ fontSize: 8 }}>{machine.machine_id}</strong><span style={{ fontSize: 7, color: selected ? "var(--amber)" : "var(--muted)" }}>{selected ? "DOWN" : isLiveDown ? "LIVE DOWN" : "READY"}</span></div>
                <div style={{ marginTop: 12, fontSize: 14, fontWeight: 800 }}>{number(machine.power_kw, 1)} <small style={{ fontSize: 8, color: "var(--muted)" }}>kW</small></div>
                <div style={{ marginTop: 3, color: "var(--muted)", fontSize: 7 }}>{PRODUCTION_MACHINES.has(machine.machine_id) ? `${number(machine.production_rate, 1)} u/h` : "utility / process"}</div>
              </button>
            );
          })}
        </div>
        <div style={{ padding: "0 15px 15px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <span style={{ color: "var(--muted)", fontSize: 8 }}>{outages.length ? `${outages.length} machine${outages.length > 1 ? "s" : ""} selected for outage.` : "No additional outage selected. Existing live FAULT / MAINTENANCE states are reflected automatically."}</span>
          {!!outages.length && <button type="button" onClick={() => setOutages([])} style={{ border: "1px solid var(--line-strong)", background: "var(--surface)", height: 30, padding: "0 10px", fontSize: 8, cursor: "pointer" }}>CLEAR OUTAGES</button>}
        </div>
      </section>

      <section className="scenario-grid">
        {SCENARIOS.map((scenario) => {
          const Icon = scenario.icon;
          const active = activeId === scenario.id;
          const selected = selectedScenario === scenario.id;
          return (
            <div className={`scenario-card ${selected ? "active" : ""}`} key={scenario.id} onClick={() => setScenarioAndKeepLive(scenario.id)} style={{ cursor: "pointer" }}>
              <div className="scenario-card-top"><div className="scenario-icon"><Icon size={20} /></div>{active && <Status value="LIVE" compact />}</div>
              <div><strong>{scenario.name}</strong><p>{scenario.text}</p></div>
              <div className="scenario-action" style={{ gap: 8 }}>
                <button type="button" onClick={(e) => { e.stopPropagation(); onScenario(scenario.id, active ? "STOP" : "START"); }} disabled={busyScenario === scenario.id} style={{ border: 0, background: "transparent", color: active ? "var(--amber)" : "var(--text)", padding: 0, fontSize: 7, fontWeight: 800, letterSpacing: ".11em", cursor: "pointer" }}>{active ? "STOP LIVE" : "RUN LIVE"}</button>
                <button type="button" onClick={(e) => { e.stopPropagation(); setScenarioAndKeepLive(scenario.id); }} style={{ border: 0, background: "transparent", color: selected ? "var(--cyan)" : "var(--muted)", padding: 0, fontSize: 7, fontWeight: 800, letterSpacing: ".11em", cursor: "pointer" }}>SELECT FOR SIMULATION</button>
              </div>
            </div>
          );
        })}
      </section>

      <div style={{ marginTop: 11 }}>
        {sim ? (
          <>
            <section className="panel" style={{ marginBottom: 11 }}>
              <div className="panel-head">
                <div><div className="eyebrow">SIMULATION RESULT · {clean(sim.scenarioId)}</div><h2>Baseline → What-If Consequences</h2></div>
                <Status value={sim.reserveStatus} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", borderBottom: "1px solid var(--line)" }}>
                <WhatIfValue label="POWER" baseline={sim.baselinePower} projected={sim.projectedPower} unit="kW" reverse />
                <WhatIfValue label="ENERGY" baseline={sim.baselineEnergy} projected={sim.projectedEnergy} unit="kWh" reverse />
                <WhatIfValue label="PRODUCTION" baseline={sim.baselineActualUnits} projected={sim.actualUnits} unit="u" />
                <WhatIfValue label="GOOD UNITS" baseline={sim.baselineGoodUnits} projected={sim.goodUnits} unit="u" />
                <WhatIfValue label="QUALITY" baseline={sim.baselineQuality} projected={sim.quality} unit="%" />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", padding: 15, gap: 9 }}>
                <div style={{ padding: 11, border: "1px solid var(--line)" }}><span style={{ fontSize: 7, color: "var(--muted)" }}>GRID IMPORT</span><strong style={{ display: "block", marginTop: 6, fontSize: 16 }}>{number(sim.gridImport, 1)} kW</strong><span style={{ fontSize: 7, color: "var(--muted)" }}>renewable modeled at {sim.renewableAvailability}%</span></div>
                <div style={{ padding: 11, border: "1px solid var(--line)" }}><span style={{ fontSize: 7, color: "var(--muted)" }}>SAFE FLEXIBILITY</span><strong style={{ display: "block", marginTop: 6, fontSize: 16 }}>{number(sim.safeFlexibility, 2)} kW</strong><span style={{ fontSize: 7, color: "var(--muted)" }}>{number(sim.selectedReduction, 2)} kW selected</span></div>
                <div style={{ padding: 11, border: "1px solid var(--line)" }}><span style={{ fontSize: 7, color: "var(--muted)" }}>DOWNTIME</span><strong style={{ display: "block", marginTop: 6, fontSize: 16 }}>{number(sim.downtimeMin, 0)} min</strong><span style={{ fontSize: 7, color: "var(--muted)" }}>{sim.outageCount} selected outage{sim.outageCount === 1 ? "" : "s"}</span></div>
                <div style={{ padding: 11, border: `1px solid ${sim.reserveGap > 0 ? "#efdfbd" : "#d3ebe1"}`, background: sim.reserveGap > 0 ? "#fffaf1" : "#f5fcf9" }}><span style={{ fontSize: 7, color: "var(--muted)" }}>GRID GAP</span><strong style={{ display: "block", marginTop: 6, fontSize: 16 }}>{number(sim.reserveGap, 2)} kW</strong><span style={{ fontSize: 7, color: sim.reserveGap > 0 ? "var(--amber)" : "var(--green)" }}>{sim.decision}</span></div>
              </div>
            </section>

            <div className="scenario-result-grid">
              <section className="panel">
                <div className="panel-head"><div><div className="eyebrow">ENERGY RESPONSE</div><h2>Baseline vs Simulated Power</h2></div><Zap size={17} /></div>
                <ChartFrame className="analytics-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={[{ name: "POWER", baseline: sim.baselinePower, scenario: sim.scenarioPowerBeforeControl, whatIf: sim.projectedPower }, { name: "ENERGY / H", baseline: sim.baselinePower, scenario: sim.scenarioPowerBeforeControl, whatIf: sim.projectedPower }]} margin={{ top: 8, right: 14, left: 0, bottom: 0 }}>
                      <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" />
                      <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 8 }} />
                      <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 8 }} width={42} />
                      <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => [`${number(v, 2)} kW`, clean(name)]} />
                      <Legend wrapperStyle={{ fontSize: 9 }} />
                      <Bar dataKey="baseline" fill="var(--muted)" name="Baseline" radius={[2,2,0,0]} />
                      <Bar dataKey="scenario" fill="var(--amber)" name="Scenario" radius={[2,2,0,0]} />
                      <Bar dataKey="whatIf" fill="var(--cyan)" name="What-If" radius={[2,2,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </ChartFrame>
              </section>

              <section className="panel">
                <div className="panel-head"><div><div className="eyebrow">QUALITY MIX</div><h2>Good vs Loss / Reject</h2></div><Shield size={17} /></div>
                <ChartFrame className="analytics-chart" style={{ display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={donutData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius="50%" outerRadius="74%" paddingAngle={2}>
                        {donutData.map((entry, index) => <Cell key={entry.name} fill={donutColors[index % donutColors.length]} />)}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => [`${number(v, 1)} u`, name]} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ position: "absolute", textAlign: "center", pointerEvents: "none" }}><strong style={{ display: "block", fontSize: 20 }}>{number(sim.quality, 1)}%</strong><span style={{ fontSize: 7, color: "var(--muted)" }}>PROJECTED QUALITY</span></div>
                </ChartFrame>
              </section>
            </div>

            <div className="scenario-result-grid">
              <section className="panel">
                <div className="panel-head"><div><div className="eyebrow">FACTORY TRAJECTORY</div><h2>Power & Production Over Time</h2></div><TimerReset size={17} /></div>
                <ChartFrame className="energy-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={sim.timeline}>
                      <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 5" />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 8 }} />
                      <YAxis yAxisId="power" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 8 }} width={42} />
                      <YAxis yAxisId="production" orientation="right" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 8 }} width={42} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 9 }} />
                      <Line yAxisId="power" type="monotone" dataKey="baselinePower" stroke="var(--muted)" strokeWidth={1.8} dot={false} name="Baseline power" />
                      <Line yAxisId="power" type="monotone" dataKey="projectedPower" stroke="var(--cyan)" strokeWidth={2.4} dot={false} name="What-If power" />
                      <Line yAxisId="production" type="monotone" dataKey="baselineProduction" stroke="var(--amber)" strokeWidth={1.6} strokeDasharray="4 4" dot={false} name="Baseline production" />
                      <Line yAxisId="production" type="monotone" dataKey="projectedProduction" stroke="var(--green)" strokeWidth={2.1} dot={false} name="What-If production" />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartFrame>
              </section>

              <section className="panel">
                <div className="panel-head"><div><div className="eyebrow">MACHINE FLEXIBILITY</div><h2>Asset-Level Consequences</h2></div><SlidersHorizontal size={17} /></div>
                <div style={{ padding: "0 15px 10px" }}>
                  {sim.machineRows.map((row) => {
                    const maxPower = Math.max(liveBasePower / 2, 1);
                    const width = Math.min(100, row.projectedPower / maxPower * 100);
                    const outage = row.outage;
                    return (
                      <div key={row.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
                        <div style={{ display: "grid", gridTemplateColumns: "86px 1fr 64px", gap: 8, alignItems: "center" }}>
                          <div><strong style={{ display: "block", fontSize: 8 }}>{row.id}</strong><span style={{ color: "var(--muted)", fontSize: 7 }}>{row.status}</span></div>
                          <div><div style={{ height: 7, background: "var(--line)", position: "relative" }}><i style={{ display: "block", height: "100%", width: `${width}%`, background: outage ? "var(--red)" : row.status === "CONTROLLED" ? "var(--cyan)" : "var(--green)" }} /></div><div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, color: "var(--muted)", fontSize: 7 }}><span>{number(row.power, 1)} → {number(row.projectedPower, 1)} kW</span><span>{row.selectedReduction > 0 ? `-${number(row.selectedReduction, 2)} kW` : row.anomaly ? "DEGRADED" : ""}</span></div></div>
                          <b style={{ textAlign: "right", fontSize: 8 }}>{row.outage ? "OFFLINE" : row.status}</b>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>

            <section className="panel" style={{ marginTop: 11 }}>
              <div className="panel-head"><div><div className="eyebrow">AI DECISION CHAIN</div><h2>Why the Simulator Reached This Result</h2></div><Bot size={17} /></div>
              <div style={{ padding: 15, display: "grid", gridTemplateColumns: "1.05fr .95fr", gap: 12 }}>
                <div style={{ border: `1px solid ${sim.reserveGap > 0 ? "#efdfbd" : "#d3ebe1"}`, background: sim.reserveGap > 0 ? "#fffaf1" : "#f5fcf9", padding: 15 }}>
                  <div style={{ color: sim.reserveGap > 0 ? "var(--amber)" : "var(--green)", fontSize: 8, fontWeight: 800, letterSpacing: ".1em" }}>SYSTEM DECISION</div>
                  <strong style={{ display: "block", marginTop: 8, fontSize: 15 }}>{sim.decision}</strong>
                  <div style={{ marginTop: 12, display: "grid", gap: 7, fontSize: 8, color: "var(--muted)", lineHeight: 1.45 }}>{sim.explanation.map((line, index) => <div key={`${line}-${index}`}><b style={{ color: "var(--text)", marginRight: 5 }}>{index + 1}.</b>{line}</div>)}</div>
                </div>
                <div style={{ border: "1px solid var(--line)", padding: 15 }}>
                  <div className="eyebrow">SAFETY ENVELOPE</div>
                  <div style={{ marginTop: 11, height: 16, border: "1px solid var(--line)", background: "var(--surface-2)", position: "relative" }}><i style={{ display: "block", height: "100%", width: `${Math.min(100, sim.safeFlexibility > 0 ? sim.selectedReduction / sim.safeFlexibility * 100 : 0)}%`, background: "var(--cyan)" }} /></div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginTop: 12 }}><div><span style={{ display: "block", color: "var(--muted)", fontSize: 7 }}>REQUIRED</span><strong style={{ display: "block", marginTop: 5, fontSize: 14 }}>{number(sim.requiredReduction, 2)} kW</strong></div><div><span style={{ display: "block", color: "var(--muted)", fontSize: 7 }}>SELECTED</span><strong style={{ display: "block", marginTop: 5, fontSize: 14 }}>{number(sim.selectedReduction, 2)} kW</strong></div><div><span style={{ display: "block", color: "var(--muted)", fontSize: 7 }}>PROTECTED</span><strong style={{ display: "block", marginTop: 5, fontSize: 14 }}>{sim.machineRows.filter((row) => !row.outage && (row.criticality.includes("HIGH") || row.criticality.includes("CRITICAL") || row.fixed)).length}</strong></div></div>
                  <div style={{ marginTop: 13, paddingTop: 12, borderTop: "1px solid var(--line)", fontSize: 8, color: "var(--muted)", lineHeight: 1.5 }}>The simulation remains non-destructive. No ROS control command is issued by <strong style={{ color: "var(--text)" }}>SIMULATE CONSEQUENCES</strong>.</div>
                </div>
              </div>
            </section>
          </>
        ) : (
          <section className="panel">
            <div className="panel-head"><div><div className="eyebrow">READY FOR SIMULATION</div><h2>{selectedLive.name}</h2></div><Bot size={17} /></div>
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 9 }}>Configure outages, grid requirements and the operating objective above, then run <strong style={{ color: "var(--text)" }}>SIMULATE CONSEQUENCES</strong> to generate the energy, production, quality and machine-level projection.</div>
          </section>
        )}
      </div>

      <div className="scenario-result-grid" style={{ marginTop: 11 }}>
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">LIVE DIGITAL TWIN</div><h2>Current Operating State</h2></div><Status value={activeId} /></div>
          <div className="result-kpis"><DataKpi label="DEMAND" value={`${number(factory.factory_power_kw, 1)} kW`} /><DataKpi label="REQUIRED" value={`${number(factory.required_reduction_kw, 2)} kW`} /><DataKpi label="RESERVE" value={`${number(factory.deployable_flexibility_kw, 2)} kW`} /><DataKpi label="ACTIVE CONTROLS" value={controls.length} /></div>
          <div className={`decision-banner ${Number(factory.reserve_margin_kw) < 0 ? "warning" : "safe"}`}><Shield size={18} /><div><span>SYSTEM DECISION</span><strong>{factory.system_action || "NO GRID RESPONSE REQUIRED"}</strong></div></div>
        </section>
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">LIVE CONTROLS</div><h2>Safe Flexibility Deployment</h2></div></div>
          {controls.length ? controls.map((control) => <div className="control-detail-row" key={control.machine_id}><div><strong>{control.machine_id}</strong><span>{control.state}</span></div><b>{number(control.power_kw, 1)} kW</b><Status value="DEPLOYED" compact /></div>) : <EmptyState text="No active controls" />}
        </section>
      </div>
    </div>
  );
}

function App() {
  const [page, setPage] = useState("overview");
  const [data, setData] = useState(null);
  const [energy12, setEnergy12] = useState(null);
  const [energy24, setEnergy24] = useState(null);
  const [production, setProduction] = useState(null);
  const [efficiency, setEfficiency] = useState(null);
  const [controlStatus, setControlStatus] = useState(null);
  const [selectedMachine, setSelectedMachine] = useState(null);
  const [machineDetail, setMachineDetail] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [energyRange, setEnergyRange] = useState(12);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [scenarioBusy, setScenarioBusy] = useState(null);
  const [scenarioMessage, setScenarioMessage] = useState("");
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("indus_twin_theme") || "light";
    } catch {
      return "light";
    }
  });

  async function getJson(path, fallback = null) {
    try {
      const response = await fetch(`${API}${path}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error(`INDUS_TWIN ${path}:`, error);
      return fallback;
    }
  }

  async function loadData() {
    const [dashboard, e12, e24, prod, eff, controls] = await Promise.all([
      getJson("/api/dashboard"),
      getJson("/api/analytics/energy?hours=12", { history: [], latest_machine_power: [] }),
      getJson("/api/analytics/energy?hours=24", { history: [], latest_machine_power: [] }),
      getJson("/api/analytics/production?hours=12", null),
      getJson("/api/analytics/efficiency?hours=12", null),
      getJson("/api/control/status", { active_controls: [], active_control_count: 0 }),
    ]);
    if (dashboard) setData((current) => ({ ...dashboard, control: controls || current?.control }));
    setEnergy12(e12);
    setEnergy24(e24);
    setProduction(prod);
    setEfficiency(eff);
    setControlStatus(controls);
    setLastUpdate(new Date());

    if (selectedMachine?.machine_id) {
      const detail = await getJson(`/api/machines/${selectedMachine.machine_id}/dashboard?hours=12`, null);
      if (detail?.machine) {
        setMachineDetail(detail);
        setSelectedMachine(detail.machine);
      }
    }
  }

  async function runScenario(scenarioId, action) {
    setScenarioBusy(scenarioId);
    setScenarioMessage("");
    try {
      const response = await fetch(`${API}/api/scenario`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, scenario_id: action === "STOP" ? scenarioId : scenarioId }),
      });
      const result = await response.json();
      if (!response.ok || result.success === false) throw new Error(result.message || `HTTP ${response.status}`);
      setScenarioMessage(result.message || "Scenario command published.");
      await new Promise((resolve) => setTimeout(resolve, 900));
      await loadData();
    } catch (error) {
      console.error(error);
      setScenarioMessage(`Scenario command failed: ${error.message}`);
    } finally {
      setScenarioBusy(null);
    }
  }

  useEffect(() => {
    try {
      localStorage.setItem("indus_twin_theme", theme);
    } catch {
      // Ignore storage failures; theme still applies for the current session.
    }
  }, [theme]);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 4000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedMachine?.machine_id) {
      setMachineDetail(null);
      return;
    }
    getJson(`/api/machines/${selectedMachine.machine_id}/dashboard?hours=12`, null).then((result) => {
      if (result?.machine) {
        setMachineDetail(result);
        setSelectedMachine(result.machine);
      }
    });
  }, [selectedMachine?.machine_id]);

  const factory = data?.factory || {};
  const energy = energyRange === 24 ? energy24 : energy12;

  return (
    <div className={`app theme-${theme}`}>
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-icon"><Grid3X3 size={20} /></div>
          <div><strong>INDUS_TWIN</strong><span>INDUSTRIAL DIGITAL TWIN</span></div>
        </div>
        <div className="plant-card"><span>ACTIVE FACILITY</span><strong>PLANT 01 / CHENNAI</strong><div><RadioDot /></div></div>
        <nav>
          {NAV.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => { setPage(item.id); setSidebarOpen(false); }}><Icon size={17} /><span>{item.label}</span>{page === item.id && <ChevronRight size={14} />}</button>;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="stack-status"><span className="online-dot" /><div><strong>SYSTEM ONLINE</strong><small>ROS 2 · AI · FASTAPI</small></div></div>
          <div className="stack-status"><Cpu size={14} /><div><strong>LIVE SYNC</strong><small>{lastUpdate ? lastUpdate.toLocaleTimeString() : "CONNECTING"}</small></div></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumb"><button className="mobile-menu" onClick={() => setSidebarOpen((v) => !v)}><Menu size={18} /></button><span>INDUS_TWIN</span><ChevronRight size={13} /><strong>{NAV.find((item) => item.id === page)?.label}</strong></div>
          <div className="top-status">
            <div><span className="online-dot" /> LIVE</div>
            <div><Cpu size={13} /> API CONNECTED</div>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}
              title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
            >
              {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}
              <span>{theme === "light" ? "DARK" : "LIGHT"}</span>
            </button>
            <div>{lastUpdate ? lastUpdate.toLocaleTimeString() : "—"}</div>
          </div>
        </header>

        <div className="status-ribbon">
          <div><span>GRID</span><strong>{clean(factory.grid_status || "NORMAL")}</strong></div>
          <div><span>DEMAND</span><strong>{number(factory.factory_power_kw, 1)} kW</strong></div>
          <div><span>RESERVE</span><strong>{number(factory.deployable_flexibility_kw, 2)} kW</strong></div>
          <div><span>AI CONTROLS</span><strong>{controlStatus?.active_control_count || 0}</strong></div>
          <div className="ribbon-spacer" />
          <div className="refresh-state"><RefreshCw size={12} /> AUTO UPDATE · 4S</div>
        </div>

        {!data ? <div className="loading"><div className="loader" /><span>CONNECTING TO INDUSTRIAL TWIN</span></div> : (
          <>
            {page === "overview" && <Overview data={data} energy={energy} energyRange={energyRange} setEnergyRange={setEnergyRange} selectedMachine={selectedMachine} setSelectedMachine={setSelectedMachine} controlStatus={controlStatus} />}
            {page === "energy" && <EnergyPage data={{ ...data, control: controlStatus }} energy={energy} energyRange={energyRange} setEnergyRange={setEnergyRange} />}
            {page === "analytics" && <AnalyticsPage data={data} production={production} efficiency={efficiency} energyRange={energyRange} setEnergyRange={setEnergyRange} energy={energy} />}
            {page === "maintenance" && <MaintenancePage data={data} refresh={loadData} />}
            {page === "scenarios" && <ScenariosPage data={data} controlStatus={controlStatus} onScenario={runScenario} busyScenario={scenarioBusy} message={scenarioMessage} />}
          </>
        )}
      </main>

      <MachinePanel machine={selectedMachine} detail={machineDetail} close={() => setSelectedMachine(null)} />
    </div>
  );
}

export default App;
