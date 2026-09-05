"""
1D countercurrent spontaneous imbibition in a water-wet matrix block.

Reproduces the countercurrent model of

    M. Pooladi-Darvish and A. Firoozabadi,
    "Cocurrent and Countercurrent Imbibition in a Water-Wet Matrix Block",
    SPE Journal 5 (1), March 2000, 3-11.

Three independent solutions are implemented, so they can be cross-checked
against each other:

  1. `DiffusionSolver`   - the nonlinear diffusion equation, Eqs. 1-6.
                           Valid for countercurrent flow only (total
                           velocity is identically zero).
  2. `TwoPhaseSolver`    - the pressure formulation of Eqs. 9-16
                           (Peaceman-type, fully implicit, control-volume),
                           which solves for p_o and p_w directly.
  3. `McWhorterSunada`   - the semi-analytical infinite-acting solution
                           (Ref. 2 of the paper) used by the authors to
                           validate their numerical model.

Everything is done in SI units internally (m, s, Pa, m^2). Saturation is the
normalised water saturation

        S = (Sw - Siw) / (1 - Sor - Siw),

which is what Table 1 of the paper tabulates (Si = 0.001).

Base-case results (Table 1 data), which reproduce the published figures:

    quantity                                this code    paper
    front position at 1 day                  4.33 cm     ~4 cm   (Fig. 2)
    oil pressure behind the front            0.82 psi     ~0.8 psi (Fig. 1)
    water pressure at Si                    -9.20 psi    ~-9.2 psi (Fig. 1)
    recovery at 20 days                       0.47        ~0.47   (Fig. 5)
    half-recovery time                       22.6 d      >5 x 4.5 d (text)
    material-balance error                   ~1e-13       -

Usage
-----
    python countercurrent_imbibition.py                # base case, all figures
    python countercurrent_imbibition.py --nx 300 --tmax 40 --outdir figs
    python countercurrent_imbibition.py --no-twophase  # skip the p-based model

Author: written from the governing equations in the paper.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.linalg import solve_banded
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

# ----------------------------------------------------------------------------
# Unit conversions
# ----------------------------------------------------------------------------
MD_TO_M2 = 9.869233e-16      # 1 md      -> m^2
CP_TO_PAS = 1.0e-3           # 1 cp      -> Pa.s
PSI_TO_PA = 6894.757         # 1 psi     -> Pa
PA_TO_PSI = 1.0 / PSI_TO_PA
DAY = 86400.0                # 1 day     -> s
HOUR = 3600.0


# ----------------------------------------------------------------------------
# Rock / fluid description
# ----------------------------------------------------------------------------
@dataclass
class Properties:
    """Base-case data of Table 1 (SI units)."""

    L: float = 0.20                      # length, m
    k: float = 20.0 * MD_TO_M2           # absolute permeability, m^2
    phi: float = 0.30                    # porosity
    mu_o: float = 1.0 * CP_TO_PAS        # oil viscosity, Pa.s
    mu_w: float = 1.0 * CP_TO_PAS        # water viscosity, Pa.s
    kro0: float = 0.75                   # oil rel-perm end point
    krw0: float = 0.20                   # water rel-perm end point
    no: float = 4.0                      # oil rel-perm exponent
    nw: float = 4.0                      # water rel-perm exponent
    B: float = 1.45 * PSI_TO_PA          # capillary pressure constant, Pa
    Si: float = 0.001                    # normalised initial water saturation
    Swi: float = 0.0                     # irreducible water saturation
    Sor: float = 0.0                     # residual oil saturation

    # "full"              -> Eq. 2, the oil pressure gradient is retained
    # "zero_oil_gradient" -> Eq. 8, dp_o/dx neglected (unsaturated-flow
    #                        assumption; the paper shows it is not adequate)
    model: str = "full"

    # Kirchhoff-transform table, built lazily (see `_build_kirchhoff`)
    _S_tab: np.ndarray = field(default=None, repr=False)
    _Phi_tab: np.ndarray = field(default=None, repr=False)

    # -- saturation-dependent functions (Eqs. 19-20) -------------------------
    @property
    def dS(self) -> float:
        """Movable saturation range, Sw = Swi + dS * S."""
        return 1.0 - self.Sor - self.Swi

    @property
    def phi_eff(self) -> float:
        """Pore volume that participates, phi * (1 - Sor - Siw)."""
        return self.phi * self.dS

    def kro(self, S):
        return self.kro0 * np.power(np.clip(1.0 - S, 0.0, 1.0), self.no)

    def krw(self, S):
        return self.krw0 * np.power(np.clip(S, 0.0, 1.0), self.nw)

    def lam_o(self, S):                       # oil mobility, kro/mu_o
        return self.kro(S) / self.mu_o

    def lam_w(self, S):                       # water mobility, krw/mu_w
        return self.krw(S) / self.mu_w

    def Pc(self, S):                          # Eq. 20, Pa
        return -self.B * np.log(np.clip(S, 1e-300, None))

    def dPc_dS(self, S):                      # dPc/dS, Pa (negative)
        return -self.B / np.clip(S, 1e-300, None)

    def fw(self, S):
        """Water fractional flow, Eq. 3:  1 / (1 + (kro/mu_o)(mu_w/krw))."""
        lo, lw = self.lam_o(S), self.lam_w(S)
        return np.where(lo + lw > 0.0, lw / np.maximum(lo + lw, 1e-300), 1.0)

    # -- capillary diffusion -------------------------------------------------
    def Lambda(self, S):
        """
        Capillary "conductivity" [m^2/s] such that the countercurrent water
        flux is  u_w = -Lambda(S) dS/dx.

            Lambda = k (kro/mu_o) f_w (-dPc/dS)  = phi_eff * D(S)     (Eq. 2)

        i.e. Eq. 2 multiplied through by phi (and by dS for the change to
        normalised saturation). With model="zero_oil_gradient",

            Lambda = k (krw/mu_w) (-dPc/dS)                           (Eq. 8)
        """
        S = np.clip(S, 0.0, 1.0)
        if self.model == "zero_oil_gradient":
            return self.k * self.lam_w(S) * (-self.dPc_dS(S))
        return self.k * self.lam_o(S) * self.fw(S) * (-self.dPc_dS(S))

    def D(self, S):
        """Capillary diffusion coefficient of Eq. 2, m^2/s."""
        return self.Lambda(S) / self.phi_eff

    # -- Kirchhoff transform  Phi(S) = int_0^S Lambda(s) ds ------------------
    def _build_kirchhoff(self, n=200_001):
        s = np.linspace(0.0, 1.0, n)
        lam = self.Lambda(s)
        Phi = np.concatenate(([0.0], np.cumsum(0.5 * (lam[1:] + lam[:-1]) * np.diff(s))))
        self._S_tab, self._Phi_tab = s, Phi

    def Phi(self, S):
        """Kirchhoff potential; d(Phi)/dS = Lambda(S)."""
        if self._S_tab is None:
            self._build_kirchhoff()
        return np.interp(np.clip(S, 0.0, 1.0), self._S_tab, self._Phi_tab)

    # -- exact pressure/saturation relation for countercurrent flow ---------
    def oil_pressure_of_S(self, S, n=20_001):
        """
        For countercurrent flow (u_o = -u_w) the oil pressure is a unique
        function of saturation, independent of time:

            dp_o/dx = -u_o /(k*lam_o) = u_w/(k*lam_o),   u_w = -Lambda dS/dx
            =>  dp_o/dS = -Lambda/(k*lam_o) = f_w dPc/dS

        Integrating from the inlet, where S = 1 and p_o = 0, gives p_o(S).
        This is the curve plotted in Fig. 1 of the paper.
        """
        s = np.linspace(1.0, max(self.Si * 0.5, 1e-6), n)         # 1 -> Si
        integrand = self.fw(s) * self.dPc_dS(s)
        po = np.concatenate(([0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(s))))
        # np.interp needs increasing x
        return np.interp(np.clip(S, s[-1], 1.0), s[::-1], po[::-1])

    def water_pressure_of_S(self, S):
        """p_w = p_o - Pc."""
        return self.oil_pressure_of_S(S) - self.Pc(S)


# ----------------------------------------------------------------------------
# Grid
# ----------------------------------------------------------------------------
def make_grid(L, nx, ratio=1.0):
    """
    Cell sizes, centres and centre-to-centre distances.

    `ratio` > 1 grows the cells geometrically away from the inlet, which is
    where the solution is singular (S -> 1, kro -> 0, so dp_o/dx -> infinity).
    ratio = 1 gives the uniform grid used in the paper.
    """
    if abs(ratio - 1.0) < 1e-12:
        dx = np.full(nx, L / nx)
    else:
        dx = ratio ** np.arange(nx)
        dx *= L / dx.sum()
    xc = np.cumsum(dx) - 0.5 * dx
    d_face = 0.5 * (dx[:-1] + dx[1:])     # distances between adjacent centres
    return dx, xc, d_face


# ----------------------------------------------------------------------------
# 1. Nonlinear diffusion model, Eqs. 1-6
# ----------------------------------------------------------------------------
class DiffusionSolver:
    """
    Fully implicit, cell-centred finite-volume solution of

        phi_eff dS/dt = d/dx ( Lambda(S) dS/dx ),        0 < x < L

        S(x, 0)  = Si              (Eq. 4)
        S(0, t)  = 1               (Eq. 5, Pc = 0 at the inlet face)
        u_w(L,t) = 0               (Eq. 6, closed outer boundary)

    Interface conductivities use the integral (Kirchhoff) average

        Lambda_(i+1/2) = [Phi(S_(i+1)) - Phi(S_i)] / (S_(i+1) - S_i),

    which handles the degeneracy of Lambda at S = 0 and S = 1 far better than
    a simple arithmetic average, and in particular gives the correct
    (non-zero) influx through the inlet face where kro -> 0.
    """

    def __init__(self, props: Properties, nx: int = 300, grid_ratio: float = 1.0):
        self.p = props
        self.nx = nx
        self.dx, self.x, self.df = make_grid(props.L, nx, grid_ratio)
        self.d_in = 0.5 * self.dx[0]          # centre-to-inlet-face distance
        self.S_bc = 1.0                       # inlet saturation, Eq. 5

    # -- residual and tridiagonal Jacobian ----------------------------------
    def _face_flux(self, S):
        """Water flux at the nx+1 faces (m/s), positive in +x."""
        p = self.p
        Phi = p.Phi(S)
        u = np.zeros(self.nx + 1)
        # inlet face: half-cell distance to the boundary value S = 1
        u[0] = -(Phi[0] - p.Phi(self.S_bc)) / self.d_in
        # interior faces
        u[1:-1] = -(Phi[1:] - Phi[:-1]) / self.df
        # outlet face: no flow (Eq. 6)
        u[-1] = 0.0
        return u

    def _residual(self, S, Sn, dt):
        p = self.p
        u = self._face_flux(S)
        return p.phi_eff * self.dx * (S - Sn) / dt + (u[1:] - u[:-1])

    def _jacobian_banded(self, S, dt):
        """Tridiagonal Jacobian in the banded form expected by solve_banded."""
        p, n = self.p, self.nx
        lam = p.Lambda(S)                     # d(Phi)/dS at the cell centres
        ab = np.zeros((3, n))
        main = p.phi_eff * self.dx / dt
        # inlet face contribution (depends on S_0 only)
        main[0] += lam[0] / self.d_in
        # interior faces
        main[:-1] += lam[:-1] / self.df
        main[1:] += lam[1:] / self.df
        ab[0, 1:] = -lam[1:] / self.df        # upper diagonal, dR_i/dS_(i+1)
        ab[1, :] = main
        ab[2, :-1] = -lam[:-1] / self.df      # lower diagonal, dR_i/dS_(i-1)
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
            # damped update: limit the saturation change per iteration
            step = min(1.0, 0.2 / max(np.max(np.abs(dS)), 1e-30))
            S = np.clip(S + step * dS, 1e-8, 1.0)
        return S, itmax, False

    # -- time loop -----------------------------------------------------------
    def run(self, report_times, dt0=1.0, dt_max=None, growth=1.25, verbose=True,
            n_frames=150):
        """
        March to max(report_times) with adaptive time steps.

        Returns a dict with the saturation profiles at the requested times, the
        recovery history, and `n_frames` intermediate profiles (spaced evenly in
        sqrt(t), which is how this problem actually evolves) for the space-time
        plots.
        """
        p = self.p
        report_times = np.atleast_1d(np.sort(np.asarray(report_times, float)))
        tmax = report_times[-1]
        dt_max = dt_max if dt_max is not None else tmax / 50.0

        S = np.full(self.nx, p.Si)
        S0 = S.copy()
        t, dt, Q = 0.0, dt0, 0.0        # Q = water imbibed per unit area, m
        snaps, hist_t, hist_R = {}, [0.0], [0.0]
        k_rep = 0
        # frame times, evenly spaced in sqrt(t) so the early front is resolved
        frame_times = np.linspace(0.0, np.sqrt(tmax), n_frames + 1)[1:] ** 2
        k_frame = 0
        frames_t, frames_S = [0.0], [S.copy()]

        def recovery(S):
            # fraction of the recoverable oil produced; ultimate value = 1
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
            while k_frame < len(frame_times) and t >= frame_times[k_frame]:
                frames_t.append(t)
                frames_S.append(S.copy())
                k_frame += 1
            hist_t.append(t)
            hist_R.append(recovery(S))
            if k_rep < len(report_times) and abs(t - report_times[k_rep]) < 1e-9:
                snaps[report_times[k_rep]] = S.copy()
                if verbose:
                    print(f"    t = {t/DAY:9.4f} d   recovery = {hist_R[-1]:.4f}")
                k_rep += 1
            dt *= growth if nit <= 4 else 1.0

        u = self._face_flux(S)
        # water imbibed through the inlet vs. water stored in the core
        stored = p.phi_eff * np.sum((S - S0) * self.dx)     # m^3/m^2
        mb_err = (Q - stored) / max(Q, 1e-30)
        return dict(x=self.x, dx=self.dx, snapshots=snaps, t=np.array(hist_t),
                    recovery=np.array(hist_R), S_final=S, flux_final=u,
                    influx=Q, mass_balance_error=mb_err,
                    frames_t=np.array(frames_t), frames_S=np.array(frames_S))


# ----------------------------------------------------------------------------
# 2. Pressure formulation, Eqs. 9-16
# ----------------------------------------------------------------------------
class TwoPhaseSolver:
    """
    Fully implicit, control-volume solution of the two coupled equations

        div( k (kro/mu_o) grad p_o ) = -phi dSw/dt          (Eq. 9)
        div( k (krw/mu_w) grad p_w ) =  phi dSw/dt          (Eq. 10)

    with the countercurrent initial and boundary conditions, Eqs. 11-16:

        p_o = 0,  p_w = -Pc(Swi)          at t = 0
        p_o = p_w = 0                     at x = 0, t > 0   (Eqs. 13, 15)
        q_o = q_w = 0                     at x = L          (Eqs. 14, 16)

    Primary unknowns are (p_o, S) per cell, with p_w = p_o - Pc(S).
    Mobilities are single-point upstream weighted. The Jacobian is built by
    finite differences using a 3-colour scheme (the stencil is tridiagonal),
    which costs six residual evaluations per Newton iteration.
    """

    def __init__(self, props: Properties, nx: int = 300, grid_ratio: float = 1.0):
        self.p = props
        self.nx = nx
        self.dx, self.x, self.df = make_grid(props.L, nx, grid_ratio)

    # -- residuals -----------------------------------------------------------
    def _residuals(self, po, S, Sn, dt):
        p, n = self.p, self.nx
        pw = po - p.Pc(S)
        acc = p.phi_eff * self.dx * (S - Sn) / dt     # water accumulation, m/s

        T = p.k / self.df                             # interior transmissibility
        Tb = p.k / (0.5 * self.dx[0])                 # inlet (half cell)

        # --- interior faces, upstream mobilities
        dpo = po[1:] - po[:-1]
        dpw = pw[1:] - pw[:-1]
        lam_o_f = np.where(dpo > 0.0, p.lam_o(S[1:]), p.lam_o(S[:-1]))
        lam_w_f = np.where(dpw > 0.0, p.lam_w(S[1:]), p.lam_w(S[:-1]))
        qo = T * lam_o_f * dpo                        # oil flux, +x direction
        qw = T * lam_w_f * dpw

        # --- inlet face: boundary state is p_o = p_w = 0, S = 1 (Pc = 0)
        po_b, pw_b, S_b = 0.0, 0.0, 1.0
        lam_o_b = p.lam_o(S_b) if po_b > po[0] else p.lam_o(S[0])
        lam_w_b = p.lam_w(S_b) if pw_b > pw[0] else p.lam_w(S[0])
        qo_in = Tb * lam_o_b * (po_b - po[0])
        qw_in = Tb * lam_w_b * (pw_b - pw[0])

        Fo = np.zeros(n + 1)                          # fluxes at faces, +x
        Fw = np.zeros(n + 1)
        Fo[0], Fw[0] = qo_in, qw_in                   # +x directed influx
        Fo[1:-1], Fw[1:-1] = -qo, -qw
        Fo[-1] = Fw[-1] = 0.0                         # Eqs. 14 and 16

        Rw = acc + (Fw[1:] - Fw[:-1])
        Ro = -acc + (Fo[1:] - Fo[:-1])
        return Ro, Rw

    def _pack(self, po, S):
        v = np.empty(2 * self.nx)
        v[0::2], v[1::2] = po, S
        return v

    def _unpack(self, v):
        return v[0::2].copy(), v[1::2].copy()

    def _newton(self, po, S, Sn, dt, tol=1e-9, itmax=20):
        n = self.nx
        scale = self.p.phi_eff * self.dx.min() / dt
        po, S = po.copy(), S.copy()

        for it in range(itmax):
            Ro, Rw = self._residuals(po, S, Sn, dt)
            R = np.empty(2 * n)
            R[0::2], R[1::2] = Ro, Rw
            if np.max(np.abs(R)) / scale < tol:
                return po, S, it, True

            # --- colored finite-difference Jacobian (tridiagonal stencil)
            rows, cols, vals = [], [], []
            eps_p = 1.0            # Pa
            eps_S = 1e-7
            for var in (0, 1):     # 0 -> p_o, 1 -> S
                eps = eps_p if var == 0 else eps_S
                for color in range(3):
                    cells = np.arange(color, n, 3)
                    po_p, S_p = po.copy(), S.copy()
                    if var == 0:
                        po_p[cells] += eps
                    else:
                        S_p[cells] = np.clip(S_p[cells] + eps, 1e-9, 1.0)
                    Ro_p, Rw_p = self._residuals(po_p, S_p, Sn, dt)
                    dRo = (Ro_p - Ro) / eps
                    dRw = (Rw_p - Rw) / eps
                    for c in cells:
                        for r in (c - 1, c, c + 1):
                            if 0 <= r < n:
                                rows.extend([2 * r, 2 * r + 1])
                                cols.extend([2 * c + var, 2 * c + var])
                                vals.extend([dRo[r], dRw[r]])
            J = csr_matrix((vals, (rows, cols)), shape=(2 * n, 2 * n))
            dv = spsolve(J, -R)
            if not np.all(np.isfinite(dv)):
                return po, S, it, False
            dpo, dS = self._unpack(dv)
            # limit the saturation change per Newton iteration
            w = min(1.0, 0.2 / max(np.max(np.abs(dS)), 1e-30))
            po += w * dpo
            S = np.clip(S + w * dS, 1e-8, 1.0 - 1e-10)
        return po, S, itmax, False

    def run(self, report_times, dt0=0.5, dt_max=None, growth=1.2, verbose=True):
        p = self.p
        report_times = np.atleast_1d(np.sort(np.asarray(report_times, float)))
        tmax = report_times[-1]
        dt_max = dt_max if dt_max is not None else tmax / 100.0

        S = np.full(self.nx, p.Si)
        S0 = S.copy()
        po = np.zeros(self.nx)                       # Eq. 11
        t, dt = 0.0, dt0
        snaps, hist_t, hist_R = {}, [0.0], [0.0]
        k_rep = 0

        while t < tmax - 1e-12:
            dt = min(dt, dt_max, tmax - t)
            if k_rep < len(report_times):
                dt = min(dt, report_times[k_rep] - t)
            po_n, S_n, nit, ok = self._newton(po, S, S, dt)
            if not ok:
                dt *= 0.25
                if dt < 1e-6:
                    raise RuntimeError("time step collapsed in TwoPhaseSolver")
                continue
            po, S, t = po_n, S_n, t + dt
            hist_t.append(t)
            hist_R.append(np.sum((S - S0) * self.dx) / ((1.0 - p.Si) * p.L))
            if k_rep < len(report_times) and abs(t - report_times[k_rep]) < 1e-9:
                snaps[report_times[k_rep]] = dict(S=S.copy(), po=po.copy(),
                                                  pw=po - p.Pc(S))
                if verbose:
                    print(f"    t = {t/DAY:9.4f} d   recovery = {hist_R[-1]:.4f}")
                k_rep += 1
            dt *= growth if nit <= 5 else 1.0

        return dict(x=self.x, snapshots=snaps, t=np.array(hist_t),
                    recovery=np.array(hist_R))


# ----------------------------------------------------------------------------
# 3. McWhorter & Sunada semi-analytical solution (infinite acting)
# ----------------------------------------------------------------------------
class McWhorterSunada:
    """
    Exact solution of Eqs. 1-6 on a semi-infinite domain (Ref. 2 of the paper).

    Water is imbibed as  Q_w(t) = 2 A sqrt(t)  [m^3/m^2], and the saturation
    profile is self-similar, x(S, t) = lambda(S) sqrt(t), with

        F(S) = 1 - int_S^1 (b - S) D(b)/F(b) db
                 / int_Si^1 (b - Si) D(b)/F(b) db,
        A^2  = (phi_eff^2 / 2) int_Si^1 (b - Si) D(b)/F(b) db,
        lambda(S) = (phi_eff / A) int_S^1 D(b)/F(b) db.

    F is obtained by direct (under-relaxed) functional iteration; it converges
    in a few tens of sweeps.
    """

    def __init__(self, props: Properties, npts: int = 4001,
                 itmax: int = 500, omega: float = 0.6, tol: float = 1e-10):
        p = self.p = props
        S = np.linspace(p.Si, 1.0, npts)
        D = p.D(S)
        F = (S - p.Si) / (1.0 - p.Si)                # initial guess

        # D/F is 0/0 at S = Si; the floor below keeps the quadrature finite.
        # D(Si) is ~10 orders of magnitude below max(D), so the contribution of
        # that end of the range is negligible whatever floor is used.
        F_floor = 1e-8

        for it in range(itmax):
            g = D / np.maximum(F, F_floor)
            I0 = _cumtrap(g, S)                      # int_Si^S g db
            I1 = _cumtrap(S * g, S)                  # int_Si^S b g db
            tail0 = I0[-1] - I0                      # int_S^1 g db
            tail1 = I1[-1] - I1                      # int_S^1 b g db
            num = tail1 - S * tail0                  # int_S^1 (b-S) g db
            den = I1[-1] - p.Si * I0[-1]             # int_Si^1 (b-Si) g db
            Fnew = np.clip(1.0 - num / den, 1e-30, 1.0)
            Fnew[0], Fnew[-1] = 1e-30, 1.0
            err = np.max(np.abs(Fnew - F))
            F = (1.0 - omega) * F + omega * Fnew
            if err < tol:
                break

        self.S, self.F, self.iters, self.err = S, F, it + 1, err
        self.A = p.phi_eff * np.sqrt(0.5 * den)      # m/s^0.5
        g = D / np.maximum(F, F_floor)
        I0 = _cumtrap(g, S)
        self.lam = p.phi_eff * (I0[-1] - I0) / self.A   # lambda(S), m/s^0.5

    # -- outputs -------------------------------------------------------------
    def front_position(self, t):
        return self.lam[0] * np.sqrt(t)

    def profile(self, t):
        """Returns (x, S) at time t."""
        return self.lam * np.sqrt(t), self.S

    def cumulative_influx(self, t):
        """Water imbibed per unit area, m^3/m^2."""
        return 2.0 * self.A * np.sqrt(t)

    def recovery(self, t):
        p = self.p
        return self.cumulative_influx(t) / (p.phi_eff * (1.0 - p.Si) * p.L)


def _cumtrap(y, x):
    return np.concatenate(([0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(x))))


# ----------------------------------------------------------------------------
# Plotting - reproduces Figs. 1, 2 and 5 of the paper
# ----------------------------------------------------------------------------
def make_figures(props, diff, ms, two=None, zog=None, times=None, outdir=".",
                 animate=False):
    show_eq8 = zog is not None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    labels = {2 * HOUR: "t = 2 hrs", 1 * DAY: "t = 1 day",
              5 * DAY: "t = 5 days", 40 * DAY: "t = 40 days"}
    times = times or sorted(diff["snapshots"])
    files = []

    # --- Fig. 2: saturation distribution ------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    for i, t in enumerate(times):
        c = f"C{i}"
        ax.plot(diff["x"], diff["snapshots"][t], c, lw=1.6,
                label=labels.get(t, f"t = {t/DAY:g} d") + " (numerical)")
        if ms.front_position(t) < props.L:
            xa, Sa = ms.profile(t)
            ax.plot(xa, Sa, "k--", lw=1.0,
                    label="analytical" if i == 0 else None)
    ax.set(xlabel="Distance from inlet, m", ylabel="Normalized water saturation",
           xlim=(0, props.L), ylim=(0, 1.02),
           title="Fig. 2 - saturation distribution, 1D countercurrent imbibition")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)
    f = os.path.join(outdir, "fig2_saturation.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # --- Fig. 1: oil and water pressure -------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 7.0), sharex=True,
                             gridspec_kw=dict(height_ratios=[1, 1.6]))
    for i, t in enumerate(times):
        S = diff["snapshots"][t]
        po = props.oil_pressure_of_S(S) * PA_TO_PSI
        pw = (props.oil_pressure_of_S(S) - props.Pc(S)) * PA_TO_PSI
        axes[0].plot(diff["x"], po, f"C{i}", lw=1.6, label=labels.get(t, f"{t/DAY:g} d"))
        axes[1].plot(diff["x"], pw, f"C{i}", lw=1.6)
        if two is not None and t in two["snapshots"]:
            sn = two["snapshots"][t]
            axes[0].plot(two["x"], sn["po"] * PA_TO_PSI, "k:", lw=1.0)
            axes[1].plot(two["x"], sn["pw"] * PA_TO_PSI, "k:", lw=1.0)
    axes[0].set(ylabel="Oil pressure, psi",
                title="Fig. 1 - pressures, 1D countercurrent imbibition")
    axes[1].set(xlabel="Distance from inlet, m", ylabel="Water pressure, psi",
                xlim=(0, props.L))
    axes[0].legend(fontsize=8); [a.grid(alpha=0.3) for a in axes]
    if two is not None:
        axes[0].plot([], [], "k:", label="pressure model (Eqs. 9-16)")
        axes[0].legend(fontsize=8)
    f = os.path.join(outdir, "fig1_pressures.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # --- Fig. 5: recovery ---------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    td = diff["t"] / DAY
    ta = np.linspace(1e-4, min(td[-1], 20.0), 400)
    ax.plot(ta, ms.recovery(ta * DAY), "k-", lw=1.4, label="Analytical (M&S)")
    ax.plot(td, diff["recovery"], "C0--", lw=1.8,
            label=f"Diffusion model, {len(diff['x'])} grids")
    if two is not None:
        ax.plot(two["t"] / DAY, two["recovery"], "C3:", lw=2.0,
                label=f"Pressure model, {len(two['x'])} grids")
    if zog is not None:
        ax.plot(zog["t"] / DAY, zog["recovery"], "C2-.", lw=1.6,
                label="Zero oil pressure gradient (Eq. 8)")
    ax.set(xlabel="Time, days", ylabel="Recovery, fraction",
           xlim=(0, td[-1]), ylim=(0, 1.0),
           title="Fig. 5 - recovery, 1D countercurrent imbibition")
    ax.legend(fontsize=9); ax.grid(alpha=0.3)
    f = os.path.join(outdir, "fig5_recovery.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # --- saturation development: coloured core and space-time map -----------
    files += plot_saturation_development(props, diff, times=times, outdir=outdir,
                                         animate=animate)

    # --- the same treatment for the oil and water pressures -----------------
    files += plot_pressure_development(props, diff, times=times, outdir=outdir,
                                       animate=animate)

    # --- and for the recovery factor ----------------------------------------
    files += plot_recovery_development(props, diff, ms=ms, times=times,
                                       outdir=outdir, animate=animate)

    # --- extra: the building blocks of the diffusion coefficient ------------
    files += plot_building_blocks(props, outdir=outdir, show_eq8=show_eq8)
    return files


def plot_saturation_development(props, diff, times=None, outdir=".",
                                cmap="viridis", animate=False):
    """
    Show how the water saturation develops inside the 1D block.

      * core_saturation_strips.png - the core drawn as a coloured bar at each
        reporting time, water entering from the left (x = 0) and oil leaving
        through the same face
      * saturation_map.png - the whole history as a space-time map, x across
        and time up, plus the same data against sqrt(t), where the
        infinite-acting front is a straight line
      * saturation_animation.gif - optional animation of the profile and the
        coloured core (needs `animate=True`)
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    files = []
    L = props.L
    labels = {2 * HOUR: "2 hrs", 1 * DAY: "1 day", 5 * DAY: "5 days",
              40 * DAY: "40 days"}
    times = times or sorted(diff["snapshots"])
    norm = matplotlib.colors.Normalize(vmin=0.0, vmax=1.0)

    # ---------------- 1. the core as a coloured strip -----------------------
    n = len(times)
    fig, axes = plt.subplots(n, 1, figsize=(8.0, 1.15 * n + 1.6))
    axes = np.atleast_1d(axes)
    for a, t in zip(axes, times):
        S = diff["snapshots"][t][None, :]
        a.imshow(S, aspect="auto", cmap=cmap, norm=norm, origin="lower",
                 extent=(0.0, L, 0.0, 1.0), interpolation="nearest")
        a.set_yticks([])
        a.set_ylabel(labels.get(t, f"{t/DAY:g} d"), rotation=0, ha="right",
                     va="center", fontsize=10)
        a.set_xlim(0, L)
        if a is not axes[-1]:
            a.set_xticklabels([])
    axes[-1].set_xlabel("Distance from inlet, m")
    axes[0].set_title("Water saturation in the 1D block\n"
                      "water in / oil out at the left face; right face closed",
                      fontsize=11)
    # arrows marking the countercurrent flow at the open face
    axes[0].annotate("water in", xy=(0.0, 0.5), xytext=(0.10 * L, 0.5),
                     xycoords=("data", "axes fraction"), fontsize=9, color="w",
                     va="center", ha="left",
                     arrowprops=dict(arrowstyle="->", color="w", lw=1.4))
    fig.subplots_adjust(right=0.86)
    cax = fig.add_axes([0.88, 0.12, 0.025, 0.76])
    fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax,
                 label="Normalized water saturation, S")
    f = os.path.join(outdir, "core_saturation_strips.png")
    fig.savefig(f, dpi=150, bbox_inches="tight"); plt.close(fig); files.append(f)

    # ---------------- 2. space-time map -------------------------------------
    tf, Sf = diff["frames_t"], diff["frames_S"]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.8))
    for a, yscale in zip(axes, ("t", "sqrt")):
        y = tf / DAY if yscale == "t" else np.sqrt(tf / DAY)
        im = a.pcolormesh(diff["x"], y, Sf, cmap=cmap, norm=norm,
                          shading="nearest")
        a.set_xlabel("Distance from inlet, m")
        a.set_xlim(0, L)
        if yscale == "t":
            a.set(ylabel="Time, days", title="Saturation history")
        else:
            a.set(ylabel=r"$\sqrt{t}$, days$^{1/2}$",
                  title=r"Same data against $\sqrt{t}$"
                        "\n(front is a straight line while infinite acting)")
        for t in times:
            if t <= tf[-1]:
                yy = t / DAY if yscale == "t" else np.sqrt(t / DAY)
                a.axhline(yy, color="w", lw=0.8, ls=":")
    fig.colorbar(im, ax=axes, label="Normalized water saturation, S",
                 fraction=0.035, pad=0.02)
    f = os.path.join(outdir, "saturation_map.png")
    fig.savefig(f, dpi=150, bbox_inches="tight"); plt.close(fig); files.append(f)

    # ---------------- 3. optional animation ---------------------------------
    if animate:
        from matplotlib.animation import FuncAnimation, PillowWriter
        fig, (a0, a1) = plt.subplots(2, 1, figsize=(7.5, 5.2),
                                     gridspec_kw=dict(height_ratios=[3, 1]))
        line, = a0.plot(diff["x"], Sf[0], "C0", lw=2.0)
        a0.set(xlim=(0, L), ylim=(0, 1.02), ylabel="Normalized water saturation",
               xticklabels=[])
        ttl = a0.set_title("")
        img = a1.imshow(Sf[0][None, :], aspect="auto", cmap=cmap, norm=norm,
                        origin="lower", extent=(0.0, L, 0.0, 1.0),
                        interpolation="nearest")
        a1.set(yticks=[], xlabel="Distance from inlet, m")
        fig.colorbar(img, ax=(a0, a1), label="S", fraction=0.03, pad=0.02)

        def update(i):
            line.set_ydata(Sf[i])
            img.set_data(Sf[i][None, :])
            ttl.set_text(f"t = {tf[i]/DAY:7.2f} days")
            return line, img, ttl

        ani = FuncAnimation(fig, update, frames=len(tf), interval=80, blit=False)
        f = os.path.join(outdir, "saturation_animation.gif")
        ani.save(f, writer=PillowWriter(fps=12), dpi=90)
        plt.close(fig); files.append(f)

    return files


