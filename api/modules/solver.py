"""
1D countercurrent spontaneous imbibition solvers.

Ported from the Pooladi-Darvish & Firoozabadi (SPE Journal, March 2000)
reference implementation. Contains:

  - Properties dataclass (rock/fluid description, Table 1)
  - DiffusionSolver: nonlinear diffusion equation, Eqs. 1-6
  - McWhorterSunada: semi-analytical infinite-acting solution

Everything is in SI units internally (m, s, Pa, m^2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.linalg import solve_banded

# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------
MD_TO_M2 = 9.869233e-16       # 1 md  -> m^2
CP_TO_PAS = 1.0e-3            # 1 cp  -> Pa.s
PSI_TO_PA = 6894.757          # 1 psi -> Pa
PA_TO_PSI = 1.0 / PSI_TO_PA
DAY = 86400.0
HOUR = 3600.0


# ---------------------------------------------------------------------------
# Rock / fluid description
# ---------------------------------------------------------------------------
@dataclass
class Properties:
    """Rock and fluid properties (SI units internally)."""

    L: float = 0.20                       # length, m
    k: float = 20.0 * MD_TO_M2            # absolute permeability, m^2
    phi: float = 0.30                     # porosity
    mu_o: float = 1.0 * CP_TO_PAS         # oil viscosity, Pa.s
    mu_w: float = 1.0 * CP_TO_PAS         # water viscosity, Pa.s
    kro0: float = 0.75                    # oil rel-perm end point
    krw0: float = 0.20                    # water rel-perm end point
    no: float = 4.0                       # oil rel-perm exponent
    nw: float = 4.0                       # water rel-perm exponent
    B: float = 1.45 * PSI_TO_PA           # capillary pressure constant, Pa
    Si: float = 0.001                     # normalised initial water saturation
    Swi: float = 0.0                      # irreducible water saturation
    Sor: float = 0.0                      # residual oil saturation
    model: str = "full"                   # "full" or "zero_oil_gradient"

    # Kirchhoff-transform table, built lazily.
    _S_tab: np.ndarray = field(default=None, repr=False)
    _Phi_tab: np.ndarray = field(default=None, repr=False)

    @property
    def dS(self) -> float:
        return 1.0 - self.Sor - self.Swi

    @property
    def phi_eff(self) -> float:
        return self.phi * self.dS

    def kro(self, S):
        return self.kro0 * np.power(np.clip(1.0 - S, 0.0, 1.0), self.no)

    def krw(self, S):
        return self.krw0 * np.power(np.clip(S, 0.0, 1.0), self.nw)

    def lam_o(self, S):
        return self.kro(S) / self.mu_o

    def lam_w(self, S):
        return self.krw(S) / self.mu_w

    def Pc(self, S):
        return -self.B * np.log(np.clip(S, 1e-300, None))

    def dPc_dS(self, S):
        return -self.B / np.clip(S, 1e-300, None)

    def fw(self, S):
        lo, lw = self.lam_o(S), self.lam_w(S)
        return np.where(lo + lw > 0.0, lw / np.maximum(lo + lw, 1e-300), 1.0)

    def Lambda(self, S):
        S = np.clip(S, 0.0, 1.0)
        if self.model == "zero_oil_gradient":
            return self.k * self.lam_w(S) * (-self.dPc_dS(S))
        return self.k * self.lam_o(S) * self.fw(S) * (-self.dPc_dS(S))

    def D(self, S):
        return self.Lambda(S) / self.phi_eff

    def _build_kirchhoff(self, n=200_001):
        s = np.linspace(0.0, 1.0, n)
        lam = self.Lambda(s)
        Phi = np.concatenate(([0.0], np.cumsum(0.5 * (lam[1:] + lam[:-1]) * np.diff(s))))
        self._S_tab, self._Phi_tab = s, Phi

    def Phi(self, S):
        if self._S_tab is None:
            self._build_kirchhoff()
        return np.interp(np.clip(S, 0.0, 1.0), self._S_tab, self._Phi_tab)

    def oil_pressure_of_S(self, S, n=20_001):
        s = np.linspace(1.0, max(self.Si * 0.5, 1e-6), n)
        integrand = self.fw(s) * self.dPc_dS(s)
        po = np.concatenate(([0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(s))))
        return np.interp(np.clip(S, s[-1], 1.0), s[::-1], po[::-1])

    def water_pressure_of_S(self, S):
        return self.oil_pressure_of_S(S) - self.Pc(S)


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------
def make_grid(L, nx, ratio=1.0):
    if abs(ratio - 1.0) < 1e-12:
        dx = np.full(nx, L / nx)
    else:
        dx = ratio ** np.arange(nx)
        dx *= L / dx.sum()
    xc = np.cumsum(dx) - 0.5 * dx
    d_face = 0.5 * (dx[:-1] + dx[1:])
    return dx, xc, d_face


# ---------------------------------------------------------------------------
# Cumulative trapezoidal integration helper
# ---------------------------------------------------------------------------
def _cumtrap(y, x):
    return np.concatenate(([0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))))


# ---------------------------------------------------------------------------
# 1. Nonlinear diffusion model, Eqs. 1-6
# ---------------------------------------------------------------------------
class DiffusionSolver:
    """
    Fully implicit, cell-centred finite-volume solution of

        phi_eff dS/dt = d/dx ( Lambda(S) dS/dx )

    with Kirchhoff-transform face conductivities.
    """

    def __init__(self, props: Properties, nx: int = 300, grid_ratio: float = 1.0):
        self.p = props
        self.nx = nx
        self.dx, self.x, self.df = make_grid(props.L, nx, grid_ratio)
        self.d_in = 0.5 * self.dx[0]
        self.S_bc = 1.0

    def _face_flux(self, S):
        p = self.p
        Phi = p.Phi(S)
        u = np.zeros(self.nx + 1)
        u[0] = -(Phi[0] - p.Phi(self.S_bc)) / self.d_in
        u[1:-1] = -(Phi[1:] - Phi[:-1]) / self.df
        u[-1] = 0.0
        return u

    def _residual(self, S, Sn, dt):
        p = self.p
        u = self._face_flux(S)
        return p.phi_eff * self.dx * (S - Sn) / dt + (u[1:] - u[:-1])

    def _jacobian_banded(self, S, dt):
        p, n = self.p, self.nx
        lam = p.Lambda(S)
        ab = np.zeros((3, n))
        main = p.phi_eff * self.dx / dt
        main[0] += lam[0] / self.d_in
        main[:-1] += lam[:-1] / self.df
        main[1:] += lam[1:] / self.df
        ab[0, 1:] = -lam[1:] / self.df
        ab[1, :] = main
        ab[2, :-1] = -lam[:-1] / self.df
        return ab

    def _newton(self, Sn, dt, tol=1e-10, itmax=25):
        S = Sn.copy()
        for it in range(itmax):
            R = self._residual(S, Sn, dt)
            scale = self.p.phi_eff * self.dx.min() / dt
            if np.max(np.abs(R)) / scale < tol:
                return S, it, True
            ab = self._jacobian_banded(S, dt)
            dS = solve_banded((1, 1), ab, -R)
            step = min(1.0, 0.2 / max(np.max(np.abs(dS)), 1e-30))
            S = np.clip(S + step * dS, 1e-8, 1.0)
        return S, itmax, False

    def run(self, report_times, dt0=1.0, dt_max=None, growth=1.25, verbose=False):
        p = self.p
        report_times = np.atleast_1d(np.sort(np.asarray(report_times, float)))
        tmax = report_times[-1]
        dt_max = dt_max if dt_max is not None else tmax / 50.0

        S = np.full(self.nx, p.Si)
        S0 = S.copy()
        t, dt, Q = 0.0, dt0, 0.0
        snaps, hist_t, hist_R = {}, [0.0], [0.0]
        k_rep = 0

        def recovery(S):
            return np.sum((S - S0) * self.dx) / ((1.0 - p.Si) * p.L)

        while t < tmax - 1e-12:
            dt = min(dt, dt_max, tmax - t)
            if k_rep < len(report_times):
                dt = min(dt, report_times[k_rep] - t)
            Snew, nit, ok = self._newton(S, dt)
            if not ok:
                dt *= 0.25
                continue
            Q += self._face_flux(Snew)[0] * dt
            S, t = Snew, t + dt
            hist_t.append(t)
            hist_R.append(recovery(S))
            if k_rep < len(report_times) and abs(t - report_times[k_rep]) < 1e-9:
                snaps[report_times[k_rep]] = S.copy()
                if verbose:
                    print(f"    t = {t/DAY:9.4f} d   recovery = {hist_R[-1]:.4f}")
                k_rep += 1
            dt *= growth if nit <= 4 else 1.0

        u = self._face_flux(S)
        stored = p.phi_eff * np.sum((S - S0) * self.dx)
        mb_err = (Q - stored) / max(Q, 1e-30)
        return dict(x=self.x, snapshots=snaps, t=np.array(hist_t),
                    recovery=np.array(hist_R), S_final=S, flux_final=u,
                    influx=Q, mass_balance_error=mb_err)


# ---------------------------------------------------------------------------
# 2. McWhorter & Sunada semi-analytical solution (infinite acting)
# ---------------------------------------------------------------------------
class McWhorterSunada:
    """
    Exact self-similar solution on a semi-infinite domain.

    Q_w(t) = 2 A sqrt(t),  x(S, t) = lambda(S) sqrt(t).
    """

    def __init__(self, props: Properties, npts: int = 4001,
                 itmax: int = 500, omega: float = 0.6, tol: float = 1e-10):
        p = self.p = props
        S = np.linspace(p.Si, 1.0, npts)
        D = p.D(S)
        F = (S - p.Si) / (1.0 - p.Si)

        F_floor = 1e-8

        for it in range(itmax):
            g = D / np.maximum(F, F_floor)
            I0 = _cumtrap(g, S)
            I1 = _cumtrap(S * g, S)
            tail0 = I0[-1] - I0
            tail1 = I1[-1] - I1
            num = tail1 - S * tail0
            den = I1[-1] - p.Si * I0[-1]
            Fnew = np.clip(1.0 - num / den, 1e-30, 1.0)
            Fnew[0], Fnew[-1] = 1e-30, 1.0
            err = np.max(np.abs(Fnew - F))
            F = (1.0 - omega) * F + omega * Fnew
            if err < tol:
                break

        self.S, self.F, self.iters, self.err = S, F, it + 1, err
        self.A = p.phi_eff * np.sqrt(0.5 * den)
        g = D / np.maximum(F, F_floor)
        I0 = _cumtrap(g, S)
        self.lam = p.phi_eff * (I0[-1] - I0) / self.A

    def front_position(self, t):
        return self.lam[0] * np.sqrt(t)

    def profile(self, t):
        return self.lam * np.sqrt(t), self.S

    def cumulative_influx(self, t):
        return 2.0 * self.A * np.sqrt(t)

    def recovery(self, t):
        p = self.p
        return self.cumulative_influx(t) / (p.phi_eff * (1.0 - p.Si) * p.L)
