// Typed API wrapper for the simulation backend.

export interface SimulationRequest {
  L: number;
  k: number;
  phi: number;
  mu_o: number;
  mu_w: number;
  kro0: number;
  krw0: number;
  no: number;
  nw: number;
  B: number;
  Si: number;
  Swi: number;
  Sor: number;
  tmax: number;
  nx: number;
}

export interface ProfileSeries {
  time_days: number;
  time_label: string;
  x_m: number[];
  values: number[];
}

export interface CurveData {
  x: number[];
  y: number[];
}

export interface SummaryStats {
  front_position_1d_cm: number | null;
  oil_pressure_behind_front_psi: number;
  water_pressure_at_Si_psi: number;
  half_recovery_days: number | null;
  mass_balance_error: number;
}

export interface SimulationResponse {
  saturation_profiles: ProfileSeries[];
  analytical_profiles: ProfileSeries[];
  oil_pressure_profiles: ProfileSeries[];
  water_pressure_profiles: ProfileSeries[];
  recovery_curve: CurveData;
  analytical_recovery: CurveData;
  summary: SummaryStats;
}

export interface PropertiesResponse {
  relative_permeability: { S: number[]; kro: number[]; krw: number[] };
  fractional_flow: { S: number[]; fw: number[] };
  capillary_pressure: { S: number[]; Pc_psi: number[]; dPc_dSw_psi: number[] };
  diffusion_coefficient: { S: number[]; D_cm2_s: number[] };
}

const BASE = "/api/py";

export async function runSimulation(
  params: SimulationRequest
): Promise<SimulationResponse> {
  const res = await fetch(`${BASE}/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`Simulation failed: ${res.statusText}`);
  return res.json();
}

export async function computeProperties(
  params: SimulationRequest
): Promise<PropertiesResponse> {
  const res = await fetch(`${BASE}/properties`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`Properties request failed: ${res.statusText}`);
  return res.json();
}
