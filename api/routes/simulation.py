"""Simulation and property-calculation endpoints."""

import numpy as np
from fastapi import APIRouter

from api.modules.solver import (
    CP_TO_PAS,
    DAY,
    HOUR,
    KPA_TO_PA,
    MD_TO_M2,
    PA_TO_KPA,
    DiffusionSolver,
    McWhorterSunada,
    Properties,
)
from api.schemas.simulation import (
    CapillaryPressureData,
    CurveData,
    DiffusionCoefficientData,
    FractionalFlowData,
    PressureMap,
    ProfileSeries,
    PropertiesResponse,
    RelativePermeabilityData,
    SaturationMap,
    SimulationRequest,
    SimulationResponse,
    SummaryStats,
)

router = APIRouter(tags=["simulation"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_props(req: SimulationRequest) -> Properties:
    """Convert a frontend request into a Properties object."""
    return Properties(
        L=req.L,
        k=req.k * MD_TO_M2,
        phi=req.phi,
        mu_o=req.mu_o * CP_TO_PAS,
        mu_w=req.mu_w * CP_TO_PAS,
        kro0=req.kro0,
        krw0=req.krw0,
        no=req.no,
        nw=req.nw,
        B=req.B * KPA_TO_PA,
        Si=req.Si,
        Swi=req.Swi,
        Sor=req.Sor,
    )


def _time_label(t: float) -> str:
    """Human-readable label for a report time (seconds)."""
    days = t / DAY
    hours = t / HOUR
    if days >= 1.0:
        return f"t = {days:g} day{'s' if days != 1 else ''}"
    return f"t = {hours:g} hr{'s' if hours != 1 else ''}"


# ---------------------------------------------------------------------------
# POST /api/py/simulate
# ---------------------------------------------------------------------------
@router.post("/simulate", response_model=SimulationResponse)
def simulate(req: SimulationRequest):
    """Run the diffusion solver + McWhorter-Sunada analytical solution."""
    props = _build_props(req)
    tmax_s = req.tmax * DAY

    # Choose report times: 2 hr, 1 day, 5 days, and tmax (if applicable).
    report = [t for t in (2 * HOUR, 1 * DAY, 5 * DAY, tmax_s) if t <= tmax_s]
    if not report:
        report = [tmax_s]

    # Diffusion solver (Eqs. 1-6)
    diff = DiffusionSolver(props, req.nx).run(report, verbose=False)

    # McWhorter-Sunada analytical
    ms = McWhorterSunada(props)

    # --- Build response arrays -------------------------------------------

    sat_profiles: list[ProfileSeries] = []
    ana_profiles: list[ProfileSeries] = []
    oil_p_profiles: list[ProfileSeries] = []
    wat_p_profiles: list[ProfileSeries] = []

    for t in sorted(diff["snapshots"]):
        td = t / DAY
        label = _time_label(t)
        S = diff["snapshots"][t]
        x = diff["x"]

        sat_profiles.append(ProfileSeries(
            time_days=td, time_label=label,
            x_m=x.tolist(), values=S.tolist(),
        ))

        # Pressures from the diffusion solution
        po = props.oil_pressure_of_S(S) * PA_TO_KPA
        pw = (props.oil_pressure_of_S(S) - props.Pc(S)) * PA_TO_KPA
        oil_p_profiles.append(ProfileSeries(
            time_days=td, time_label=label,
            x_m=x.tolist(), values=po.tolist(),
        ))
        wat_p_profiles.append(ProfileSeries(
            time_days=td, time_label=label,
            x_m=x.tolist(), values=pw.tolist(),
        ))

        # Analytical profile (only if front hasn't reached end)
        if ms.front_position(t) < props.L:
            xa, Sa = ms.profile(t)
            ana_profiles.append(ProfileSeries(
                time_days=td, time_label=label + " (analytical)",
                x_m=xa.tolist(), values=Sa.tolist(),
            ))

    # Recovery curves
    td_num = (diff["t"] / DAY).tolist()
    R_num = diff["recovery"].tolist()

    # Analytical recovery on a fine grid
    t_ana = np.linspace(1e-4, min(td_num[-1], req.tmax), 400)
    R_ana = np.array([ms.recovery(t * DAY) for t in t_ana])
    # Cap analytical recovery at 1.0
    R_ana = np.minimum(R_ana, 1.0)

    # Summary
    front_1d = ms.front_position(DAY) * 100  # cm
    po_behind = props.oil_pressure_of_S(props.Si) * PA_TO_KPA
    pw_si = props.water_pressure_of_S(props.Si) * PA_TO_KPA
    R = diff["recovery"]
    t_half = float(np.interp(0.5, R, diff["t"]) / DAY) if R[-1] > 0.5 else None

    # Space-time saturation map: frames evenly spaced in sqrt(t).  The
    # spatial axis is downsampled so the payload stays bounded for large nx.
    stride = max(1, -(-req.nx // 300))
    sat_map = SaturationMap(
        times_days=(diff["frames_t"] / DAY).tolist(),
        x_m=diff["x"][::stride].tolist(),
        frames=diff["frames_S"][:, ::stride].tolist(),
    )

    # Pressure frames: derived from the saturation frames (countercurrent flow
    # makes oil pressure a unique function of saturation, Eq. 7).
    po_frames = props.oil_pressure_of_S(diff["frames_S"]) * PA_TO_KPA
    pw_frames = (props.oil_pressure_of_S(diff["frames_S"]) - props.Pc(diff["frames_S"])) * PA_TO_KPA
    pressure_map = PressureMap(
        times_days=sat_map.times_days,
        x_m=sat_map.x_m,
        oil_pressure_kPa=po_frames[:, ::stride].tolist(),
        water_pressure_kPa=pw_frames[:, ::stride].tolist(),
    )

    return SimulationResponse(
        saturation_profiles=sat_profiles,
        analytical_profiles=ana_profiles,
        oil_pressure_profiles=oil_p_profiles,
        water_pressure_profiles=wat_p_profiles,
        saturation_map=sat_map,
        pressure_map=pressure_map,
        recovery_curve=CurveData(x=td_num, y=R_num),
        analytical_recovery=CurveData(x=t_ana.tolist(), y=R_ana.tolist()),
        summary=SummaryStats(
            front_position_1d_cm=front_1d if front_1d < props.L * 100 else None,
            oil_pressure_behind_front_kPa=po_behind,
            water_pressure_at_Si_kPa=pw_si,
            half_recovery_days=t_half,
            mass_balance_error=diff["mass_balance_error"],
        ),
    )


# ---------------------------------------------------------------------------
# POST /api/py/properties
# ---------------------------------------------------------------------------
@router.post("/properties", response_model=PropertiesResponse)
def compute_properties(req: SimulationRequest):
    """Compute rock/fluid property curves for the given parameters."""
    props = _build_props(req)
    S = np.linspace(1e-4, 1.0 - 1e-9, 500)

    kro = props.kro(S)
    krw = props.krw(S)
    fw = props.fw(S)
    Pc = props.Pc(S) * PA_TO_KPA
    dPc = props.dPc_dS(S) * PA_TO_KPA
    D = props.D(S) * 1e4  # cm^2/s

    return PropertiesResponse(
        relative_permeability=RelativePermeabilityData(
            S=S.tolist(), kro=kro.tolist(), krw=krw.tolist(),
        ),
        fractional_flow=FractionalFlowData(
            S=S.tolist(), fw=fw.tolist(),
        ),
        capillary_pressure=CapillaryPressureData(
            S=S.tolist(), Pc_kPa=Pc.tolist(), dPc_dSw_kPa=dPc.tolist(),
        ),
        diffusion_coefficient=DiffusionCoefficientData(
            S=S.tolist(), D_cm2_s=D.tolist(),
        ),
    )
