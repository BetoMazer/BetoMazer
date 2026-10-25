"""Modelo de projeção do 2º turno a partir da apuração parcial.

Ideia central
-------------
Cada município j entra com o seu "vetor" do 1º turno (votos de A, B, de cada
terceiro, brancos, nulos, abstenção) e com o histórico de 2018/2022. A partir
dele calculamos uma linha de base para o 2º turno:

    s0_j = (A1 + Σ_k a_k · T_k) / (A1 + B1 + Σ_k T_k)

em que a_k é a fração dos eleitores do terceiro k que vai para A (prior em
config.PRIOR_TRANSFERENCIA). Conforme as urnas chegam, medimos em cada
município apurado o desvio em relação a essa base (escala logit):

    r_i = logit(y_i) - logit(s0_i),   y_i = A / (A + B) apurado

e aprendemos como esse desvio depende do perfil do município (fatia de cada
terceiro, força de A no 1º turno, swing entre turnos em 2018/2022, região, UF,
tamanho...). É uma regressão bayesiana com priors encolhendo tudo para zero:
com poucas urnas o modelo aplica um swing quase uniforme; com mais dados ele
passa a diferenciar perfis. Se as zonas apuradas votam como no 1º turno, o
desvio fica perto de zero e a projeção segue o 1º turno; se votam diferente,
o vetor de desvio aprendido é aplicado às zonas ainda não apuradas que têm
perfil parecido.

O mesmo mecanismo projeta o comparecimento (razão entre votos válidos dos
finalistas no 2º turno e votos válidos do 1º turno), que define o peso de
cada município ainda não apurado.

A incerteza vem de simulação Monte Carlo: incerteza dos coeficientes,
ruído idiossincrático por município, e um termo sistemático comum a todo o
voto não apurado (o risco de quem falta apurar ser diferente de quem já foi
apurado de um jeito que o perfil não captura) que decai com a cobertura.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import FINALISTAS, PRIOR_TRANSFERENCIA, PROCESSED, TERCEIROS


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def expit(x):
    return 1 / (1 + np.exp(-x))


@dataclass
class Parametros:
    # desvios-padrão a priori (escala logit para a fatia de A)
    sd_intercepto: float = 0.20
    sd_feature: float = 0.05
    sd_regiao: float = 0.06
    sd_uf: float = 0.06
    tau0: float = 0.08          # ruído idiossincrático por município (prior)
    kappa: float = 0.08         # viés de apuração parcial dentro do município
    sd_sistematico: float = 0.03  # viés comum do não apurado (cobertura zero)
    # comparecimento (log da razão válidos 2º turno / válidos 1º turno)
    sd_intercepto_t: float = 0.06
    sd_feature_t: float = 0.02
    sd_regiao_t: float = 0.02
    sd_uf_t: float = 0.02
    tau0_t: float = 0.05
    kappa_t: float = 0.05
    sd_sistematico_t: float = 0.015
    k_tau: float = 30.0         # peso (em municípios) do prior de tau


FEATURES_BASE = ["lA1", "bn1", "abst1", "swing_prev", "trend_prev", "log_aptos", "turnout_prev"]


def carregar_painel():
    return pd.read_parquet(PROCESSED / "municipio.parquet")


class Modelo:
    def __init__(self, ano, painel=None, params=None, prior=None, alvo_prior=None):
        self.ano = ano
        self.p = params or Parametros()
        painel = carregar_painel() if painel is None else painel
        self.prior = dict(PRIOR_TRANSFERENCIA[ano] if prior is None else prior)
        self._montar_base(painel)
        if alvo_prior is not None:
            self.calibrar_prior(alvo_prior)

    def calibrar_prior(self, alvo):
        """Desloca a linha de base (uniformemente, em logit) para que, sem
        nenhuma urna apurada, a projeção nacional de A seja `alvo` (0..1) —
        ex.: a média das últimas pesquisas. Só afeta o início da apuração."""
        lo, hi = -1.0, 1.0
        base = logit(self.s0)
        for _ in range(60):
            c = (lo + hi) / 2
            if np.average(expit(base + c), weights=self.V1) < alvo:
                lo = c
            else:
                hi = c
        self.s0 = expit(base + c)
        return c

    # ------------------------------------------------------------------ base
    def _montar_base(self, painel):
        y, prev = self.ano, self.ano - 4
        t1 = f"{y}t1_"
        terc = list(TERCEIROS[y].values()) + ["outros"]
        b = painel[painel[t1 + "validos"].fillna(0) > 0].copy()
        b = b.set_index(["uf", "cd_mun"]).sort_index()
        V1 = b[t1 + "validos"].astype(float)
        A1, B1 = b[t1 + "A"].astype(float), b[t1 + "B"].astype(float)
        T = b[[t1 + k for k in terc]].fillna(0).astype(float)
        T.columns = terc
        a = np.array([self.prior[k] for k in terc])
        num = A1 + T.to_numpy() @ a
        self.s0 = ((num + 0.5) / (A1 + B1 + T.sum(axis=1) + 1)).to_numpy()
        self.V1 = V1.to_numpy()
        self.idx = b.index
        self.uf = b.index.get_level_values("uf").to_numpy()
        self.regiao = b.regiao.fillna("Exterior").to_numpy()

        f = pd.DataFrame(index=b.index)
        for k in terc:
            f["t_" + k] = T[k] / V1
        f["lA1"] = logit((A1 + .5) / (A1 + B1 + 1))
        f["bn1"] = (b[t1 + "brancos"] + b[t1 + "nulos"]) / b[t1 + "comparecimento"]
        f["abst1"] = 1 - b[t1 + "comparecimento"] / b[t1 + "aptos"]
        p1, p2 = f"{prev}t1_", f"{prev}t2_"
        if p2 + "A" in b:
            s1p = (b[p1 + "A"] + .5) / (b[p1 + "A"] + b[p1 + "B"] + 1)
            s2p = (b[p2 + "A"] + .5) / (b[p2 + "A"] + b[p2 + "B"] + 1)
            f["swing_prev"] = logit(s2p) - logit(s1p)
            f["trend_prev"] = logit(s2p) - f["lA1"]
            f["turnout_prev"] = np.log((b[p2 + "A"] + b[p2 + "B"] + 1) / (b[p1 + "validos"] + 1))
        else:
            f["swing_prev"] = f["trend_prev"] = f["turnout_prev"] = np.nan
        f["log_aptos"] = np.log(b[t1 + "aptos"])
        f = f.replace([np.inf, -np.inf], np.nan)
        w = V1 / V1.sum()
        cont = ["t_" + k for k in terc] + FEATURES_BASE
        for c in cont:
            m = np.nansum(w * f[c])
            f[c] = f[c].fillna(m)
            sd = np.sqrt(np.nansum(w * (f[c] - m) ** 2)) or 1.0
            f[c] = (f[c] - m) / sd
        self.features = f
        reg = pd.get_dummies(self.regiao).astype(float)
        ufd = pd.get_dummies(self.uf).astype(float)
        X = np.hstack([np.ones((len(f), 1)), f[cont].to_numpy(), reg.to_numpy(), ufd.to_numpy()])
        self.X = X
        self.colunas = ["intercepto"] + cont + ["reg_" + r for r in reg.columns] + ["uf_" + u for u in ufd.columns]
        nc, nr, nu = len(cont), reg.shape[1], ufd.shape[1]
        self.nc = nc
        p = self.p
        self.prior_sd = np.r_[p.sd_intercepto, np.full(nc, p.sd_feature), np.full(nr, p.sd_regiao), np.full(nu, p.sd_uf)]
        self.prior_sd_t = np.r_[p.sd_intercepto_t, np.full(nc, p.sd_feature_t), np.full(nr, p.sd_regiao_t), np.full(nu, p.sd_uf_t)]
        # linha de base do comparecimento: razão observada na eleição anterior
        # (média nacional), pois a do município é usada como feature
        if p2 + "A" in b:
            r = (b[p2 + "A"] + b[p2 + "B"]).sum() / b[p1 + "validos"].sum()
            self.rho0 = float(np.log(r))
        else:
            self.rho0 = 0.0

    # ------------------------------------------------------------- ajuste
    def _alinhar(self, obs):
        """obs: DataFrame indexado por (uf, cd_mun) com A, B, pi (0..1)."""
        o = pd.DataFrame(0.0, index=self.idx, columns=["A", "B", "pi"])
        if obs is not None and len(obs):
            o = o[[]].join(obs[["A", "B", "pi"]])
        o = o.fillna(0.0).astype(float)
        o["pi"] = o.pi.clip(0, 1)
        return o

    @staticmethod
    def _bayes(X, r, var_obs, tau2, prior_sd):
        w = 1.0 / (var_obs + tau2)
        P = 1.0 / prior_sd ** 2
        A = (X * w[:, None]).T @ X + np.diag(P)
        bvec = (X * w[:, None]).T @ r
        L = np.linalg.cholesky(A)
        theta = np.linalg.solve(A, bvec)
        return theta, L

    def _estimar(self, r, var_obs, mask, tau0, prior_sd):
        X = self.X[mask]
        tau2 = tau0 ** 2
        for _ in range(3):
            theta, L = self._bayes(X, r, var_obs, tau2, prior_sd)
            e = r - X @ theta
            w = 1.0 / (var_obs + tau2)
            est = np.sum(w * (e ** 2 - var_obs)) / np.sum(w)
            n = mask.sum()
            tau2 = max((self.p.k_tau * tau0 ** 2 + n * max(est, 0.0)) / (self.p.k_tau + n), 1e-4)
        return theta, L, tau2

    def ajustar(self, obs):
        o = self._alinhar(obs)
        self.obs = o
        n = (o.A + o.B).to_numpy()
        pi = o.pi.to_numpy()
        mask = (n >= 20) & (pi > 0)
        self.mask = mask
        y = (o.A.to_numpy() + .5) / (n + 1)
        r = logit(y) - logit(self.s0)
        var_s = 1.0 / ((n + 1) * y * (1 - y)) + self.p.kappa ** 2 * (1 - pi)
        rt = np.log((n + 1) / (self.V1 * np.maximum(pi, 1e-9) + 1))
        var_t = 1.0 / (n + 1) + self.p.kappa_t ** 2 * (1 - pi)
        self.r, self.var_s, self.rt, self.var_t = r, var_s, rt - self.rho0, var_t
        if mask.sum() == 0:
            k = self.X.shape[1]
            self.theta, self.L, self.tau2 = np.zeros(k), np.diag(1 / self.prior_sd), self.p.tau0 ** 2
            self.phi, self.Lt, self.tau2_t = np.zeros(k), np.diag(1 / self.prior_sd_t), self.p.tau0_t ** 2
        else:
            self.theta, self.L, self.tau2 = self._estimar(r[mask], var_s[mask], mask, self.p.tau0, self.prior_sd)
            self.phi, self.Lt, self.tau2_t = self._estimar(self.rt[mask], var_t[mask], mask, self.p.tau0_t, self.prior_sd_t)
        return self

    # ---------------------------------------------------------- projeção
    def _x_sem_extrapolar(self, q=0.0):
        """Trunca as features contínuas à faixa observada nos municípios já
        apurados: o efeito aprendido num perfil não é extrapolado linearmente
        para perfis que ainda não apareceram na apuração (ex.: só o Nordeste
        apurado não deve ditar o swing do Sul)."""
        Xp = self.X.copy()
        if self.mask.sum() < 5:
            return Xp
        cols = slice(1, 1 + self.nc)
        obs = self.X[self.mask, cols]
        lo, hi = np.quantile(obs, q, axis=0), np.quantile(obs, 1 - q, axis=0)
        Xp[:, cols] = np.clip(Xp[:, cols], lo, hi)
        return Xp

    def _sorteio(self, theta, L, n_sim, rng):
        z = rng.standard_normal((len(theta), n_sim))
        return theta[:, None] + np.linalg.solve(L.T, z)  # cov = (L L^T)^-1

    def projetar(self, obs=None, n_sim=2000, seed=0, detalhe=False):
        if obs is not None or not hasattr(self, "obs"):
            self.ajustar(obs)
        rng = np.random.default_rng(seed)
        o, m = self.obs, self.mask
        pi = o.pi.to_numpy()
        A_obs, B_obs = o.A.to_numpy(), o.B.to_numpy()

        th = self._sorteio(self.theta, self.L, n_sim, rng)       # k x S
        ph = self._sorteio(self.phi, self.Lt, n_sim, rng)
        Xp = self._x_sem_extrapolar()
        mu_s = Xp @ th                                           # J x S
        mu_t = Xp @ ph

        # efeito próprio do município: posterior dado o que já foi apurado nele
        g_s = np.where(m, self.tau2 / (self.tau2 + self.var_s), 0.0)
        g_t = np.where(m, self.tau2_t / (self.tau2_t + self.var_t), 0.0)
        u_s = g_s[:, None] * (self.r[:, None] - mu_s) + np.sqrt(self.tau2 * (1 - g_s))[:, None] * rng.standard_normal(mu_s.shape)
        u_t = g_t[:, None] * (self.rt[:, None] - mu_t) + np.sqrt(self.tau2_t * (1 - g_t))[:, None] * rng.standard_normal(mu_t.shape)

        # cobertura: fração do eleitorado já apurada
        cob = float(np.sum(self.V1 * pi) / np.sum(self.V1))
        # o efeito no total nacional já é proporcional ao que falta apurar
        e_s = rng.standard_normal(n_sim) * self.p.sd_sistematico
        e_t = rng.standard_normal(n_sim) * self.p.sd_sistematico_t

        share = expit(logit(self.s0)[:, None] + mu_s + u_s + e_s[None, :])
        resto = (self.V1 * (1 - pi))[:, None] * np.exp(self.rho0 + mu_t + u_t + e_t[None, :])
        A_tot = A_obs.sum() + (resto * share).sum(axis=0)
        B_tot = B_obs.sum() + (resto * (1 - share)).sum(axis=0)
        pA = A_tot / (A_tot + B_tot)

        apurado = A_obs.sum() + B_obs.sum()
        res = {
            "pct_apurado_votos": 100 * apurado / max(np.mean(A_tot + B_tot), 1),
            "cobertura_eleitorado": 100 * cob,
            "municipios_com_dados": int((pi > 0).sum()),
            "municipios_completos": int((pi >= 0.999).sum()),
            "parcial_A": 100 * A_obs.sum() / max(apurado, 1),
            "A": 100 * float(np.mean(pA)),
            "B": 100 * float(1 - np.mean(pA)),
            "A_ic90": tuple(100 * np.quantile(pA, [.05, .95])),
            "A_ic95": tuple(100 * np.quantile(pA, [.025, .975])),
            "prob_A": float(np.mean(pA > .5)),
            "validos_proj": float(np.mean(A_tot + B_tot)),
            "tau": float(np.sqrt(self.tau2)),
            "swing_medio": float(np.average(mu_s.mean(axis=1), weights=self.V1)),
        }
        if detalhe:
            d = pd.DataFrame(index=self.idx)
            d["regiao"] = self.regiao
            d["pi"] = pi
            d["base_1t_A"] = 100 * self.s0
            d["proj_A"] = 100 * share.mean(axis=1)
            d["desvio_logit"] = (mu_s + u_s).mean(axis=1)
            d["validos_proj"] = A_obs + B_obs + resto.mean(axis=1)
            d["A_proj_votos"] = A_obs + (resto * share).mean(axis=1)
            res["municipios"] = d
            res["sims_A"] = pA
            # chance de A vencer em cada UF, nas mesmas simulações
            ufs, inv = np.unique(self.uf, return_inverse=True)
            Au = np.zeros((len(ufs), n_sim)); Vu = np.zeros((len(ufs), n_sim))
            np.add.at(Au, inv, A_obs[:, None] + resto * share)
            np.add.at(Vu, inv, (A_obs + B_obs)[:, None] + resto)
            res["prob_A_uf"] = dict(zip(ufs, (Au / np.maximum(Vu, 1) > 0.5).mean(axis=1)))
        return res

    def coeficientes(self):
        sd = np.sqrt(np.diag(np.linalg.inv(self.L @ self.L.T)))
        return pd.DataFrame({"coef": self.theta, "sd": sd}, index=self.colunas)

    def resumo_por(self, res, nivel="regiao"):
        d = res["municipios"]
        g = d.groupby(nivel if nivel == "regiao" else "uf")[["validos_proj", "A_proj_votos"]].sum()
        g["A_pct"] = 100 * g.A_proj_votos / g.validos_proj
        g["B_pct"] = 100 - g.A_pct
        g["peso_pct"] = 100 * g.validos_proj / g.validos_proj.sum()
        return g


def nomes(ano):
    f = FINALISTAS[ano]
    return f["nome_A"], f["nome_B"]
