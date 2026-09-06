"""Pydantic v2 schemas for the simulation API."""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------
class SimulationRequest(BaseModel):
    """User-tunable parameters. Defaults match Table 1 of the paper."""

    L: float = Field(0.20, gt=0, description="Block length, m")
    k: float = Field(20.0, gt=0, description="Absolute permeability, md")
    phi: float = Field(0.30, gt=0, lt=1, description="Porosity")
    mu_o: float = Field(1.0, gt=0, description="Oil viscosity, cp")
    mu_w: float = Field(1.0, gt=0, description="Water viscosity, cp")
    kro0: float = Field(0.75, gt=0, le=1, description="Oil rel-perm end point")
    krw0: float = Field(0.20, gt=0, le=1, description="Water rel-perm end point")
    no: float = Field(4.0, ge=1, description="Oil rel-perm exponent")
    nw: float = Field(4.0, ge=1, description="Water rel-perm exponent")
    B: float = Field(10.0, gt=0, description="Capillary pressure constant, kPa")
    Si: float = Field(0.001, gt=0, lt=1, description="Initial normalised water saturation")
    Swi: float = Field(0.0, ge=0, lt=1, description="Irreducible water saturation")
    Sor: float = Field(0.0, ge=0, lt=1, description="Residual oil saturation")
    tmax: float = Field(40.0, gt=0, description="End time, days")
    nx: int = Field(300, ge=10, le=2000, description="Number of grid blocks")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
class ProfileSeries(BaseModel):
    time_days: float
    time_label: str
    x_m: list[float]
    values: list[float]


class CurveData(BaseModel):
    x: list[float]
    y: list[float]


class SaturationMap(BaseModel):
    """Space-time saturation frames for the grid/heatmap display."""

    times_days: list[float]          # frame times, t = 0 first
    x_m: list[float]                 # block-centre positions
    frames: list[list[float]]        # values[j][i] = S at time j, position i


class PressureMap(BaseModel):
    """Space-time oil/water pressure frames for the timelapse display."""

    times_days: list[float]          # frame times, t = 0 first
    x_m: list[float]                 # block-centre positions
    oil_pressure_kPa: list[list[float]]
    water_pressure_kPa: list[list[float]]


class SummaryStats(BaseModel):
    front_position_1d_cm: float | None = None
    oil_pressure_behind_front_kPa: float
    water_pressure_at_Si_kPa: float
    half_recovery_days: float | None = None
    mass_balance_error: float


# ---------------------------------------------------------------------------
# Simulation response
# ---------------------------------------------------------------------------
class SimulationResponse(BaseModel):
    saturation_profiles: list[ProfileSeries]
    analytical_profiles: list[ProfileSeries]
    oil_pressure_profiles: list[ProfileSeries]
    water_pressure_profiles: list[ProfileSeries]
    saturation_map: SaturationMap
    pressure_map: PressureMap
    recovery_curve: CurveData
    analytical_recovery: CurveData
    summary: SummaryStats


# ---------------------------------------------------------------------------
# Properties response
# ---------------------------------------------------------------------------
class RelativePermeabilityData(BaseModel):
    S: list[float]
    kro: list[float]
    krw: list[float]


class FractionalFlowData(BaseModel):
    S: list[float]
    fw: list[float]


class CapillaryPressureData(BaseModel):
    S: list[float]
    Pc_kPa: list[float]
    dPc_dSw_kPa: list[float]


class DiffusionCoefficientData(BaseModel):
    S: list[float]
    D_cm2_s: list[float]


class PropertiesResponse(BaseModel):
    relative_permeability: RelativePermeabilityData
    fractional_flow: FractionalFlowData
    capillary_pressure: CapillaryPressureData
    diffusion_coefficient: DiffusionCoefficientData
