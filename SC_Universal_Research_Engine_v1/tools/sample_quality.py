import math
import numpy as np


def _norm_cdf(x):
    """Cumulative distribution function for standard normal distribution using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p):
    """Percent point function (inverse CDF) for standard normal distribution."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    # Rational approximation for central and tail regions (Acklam's algorithm)
    a = [-3.969683028665376e+01, 2.204091104258814e+02, -2.755569477983199e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)


def statistics(counts,blocks=3):
    counts=np.asarray(counts,dtype=np.int64)
    groups=[x for x in np.array_split(counts,min(blocks,len(counts))) if len(x)]
    return dict(trades=int(counts.sum()),active_days=int(np.count_nonzero(counts)),days=len(counts),
                block_trades=[int(x.sum()) for x in groups])


def training_objective(result,config):
    sample=result['sample']
    if result['n']<config['min_trades']:return -1e30
    if sample['active_days']<config.get('min_active_days',0):return -1e30
    if any(n<config.get('min_trades_per_training_block',0) for n in sample['block_trades']):return -1e30
    return result['net']-.75*result['maxdd']


def deflated_sharpe_ratio(sr_observed, sr_trials_std, n_trials, sample_length_t, skew=0.0, kurtosis=3.0):
    """
    Computes the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)
    accounting for multiple testing, skewness, kurtosis, and sample length.
    Returns: float in [0.0, 1.0] representing confidence that true SR > 0.
    """
    if n_trials <= 1 or sample_length_t <= 1:
        return 0.5 if sr_observed > 0 else 0.0

    # Expected maximum Sharpe ratio under the null hypothesis (H0: SR = 0)
    euler_mascheroni = 0.57721566490153286
    z_first = _norm_ppf(1.0 - 1.0 / n_trials) if n_trials > 1 else 0.0
    z_second = _norm_ppf(1.0 - 1.0 / (n_trials * math.e)) if n_trials > 1 else 0.0
    sr0 = sr_trials_std * ((1.0 - euler_mascheroni) * z_first + euler_mascheroni * z_second)

    # Standard error of the observed Sharpe ratio under non-normality
    denom = 1.0 - skew * sr_observed + ((kurtosis - 1.0) / 4.0) * (sr_observed ** 2)
    if denom <= 0.0:
        se_sr = 1.0 / math.sqrt(sample_length_t - 1)
    else:
        se_sr = math.sqrt(denom / (sample_length_t - 1))

    if se_sr <= 1e-12:
        return 1.0 if sr_observed > sr0 else 0.0

    z_stat = (sr_observed - sr0) / se_sr
    return float(_norm_cdf(z_stat))


def benjamini_hochberg_fdr(p_values, q=0.05):
    """
    Applies the Benjamini-Hochberg procedure to control False Discovery Rate at level q.
    Returns: (rejected_mask, corrected_p_values)
    """
    p_values = np.asarray(p_values, dtype=np.float64)
    m = len(p_values)
    if m == 0:
        return np.array([], dtype=bool), np.array([], dtype=np.float64)

    sorted_indices = np.argsort(p_values)
    sorted_p = p_values[sorted_indices]
    
    thresholds = (np.arange(1, m + 1) / m) * q
    below = sorted_p <= thresholds
    
    max_k = -1
    for k in range(m - 1, -1, -1):
        if below[k]:
            max_k = k
            break

    rejected_sorted = np.zeros(m, dtype=bool)
    if max_k >= 0:
        rejected_sorted[:max_k + 1] = True

    rejected = np.zeros(m, dtype=bool)
    rejected[sorted_indices] = rejected_sorted

    cummin_p = np.minimum.accumulate((sorted_p * m / np.arange(1, m + 1))[::-1])[::-1]
    adj_p_sorted = np.clip(cummin_p, 0.0, 1.0)
    adj_p = np.zeros(m, dtype=np.float64)
    adj_p[sorted_indices] = adj_p_sorted

    return rejected, adj_p


def parameter_plateau_score(candidate_params, evaluation_func, step_sizes, min_positive_ratio=0.75):
    """
    Evaluates whether candidate parameters lie on a broad, robust plateau rather than an isolated spike.
    Perturbs each parameter by +/- 1 step.
    Returns: dict(is_robust, positive_ratio, neighbor_count, neighbor_scores)
    """
    scores = []
    keys = list(candidate_params.keys())
    for key in keys:
        if key not in step_sizes or step_sizes[key] == 0:
            continue
        step = step_sizes[key]
        for delta in [-step, step]:
            perturbed = dict(candidate_params)
            perturbed[key] = candidate_params[key] + delta
            try:
                score = evaluation_func(perturbed)
                scores.append(score)
            except Exception:
                scores.append(-1e30)

    if not scores:
        return dict(is_robust=True, positive_ratio=1.0, neighbor_count=0, neighbor_scores=[])

    positive_count = sum(1 for s in scores if s > 0)
    ratio = positive_count / len(scores)
    return dict(
        is_robust=(ratio >= min_positive_ratio),
        positive_ratio=ratio,
        neighbor_count=len(scores),
        neighbor_scores=scores
    )


def evaluation_status(result,config):
    n=config.get('validation_min_trades',30);active=config.get('validation_min_active_days',10)
    sufficient=result['n']>=n and result['sample']['active_days']>=active
    return dict(status='sufficient_for_screening' if sufficient else 'insufficient_sample',
                sufficient=sufficient,minimum_trades=n,minimum_active_days=active,
                observed_trades=result['n'],observed_active_days=result['sample']['active_days'],
                note='Sample-size screen only; not proof of independence, statistical significance or edge.')