def plot_building_blocks(props, outdir=".", npts=4000, show_eq8=False):
    """
    Plot the factors that make up the diffusion coefficient of Eq. 2,

        D(Sw) = (k/phi) * (kro/mu_o) * f(Sw) * (-dPc/dSw)
                 \\_______/   \\________/   \\____/   \\__________/
                 constant     Eq. 19      Eq. 3      Eq. 20

    Produces three figures:
      * property_functions.png    - kro, krw, f(Sw), Pc and dPc/dSw separately
      * diffusion_decomposition.png - each factor normalised by its own maximum
                                    on a log axis, so that the origin of the
                                    bell shape of D is visible
      * diffusion_coefficient.png - D(Sw) itself, Eq. 2 against Eq. 8
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    files = []
    p = props
    S = np.linspace(1e-4, 1.0 - 1e-9, npts)

    kro, krw = p.kro(S), p.krw(S)
    fw = p.fw(S)                                   # Eq. 3
    dPc = p.dPc_dS(S) * PA_TO_PSI                  # dPc/dSw, psi (negative)
    Pc = p.Pc(S) * PA_TO_PSI                       # Eq. 20, psi
    mob_o = kro / p.mu_o                           # oil mobility, 1/(Pa.s)
    D = p.D(S) * 1e4                               # Eq. 2, cm^2/s
    D8 = (replace(p, model="zero_oil_gradient",
                  _S_tab=None, _Phi_tab=None).D(S) * 1e4 if show_eq8 else None)

    i_pk = int(np.argmax(D))

    # ---------------- 1. the individual property functions ------------------
    fig, ax = plt.subplots(2, 2, figsize=(10.0, 7.5))

    ax[0, 0].plot(S, kro, "C3", lw=1.8, label=r"$k_{ro}=k_{ro}^0(1-S)^{n_o}$")
    ax[0, 0].plot(S, krw, "C0", lw=1.8, label=r"$k_{rw}=k_{rw}^0S^{n_w}$")
    ax[0, 0].set(xlabel="Normalized water saturation, S", ylabel="Relative permeability",
                 title="(a) Relative permeability, Eq. 19", xlim=(0, 1))
    ax[0, 0].legend(fontsize=9)

    ax[0, 1].plot(S, fw, "C2", lw=1.8)
    ax[0, 1].set(xlabel="Normalized water saturation, S", ylabel=r"$f(S_w)$",
                 title=r"(b) Fractional flow $f=1/(1+\frac{k_{ro}}{k_{rw}}\frac{\mu_w}{\mu_o})$,"
                       " Eq. 3", xlim=(0, 1), ylim=(0, 1.02))

    ax[1, 0].plot(S, Pc, "C4", lw=1.8, label=r"$P_c=-B\ln S$")
    ax[1, 0].set(xlabel="Normalized water saturation, S", ylabel=r"$P_c$, psi",
                 title="(c) Capillary pressure, Eq. 20", xlim=(0, 1), ylim=(0, 12))
    ax[1, 0].legend(fontsize=9, loc="upper right")

    ax[1, 1].plot(S, -dPc, "C5", lw=1.8)
    ax[1, 1].set(xlabel="Normalized water saturation, S",
                 ylabel=r"$-\mathrm{d}P_c/\mathrm{d}S_w$, psi",
                 title=r"(d) Capillary pressure gradient $-\mathrm{d}P_c/\mathrm{d}S_w=B/S$",
                 xlim=(0, 1), yscale="log")

    for a in ax.ravel():
        a.grid(alpha=0.3)
    f = os.path.join(outdir, "property_functions.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 2. how the three factors combine ----------------------
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 8.0), sharex=True,
                             gridspec_kw=dict(height_ratios=[1.3, 1]))
    a = axes[0]
    a.plot(S, mob_o / mob_o.max(), "C3", lw=1.8,
           label=r"$k_{ro}/\mu_o$  (falls to 0 at $S=1$)")
    a.plot(S, fw / fw.max(), "C2", lw=1.8,
           label=r"$f(S_w)$  (falls to 0 at $S=0$)")
    a.plot(S, -dPc / (-dPc).max(), "C5", lw=1.8,
           label=r"$-\mathrm{d}P_c/\mathrm{d}S_w$  (diverges as $1/S$)")
    a.plot(S, D / D.max(), "k", lw=2.6, label=r"product $\propto D(S_w)$, Eq. 2")
    a.axvline(S[i_pk], color="0.5", ls=":", lw=1.0)
    a.set(ylabel="factor / its own maximum", yscale="log", ylim=(1e-8, 3),
          title="Building blocks of the diffusion coefficient, Eq. 2")
    a.legend(fontsize=9, loc="lower center")
    a.grid(alpha=0.3, which="both")

    a = axes[1]
    a.plot(S, D, "k", lw=2.0, label="Eq. 2")
    if show_eq8:
        a.plot(S, D8, "C1--", lw=1.8, label="Eq. 8 (oil gradient neglected)")
    a.plot(S[i_pk], D[i_pk], "ko", ms=5)
    a.annotate(f"max D = {D[i_pk]:.2e} cm$^2$/s\nat S = {S[i_pk]:.2f}",
               (S[i_pk], D[i_pk]), textcoords="offset points", xytext=(10, -28),
               fontsize=9)
    a.set(xlabel="Normalized water saturation, S", ylabel=r"$D$, cm$^2$/s",
          xlim=(0, 1), title="Resulting diffusion coefficient")
    a.legend(fontsize=9); a.grid(alpha=0.3)
    f = os.path.join(outdir, "diffusion_decomposition.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 3. D on its own, linear and log -----------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.2))
    for a, scale in zip(axes, ("linear", "log")):
        a.plot(S, D, "C2", lw=1.9, label="Eq. 2")
        if show_eq8:
            a.plot(S, D8, "C1--", lw=1.6, label="Eq. 8")
        a.set(xlabel="Normalized water saturation, S", ylabel=r"$D$, cm$^2$/s",
              xlim=(0, 1), yscale=scale,
              title=f"Capillary diffusion coefficient ({scale} scale)")
        if scale == "log":
            a.set_ylim(D.max() * 1e-6,
                       5 * (max(D.max(), D8.max()) if show_eq8 else D.max()))
        a.grid(alpha=0.3, which="both"); a.legend(fontsize=9)
    f = os.path.join(outdir, "diffusion_coefficient.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 4. relative permeability on its own -------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.3))
    for a, scale in zip(axes, ("linear", "log")):
        a.plot(S, kro, "C3", lw=2.0, label=r"$k_{ro}=k_{ro}^0(1-S)^{n_o}$")
        a.plot(S, krw, "C0", lw=2.0, label=r"$k_{rw}=k_{rw}^0S^{n_w}$")
        a.set(xlabel="Normalized water saturation, S",
              ylabel="Relative permeability", xlim=(0, 1), yscale=scale,
              title=f"Relative permeability, Eq. 19 ({scale} scale)")
        if scale == "log":
            a.set_ylim(1e-6, 1.5)
        else:
            a.set_ylim(0, 0.8)
            a.plot([0, 1], [p.kro0, p.krw0], "k.", ms=8)
            a.annotate(rf"$k_{{ro}}^0$ = {p.kro0},  $n_o$ = {p.no:g}",
                       (0.03, p.kro0), textcoords="offset points",
                       xytext=(6, -2), fontsize=9)
            a.annotate(rf"$k_{{rw}}^0$ = {p.krw0},  $n_w$ = {p.nw:g}",
                       (0.97, p.krw0), ha="right",
                       textcoords="offset points", xytext=(-6, 8), fontsize=9)
        a.grid(alpha=0.3, which="both")
        a.legend(fontsize=9, loc="center" if scale == "linear" else "lower center")
    f = os.path.join(outdir, "relative_permeability.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 5. capillary pressure on its own ----------------------
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.3))
    a = axes[0]
    a.plot(S, Pc, "C4", lw=2.0)
    a.axhline(0.0, color="0.6", lw=0.8)
    a.set(xlabel="Normalized water saturation, S", ylabel=r"$P_c$, psi",
          xlim=(0, 1), ylim=(0, min(Pc.max(), 12.0)),
          title=r"Imbibition capillary pressure $P_c=-B\ln S$, Eq. 20")
    a.annotate(f"B = {p.B*PA_TO_PSI:.2f} psi ({p.B/1e3:.0f} kPa)\n"
               f"$P_c$ = 0 at S = 1 (inlet, Eq. 5)\n"
               f"$P_c$ = {p.Pc(p.Si)*PA_TO_PSI:.1f} psi at $S_i$ = {p.Si:g}",
               (0.32, 0.70), xycoords="axes fraction", fontsize=9)
    a.grid(alpha=0.3)

    a = axes[1]
    a.plot(S, -dPc, "C5", lw=2.0)
    a.set(xlabel="Normalized water saturation, S",
          ylabel=r"$-\mathrm{d}P_c/\mathrm{d}S_w$, psi", xlim=(0, 1),
          yscale="log", title=r"Slope $-\mathrm{d}P_c/\mathrm{d}S_w=B/S$")
    a.grid(alpha=0.3, which="both")
    f = os.path.join(outdir, "capillary_pressure.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 6. the tabulated values -------------------------------
    Sw = p.Swi + p.dS * S
    cols = [("S", S), ("Sw", Sw), ("kro", kro), ("krw", krw), ("f_w", fw),
            ("Pc_psi", Pc), ("dPc_dSw_psi", dPc), ("D_cm2_per_s", D)]
    tab = np.column_stack([c[1] for c in cols])
    f = os.path.join(outdir, "property_data.csv")
    np.savetxt(f, tab[::max(1, npts // 200)], delimiter=",", fmt="%.6e",
               header=",".join(c[0] for c in cols), comments="")
    files.append(f)

    return files


def plot_pressure_development(props, diff, times=None, outdir=".",
                              cmap_o="inferno", cmap_w="cividis",
                              animate=False):
    """
    The same timelapse views for the oil and water pressures.

    For countercurrent flow u_o = -u_w, so dp_o/dS = f_w dPc/dS and both phase
    pressures are unique functions of the local saturation. Every stored
    saturation frame therefore gives a pressure frame at no extra cost:

        p_o(x, t) = p_o(S(x, t)),      p_w = p_o - Pc(S)

    Produces `core_pressure_strips.png`, `pressure_map.png`, and, with
    `animate=True`, `pressure_animation.gif`.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    files = []
    L = props.L
    labels = {2 * HOUR: "2 hrs", 1 * DAY: "1 day", 5 * DAY: "5 days",
              40 * DAY: "40 days"}
    times = times or sorted(diff["snapshots"])

    def pressures(S):
        po = props.oil_pressure_of_S(S) * PA_TO_PSI
        return po, po - props.Pc(S) * PA_TO_PSI

    tf, Sf = diff["frames_t"], diff["frames_S"]
    Po, Pw = pressures(Sf)
    norm_o = matplotlib.colors.Normalize(vmin=0.0, vmax=Po.max())
    norm_w = matplotlib.colors.Normalize(vmin=Pw.min(), vmax=0.0)
    panels = [("Oil pressure, psi", cmap_o, norm_o, 0),
              ("Water pressure, psi", cmap_w, norm_w, 1)]

    # ---------------- 1. the core as coloured strips ------------------------
    n = len(times)
    fig, axes = plt.subplots(n, 2, figsize=(11.5, 1.15 * n + 1.8), squeeze=False)
    for row, t in enumerate(times):
        po_t, pw_t = pressures(diff["snapshots"][t])
        for label, cmap, norm, col in panels:
            a = axes[row, col]
            data = (po_t if col == 0 else pw_t)[None, :]
            a.imshow(data, aspect="auto", cmap=cmap, norm=norm, origin="lower",
                     extent=(0.0, L, 0.0, 1.0), interpolation="nearest")
            a.set_yticks([])
            a.set_xlim(0, L)
            if col == 0:
                a.set_ylabel(labels.get(t, f"{t/DAY:g} d"), rotation=0,
                             ha="right", va="center", fontsize=10)
            if row == 0:
                a.set_title(label, fontsize=11)
            if row != n - 1:
                a.set_xticklabels([])
    for col in (0, 1):
        axes[-1, col].set_xlabel("Distance from inlet, m")
    fig.subplots_adjust(left=0.10, right=0.88, wspace=0.42, hspace=0.25,
                        top=0.86, bottom=0.10)
    for label, cmap, norm, col in panels:
        p0 = axes[0, col].get_position()
        p1 = axes[-1, col].get_position()
        cax = fig.add_axes([p0.x1 + 0.015, p1.y0, 0.014, p0.y1 - p1.y0])
        fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap),
                     cax=cax, label=label)
    fig.suptitle("Phase pressures in the 1D block, countercurrent imbibition",
                 fontsize=12)
    f = os.path.join(outdir, "core_pressure_strips.png")
    fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 2. space-time maps ------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), layout="constrained")
    for label, cmap, norm, col in panels:
        a = axes[col]
        im = a.pcolormesh(diff["x"], tf / DAY, Po if col == 0 else Pw,
                          cmap=cmap, norm=norm, shading="nearest")
        a.set(xlabel="Distance from inlet, m", ylabel="Time, days",
              xlim=(0, L), title=label)
        for t in times:
            if t <= tf[-1]:
                a.axhline(t / DAY, color="w", lw=0.8, ls=":")
        fig.colorbar(im, ax=a, fraction=0.045, pad=0.02, label=label)
    fig.suptitle("Pressure history, countercurrent imbibition", fontsize=12)
    f = os.path.join(outdir, "pressure_map.png")
    fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 3. optional animation ---------------------------------
    if animate:
        from matplotlib.animation import FuncAnimation, PillowWriter
        fig, ax = plt.subplots(2, 1, figsize=(7.5, 6.0), sharex=True)
        lo, = ax[0].plot(diff["x"], Po[0], "C3", lw=2.0)
        lw_, = ax[1].plot(diff["x"], Pw[0], "C0", lw=2.0)
        ax[0].set(xlim=(0, L), ylim=(-0.03 * Po.max(), 1.08 * Po.max()),
                  ylabel="Oil pressure, psi")
        ax[1].set(xlim=(0, L), ylim=(1.08 * Pw.min(), 0.5),
                  ylabel="Water pressure, psi", xlabel="Distance from inlet, m")
        for a in ax:
            a.grid(alpha=0.3)
        ttl = ax[0].set_title("")

        def update(i):
            lo.set_ydata(Po[i])
            lw_.set_ydata(Pw[i])
            ttl.set_text(f"t = {tf[i]/DAY:7.2f} days")
            return lo, lw_, ttl

        ani = FuncAnimation(fig, update, frames=len(tf), interval=80, blit=False)
        f = os.path.join(outdir, "pressure_animation.gif")
        ani.save(f, writer=PillowWriter(fps=12), dpi=90)
        plt.close(fig); files.append(f)

    return files


def plot_recovery_development(props, diff, ms=None, times=None, outdir=".",
                              cmap="viridis", animate=False):
    """
    Timelapse of the recovery factor.

      * recovery_development.png - recovery against t and against sqrt(t), with
        the analytical curve and the reporting times marked. On the sqrt(t) axis
        the infinite-acting solution is a straight line, so the point where the
        computed curve bends away is the moment the front feels the closed outer
        boundary.
      * recovery_animation.gif - optional; the recovery curve building up next
        to the coloured core, so the production and the saturation front can be
        watched together.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    files = []
    L = props.L
    labels = {2 * HOUR: "2 hrs", 1 * DAY: "1 day", 5 * DAY: "5 days",
              40 * DAY: "40 days"}
    times = times or sorted(diff["snapshots"])
    t, R = diff["t"], diff["recovery"]
    tf, Sf = diff["frames_t"], diff["frames_S"]
    Rf = np.interp(tf, t, R)

    # time at which the front reaches the closed face (end of infinite acting)
    t_bnd = (L / ms.lam[0]) ** 2 if ms is not None else None

    # ---------------- 1. static development figure --------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    for a, xs in zip(axes, ("t", "sqrt")):
        x = t / DAY if xs == "t" else np.sqrt(t / DAY)
        a.plot(x, R, "C0", lw=2.0, label="Numerical")
        if ms is not None:
            ta = np.linspace(1e-4 * DAY, t[-1], 500)
            xa = ta / DAY if xs == "t" else np.sqrt(ta / DAY)
            a.plot(xa, ms.recovery(ta), "k--", lw=1.2,
                   label="Analytical (infinite acting)")
            if t_bnd is not None and t_bnd < t[-1]:
                xb = t_bnd / DAY if xs == "t" else np.sqrt(t_bnd / DAY)
                a.axvline(xb, color="C3", lw=1.0, ls=":")
                a.annotate(f"front reaches x = L\nat {t_bnd/DAY:.0f} days",
                           (xb, 0.90), xytext=(6, 0), textcoords="offset points",
                           fontsize=9, color="C3", va="top")
        rows = []
        for tt in times:
            if tt <= t[-1]:
                xx = tt / DAY if xs == "t" else np.sqrt(tt / DAY)
                rr = np.interp(tt, t, R)
                a.plot(xx, rr, "ko", ms=5)
                rows.append(f"{labels.get(tt, f'{tt/DAY:g} d'):>8}   {rr:.3f}")
        a.text(0.035, 0.97, "recovery\n" + "\n".join(rows), va="top",
               ha="left", transform=a.transAxes, fontsize=8.5,
               family="monospace",
               bbox=dict(fc="w", ec="0.7", alpha=0.9, boxstyle="round,pad=0.4"))
        a.set(ylabel="Recovery, fraction of recoverable oil", ylim=(0, 1),
              xlim=(0, x[-1]))
        a.set_xlabel("Time, days" if xs == "t" else r"$\sqrt{t}$, days$^{1/2}$")
        a.set_title("Recovery history" if xs == "t"
                    else r"Against $\sqrt{t}$: straight while infinite acting")
        a.grid(alpha=0.3); a.legend(fontsize=9, loc="lower right")
    f = os.path.join(outdir, "recovery_development.png")
    fig.tight_layout(); fig.savefig(f, dpi=150); plt.close(fig); files.append(f)

    # ---------------- 2. optional animation ---------------------------------
    if animate:
        from matplotlib.animation import FuncAnimation, PillowWriter
        norm = matplotlib.colors.Normalize(vmin=0.0, vmax=1.0)
        fig, (a0, a1) = plt.subplots(2, 1, figsize=(7.5, 5.8),
                                     gridspec_kw=dict(height_ratios=[3, 1],
                                                      hspace=0.45))
        a0.plot(t / DAY, R, color="0.85", lw=1.5)          # final curve, ghosted
        line, = a0.plot([], [], "C0", lw=2.4)
        dot, = a0.plot([], [], "C0o", ms=7)
        a0.set(xlim=(0, t[-1] / DAY), ylim=(0, 1), xlabel="Time, days",
               ylabel="Recovery, fraction")
        a0.grid(alpha=0.3)
        ttl = a0.set_title("")
        img = a1.imshow(Sf[0][None, :], aspect="auto", cmap=cmap, norm=norm,
                        origin="lower", extent=(0.0, L, 0.0, 1.0),
                        interpolation="nearest")
        a1.set(yticks=[], xlabel="Distance from inlet, m")
        fig.colorbar(img, ax=(a0, a1), label="S", fraction=0.03, pad=0.02)

        def update(i):
            line.set_data(tf[:i + 1] / DAY, Rf[:i + 1])
            dot.set_data([tf[i] / DAY], [Rf[i]])
            img.set_data(Sf[i][None, :])
            ttl.set_text(f"t = {tf[i]/DAY:7.2f} days     "
                         f"recovery = {Rf[i]*100:5.1f} %")
            return line, dot, img, ttl

        ani = FuncAnimation(fig, update, frames=len(tf), interval=80, blit=False)
        f = os.path.join(outdir, "recovery_animation.gif")
        ani.save(f, writer=PillowWriter(fps=12), dpi=90)
        plt.close(fig); files.append(f)

    return files


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nx", type=int, default=300, help="gridblocks (paper uses 300)")
    ap.add_argument("--tmax", type=float, default=40.0, help="end time, days")
    ap.add_argument("--nx-twophase", type=int, default=100,
                    help="gridblocks for the pressure model (slower)")
    ap.add_argument("--grid-ratio", type=float, default=1.03,
                    help="geometric cell growth away from the inlet for the "
                         "pressure model (1.0 = uniform, as in the paper)")
    ap.add_argument("--no-twophase", action="store_true",
                    help="skip the p_o/p_w formulation of Eqs. 9-16")
    ap.add_argument("--eq8", action="store_true",
                    help="also run the zero-oil-pressure-gradient case of "
                         "Eq. 8, for comparison (not part of the countercurrent "
                         "formulation itself)")
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--animate", action="store_true",
                    help="also write an animated gif of the saturation profile")
    ap.add_argument("--props-only", action="store_true",
                    help="only plot the property functions and D(Sw); "
                         "do not run any simulation")
    args = ap.parse_args()

    props = Properties()
    print("Base case (Table 1):")
    print(f"  L = {props.L} m, k = {props.k/MD_TO_M2:.1f} md, phi = {props.phi}")
    print(f"  mu_o = mu_w = {props.mu_o/CP_TO_PAS:.1f} cp, B = {props.B*PA_TO_PSI:.2f} psi")
    print(f"  max D = {props.D(np.linspace(1e-4,1,10000)).max()*1e4:.3e} cm^2/s")

    if args.props_only:
        print("\nProperty functions only:")
        for f in plot_building_blocks(props, outdir=args.outdir,
                                      show_eq8=args.eq8):
            print("  " + f)
        return

    report = [t for t in (2 * HOUR, 1 * DAY, 5 * DAY, 40 * DAY) if t <= args.tmax * DAY]
    if not report:
        report = [args.tmax * DAY]

    print("\nSemi-analytical solution (McWhorter & Sunada):")
    ms = McWhorterSunada(props)
    print(f"  converged in {ms.iters} sweeps, residual {ms.err:.2e}")
    print(f"  A = {ms.A:.4e} m/s^0.5,  front = {ms.front_position(DAY)*100:.2f} cm at 1 day")

    print(f"\nDiffusion model (Eqs. 1-6), {args.nx} gridblocks:")
    diff = DiffusionSolver(props, args.nx).run(report)

    two = None
    if not args.no_twophase:
        print(f"\nPressure model (Eqs. 9-16), {args.nx_twophase} gridblocks"
              f", grid ratio {args.grid_ratio}:")
        two = TwoPhaseSolver(props, args.nx_twophase,
                             grid_ratio=args.grid_ratio).run(report)

    zog = None
    if args.eq8:
        print("\nZero oil pressure gradient (Eq. 8):")
        zog = DiffusionSolver(Properties(model="zero_oil_gradient"),
                              args.nx).run(report)

    # --- validation summary --------------------------------------------------
    print("\nRecovery, fraction of recoverable oil:")
    print(f"  {'time':>10} {'analytical':>12} {'diffusion':>12} {'pressure':>12}"
          f" {'Eq. 8':>12}")
    for t in report:
        ra = ms.recovery(t) if ms.front_position(t) < props.L else np.nan
        rd = np.interp(t, diff["t"], diff["recovery"])
        rp = np.interp(t, two["t"], two["recovery"]) if two else np.nan
        rz = np.interp(t, zog["t"], zog["recovery"]) if zog else np.nan
        print(f"  {t/DAY:9.4f}d {ra:12.4f} {rd:12.4f} {rp:12.4f} {rz:12.4f}")

    R = diff["recovery"]
    t_half = np.interp(0.5, R, diff["t"]) / DAY if R[-1] > 0.5 else np.nan
    print(f"\n  material-balance error (diffusion)  = "
          f"{diff['mass_balance_error']:.2e}")
    print(f"  half-recovery time (countercurrent) = {t_half:.1f} days")
    print(f"  oil pressure behind the front       = "
          f"{props.oil_pressure_of_S(props.Si)*PA_TO_PSI:.2f} psi")
    print(f"  water pressure at Si                = "
          f"{props.water_pressure_of_S(props.Si)*PA_TO_PSI:.2f} psi")

    files = make_figures(props, diff, ms, two, zog, times=report,
                         outdir=args.outdir, animate=args.animate)
    print("\nFigures written:")
    for f in files:
        print("  " + f)


if __name__ == "__main__":
    main()