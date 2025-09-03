import math
import numpy as np
from scipy.optimize import fsolve, minimize


# --- NUEVA FUNCIÓN DE INTERPOLACIÓN DE LLUVIA ---
def interpolate_rainfall(target_rp, standard_rps, standard_rains):
    """
    Interpola la precipitación para un periodo de retorno objetivo.

    Utiliza una interpolación lineal sobre la variable reducida de Gumbel para mantener
    la consistencia con el análisis de frecuencia.

    Args:
        target_rp (float): El periodo de retorno para el que se desea la precipitación.
        standard_rps (list): Lista de periodos de retorno estándar disponibles.
        standard_rains (list): Lista de valores de precipitación correspondientes.

    Returns:
        float: El valor de la precipitación interpolada, o None si no se puede calcular.
    """
    if not standard_rps or len(standard_rps) != len(standard_rains) or len(standard_rps) < 2:
        return None  # No hay suficientes datos para interpolar

    # Si el valor ya existe, devolverlo directamente
    if target_rp in standard_rps:
        return standard_rains[standard_rps.index(target_rp)]

    # Usar la variable reducida de Gumbel para la linealización (y = -ln(-ln(P)))
    # P = 1 - 1/T
    try:
        gumbel_variates_x = [-np.log(-np.log(1 - 1/rp)) for rp in standard_rps]
        target_variate_x = -np.log(-np.log(1 - 1/target_rp))
    except (ValueError, ZeroDivisionError):
        return None # Periodo de retorno no válido (ej. T=1)

    # Usar la interpolación lineal de NumPy, que es robusta y eficiente
    # Permite la extrapolación si el target_rp está fuera del rango estándar
    interpolated_rain = np.interp(target_variate_x, gumbel_variates_x, standard_rains)
    
    return float(interpolated_rain)
# --- FIN DE LA NUEVA FUNCIÓN ---


def calculate_rational_method(area_km2, concentration_time_h, i1id, p0, p0_corrector, p0_corrector_rp, rainfall_mm):
    """
    Calculates flow using the modified Rational Method.
    Returns (flow_m3_s, intermediate_variables_dict).
    """
    # Basic validation
    if not all(isinstance(arg, (int, float)) for arg in [area_km2, concentration_time_h, i1id, p0, p0_corrector, p0_corrector_rp, rainfall_mm]):
        raise ValueError("Todos los parámetros de entrada para el Método Racional deben ser numéricos.")
    if area_km2 <= 0 or concentration_time_h <= 0 or i1id <= 0 or p0 < 0 or p0_corrector < 0 or p0_corrector_rp < 0 or rainfall_mm <= 0:
        raise ValueError("Los parámetros de entrada para el Método Racional deben ser positivos (excepto P0, P0_corrector, P0_corrector_RP que pueden ser cero).")

    # Apply area correction to rainfall (from original code)
    # log10(area_km2) can be negative if area_km2 < 1
    if area_km2 < 1:
        area_correction_factor = 1 # No reduction for very small areas, or adjust formula
    else:
        area_correction_factor = 1 - (math.log10(area_km2) / 15.0)
    
    # Ensure factor is not negative
    area_correction_factor = max(0.0, area_correction_factor) 
    
    corrected_rainfall_mm = rainfall_mm * area_correction_factor

    # Calculate Intensity Factor (from original code)
    # Note: Original code has a fixed '28' in the formula.
    # Handle potential division by zero or log(0) if concentration_time_h is too small
    if concentration_time_h <= 0:
        intensity_factor = 0 # Or handle as error
    else:
        try:
            intensity_factor = math.pow(i1id, ((math.pow(28, 0.1) - math.pow(concentration_time_h, 0.1)) / (math.pow(28, 0.1) - 1)))
        except (ValueError, OverflowError): # math domain error for negative base or very large/small numbers
            intensity_factor = 0 # Fallback

    # Calculate Intensity (I)
    intensity_mm_h = corrected_rainfall_mm / 24.0 * intensity_factor

    # Calculate Corrected P0
    corrected_p0_mm = p0 * p0_corrector * p0_corrector_rp
    
    # Handle division by zero for ratio calculation
    if corrected_p0_mm <= 0: # If P0 is zero or negative, runoff coefficient formula might not apply directly
        # This is a critical point. If P0 is 0, all rainfall becomes runoff.
        # The formula ((ratio - 1) * (ratio + 23)) / math.pow(ratio + 11, 2.0)
        # would imply ratio -> infinity if P0 -> 0.
        # For P0=0, C is typically 1.0 (all rainfall becomes runoff).
        runoff_coef = 1.0
    else:
        ratio = corrected_rainfall_mm / corrected_p0_mm
        runoff_coef = ((ratio - 1) * (ratio + 23)) / math.pow(ratio + 11, 2.0)
        runoff_coef = max(0.0, min(1.0, runoff_coef)) # Ensure C is between 0 and 1

    # Calculate Uniformity Coefficient (K)
    uniformity_coef = 1 + (math.pow(concentration_time_h, 1.25) / (math.pow(concentration_time_h, 1.25) + 14))

    # Calculate Flow (Q)
    flow_m3_s = (runoff_coef * intensity_mm_h * area_km2 * uniformity_coef) / 3.6

    intermediate_variables = {
        "Area (A) (km²)": round(area_km2, 3),
        "Tiempo de concentración (h)": round(concentration_time_h, 3),
        "Factor reductor por área": round(area_correction_factor, 3),
        "Precipitación corregida (mm)": round(corrected_rainfall_mm, 2),
        "Factor de intensidad": round(intensity_factor, 2),
        "Factor de torrencialidad (I1/Id)": round(i1id, 2),
        "Intensidad (I) (mm/h)": round(intensity_mm_h, 2),
        "P0 (mm)": round(p0, 2),
        "P0 corregido (mm)": round(corrected_p0_mm, 2),
        "Coeficiente de escorrentía (C)": round(runoff_coef, 3),
        "Coeficiente de uniformidad (K)": round(uniformity_coef, 3)
    }

    return flow_m3_s, intermediate_variables

# --- Curve Fitting and Flow Calculation for Interpolation ---

def get_median_for_plot(return_period):
    """Converts return period to a value suitable for plotting on a Gumbel-like scale."""
    if return_period <= 1: # Avoid log(0) or negative values
        return 0
    return -math.log(math.log(return_period / (return_period - 1)))

def calculate_gev_fit(qs, return_periods):
    """
    Performs GEV curve fitting using scipy.optimize.minimize for robustness.
    qs: list of flow values (Q)
    return_periods: list of corresponding return periods (T)
    Returns (alpha, mu, k) parameters.
    """
    if len(qs) != len(return_periods) or len(qs) < 3: # GEV needs at least 3 points
        raise ValueError("No hay suficientes puntos de datos para el ajuste GEV (se requieren al menos 3).")

    # Convert return periods to probabilities (F)
    fs = np.array([1 - 1.0 / r for r in return_periods])
    qs_arr = np.array(qs)

    # Objective function for least squares fitting
    def objective_function(params):
        alpha, mu, k = params
        if alpha <= 0: return np.inf # Alpha must be positive
        
        # Avoid math domain errors for log(-log(f)) or power
        term = -np.log(fs)
        if np.any(term <= 0): return np.inf # Ensure term is positive for log

        if k == 0: # Gumbel case
            q_pred = mu - alpha * np.log(term)
        else:
            try:
                # Ensure base of power is positive
                base_power = term
                if np.any(base_power <= 0): return np.inf
                q_pred = mu + alpha / k * (1 - np.power(base_power, k))
            except (ValueError, OverflowError):
                return np.inf # Penalize invalid calculations

        diff = q_pred - qs_arr
        return np.sum(diff * diff)

    # Initial guess for parameters
    # Simple heuristic: alpha ~ range/2, mu ~ median, k ~ small negative
    alpha_guess = (np.max(qs_arr) - np.min(qs_arr)) / 2.0
    mu_guess = np.median(qs_arr)
    k_guess = -0.1 # Often negative for GEV in hydrology

    # Ensure initial alpha is positive
    if alpha_guess <= 0: alpha_guess = 0.1

    initial_guess = [alpha_guess, mu_guess, k_guess]

    # Bounds for parameters (optional but can help convergence)
    # alpha > 0, k typically between -0.5 and 0.5, mu can vary
    bounds = ((0.001, None), (None, None), (-0.5, 0.5)) # alpha > 0, k between -0.5 and 0.5

    result = minimize(objective_function, initial_guess, bounds=bounds, method='L-BFGS-B') # or 'Nelder-Mead'

    if not result.success:
        # Fallback to a simpler grid search if optimization fails, or raise error
        print(f"Warning: GEV optimization failed: {result.message}. Attempting grid search fallback.")
        return _gev_grid_search_fallback(qs, return_periods)

    return result.x # Returns (alpha, mu, k)

def _gev_grid_search_fallback(qs, return_periods):
    """Fallback grid search for GEV fitting, replicating original code's approach."""
    fs = np.array([1 - 1.0 / r for r in return_periods])
    qs_arr = np.array(qs)

    min_diff = float('inf')
    best_alpha, best_mu, best_k = 0, 0, 0

    q_range = np.max(qs_arr) - np.min(qs_arr)
    alpha_search_range = np.linspace(0.01, q_range * 0.5, 20) # Fewer points for faster fallback
    mu_search_range = np.linspace(np.min(qs_arr) - q_range * 0.1, np.max(qs_arr) + q_range * 0.1, 20)
    k_search_range = np.linspace(-0.5, 0.0, 10)

    for test_alpha in alpha_search_range:
        for test_mu in mu_search_range:
            for test_k in k_search_range:
                if test_alpha <= 0: continue
                
                term = -np.log(fs)
                if np.any(term <= 0): continue

                if test_k == 0:
                    q_pred = test_mu - test_alpha * np.log(term)
                else:
                    try:
                        base_power = term
                        if np.any(base_power <= 0): continue
                        q_pred = test_mu + test_alpha / test_k * (1 - np.power(base_power, test_k))
                    except (ValueError, OverflowError):
                        continue
                
                current_diff = np.sum((q_pred - qs_arr)**2)
                if current_diff < min_diff:
                    min_diff = current_diff
                    best_alpha, best_mu, best_k = test_alpha, test_mu, test_k
    
    if min_diff == float('inf'):
        raise ValueError("GEV grid search fallback failed to find a valid fit.")
    return (best_alpha, best_mu, best_k)


def get_flow_from_gev(return_period, gev_params):
    """
    Calculates flow from GEV parameters for a given return period.
    gev_params: (alpha, mu, k)
    """
    alpha, mu, k = gev_params
    prob = 1 - 1.0 / return_period
    if prob <= 0 or prob >= 1: # Probability must be (0, 1)
        return 0 # Or raise error

    if k == 0: # Gumbel case
        return mu - alpha * math.log(-math.log(prob))
    else:
        try:
            # Ensure base of power is positive
            base_power = -math.log(prob)
            if base_power <= 0: return 0
            return mu + alpha / k * (1 - math.pow(base_power, k))
        except (ValueError, OverflowError): # Math domain error (e.g., negative base for power)
            return 0 # Or handle as error

def calculate_tcev_fit(qs, return_periods):
    """
    Performs TCEV curve fitting using scipy.optimize.minimize.
    qs: list of flow values (Q)
    return_periods: list of corresponding return periods (T)
    Returns (alpha1, alpha2, lambda1, lambda2) parameters.
    """
    if len(qs) != len(return_periods) or len(qs) < 4: # TCEV needs at least 4 points
        raise ValueError("No hay suficientes puntos de datos para el ajuste TCEV (se requieren al menos 4).")

    fs = np.array([1 - 1.0 / r for r in return_periods])
    qs_arr = np.array(qs)

    # Objective function for least squares fitting
    def objective_function(params):
        alpha1, alpha2, lambda1, lambda2 = params
        if alpha1 <= 0 or alpha2 <= 0 or lambda1 <= 0 or lambda2 <= 0:
            return np.inf # Parameters must be positive

        def _f_tcev_solver_for_fit(val, target_prob):
            try:
                # Use np.clip to prevent overflow in exp
                term1 = np.clip(-val * lambda1, -700, 700)
                term2 = np.clip(-val * lambda2, -700, 700)
                return (
                    np.exp(
                        (-alpha1 * np.exp(term1))
                        - (alpha2 * np.exp(term2))
                    )
                    - target_prob
                )
            except (OverflowError, ValueError):
                return np.inf # Penalize invalid calculations

        diff_sum = 0
        for q_obs, prob in zip(qs_arr, fs):
            try:
                # Use fsolve to find Q_pred for each prob
                q_pred = fsolve(_f_tcev_solver_for_fit, q_obs, args=(prob,))[0]
                diff_sum += (q_pred - q_obs)**2
            except Exception:
                diff_sum += 1e10 # Penalize if solver fails for a point
        return diff_sum

    # Initial guess based on original code's heuristics (simplified)
    # Find indices for the specific return periods used in the original heuristic
    # Assuming standard_return_periods are used for fitting
    try:
        idx_2 = return_periods.index(2) if 2 in return_periods else 0
        idx_10 = return_periods.index(10) if 10 in return_periods else min(2, len(return_periods) - 1)
        idx_100 = return_periods.index(100) if 100 in return_periods else max(0, len(return_periods) - 2)
        idx_500 = return_periods.index(500) if 500 in return_periods else len(return_periods) - 1
    except ValueError:
        # Fallback if specific RPs are not in the list
        idx_2, idx_10, idx_100, idx_500 = 0, min(2, len(return_periods)-1), max(0, len(return_periods)-2), len(return_periods)-1
        if len(return_periods) < 4: # Need at least 4 points for a reasonable guess
            raise ValueError("Not enough points for TCEV initial guess heuristic.")

    # Ensure indices are valid
    idx_2, idx_10, idx_100, idx_500 = int(idx_2), int(idx_10), int(idx_100), int(idx_500)

    # Avoid division by zero if flows are identical
    q_diff1 = qs_arr[idx_10] - qs_arr[idx_2]
    q_diff2 = qs_arr[idx_500] - qs_arr[idx_100]

    t1_guess = ((math.log(-math.log(fs[idx_2]))) - (math.log(-math.log(fs[idx_10])))) / q_diff1 if q_diff1 != 0 else 0.1
    alpha1_guess = -(math.log(fs[idx_2])) / (math.exp((-qs_arr[idx_2] * t1_guess))) if t1_guess != 0 else 1.0

    t2_guess = ((math.log(-math.log(fs[idx_100]))) - (math.log(-math.log(fs[idx_500])))) / q_diff2 if q_diff2 != 0 else 0.01
    alpha2_guess = -(math.log(fs[idx_100])) / (math.exp((-qs_arr[idx_100] * t2_guess))) if t2_guess != 0 else 0.1

    # Ensure guesses are positive
    initial_guess = [max(0.001, alpha1_guess), max(0.001, alpha2_guess), max(0.001, t1_guess), max(0.001, t2_guess)]

    # Bounds for parameters (all must be positive)
    bounds = ((0.001, None), (0.001, None), (0.001, None), (0.001, None))

    result = minimize(objective_function, initial_guess, bounds=bounds, method='L-BFGS-B') # or 'Nelder-Mead'

    if not result.success:
        # Fallback to grid search if optimization fails
        print(f"Warning: TCEV optimization failed: {result.message}. Attempting grid search fallback.")
        return _tcev_grid_search_fallback(qs, return_periods)

    return result.x # Returns (alpha1, alpha2, lambda1, lambda2)

def _tcev_grid_search_fallback(qs, return_periods):
    """Fallback grid search for TCEV fitting, replicating original code's approach."""
    fs = np.array([1 - 1.0 / r for r in return_periods])
    qs_arr = np.array(qs)

    N = 5 # Reduced N for faster fallback
    N2 = N * 2

    # Initial guesses (simplified, might need more robust logic)
    t1_val = 0.1
    alpha1_val = 10
    t2_val = 0.01
    alpha2_val = 1

    minLam1 = t1_val * 0.5
    maxLam1 = t1_val * 1.5
    minA1 = alpha1_val * 0.5
    maxA1 = alpha1_val * 1.5

    minLam2 = t2_val * 0.5
    maxLam2 = t2_val * 1.5
    minA2 = alpha2_val * 0.5
    maxA2 = alpha2_val * 1.5

    minsqdif = float('inf')
    fitted_params = [0, 0, 0, 0]

    difA1 = (maxA1 - minA1) / N2
    difA2 = (maxA2 - minA2) / N2
    difLam1 = (maxLam1 - minLam1) / N2
    difLam2 = (maxLam2 - minLam2) / N2

    for n1 in range(N2):
        for n2 in range(N2):
            for n3 in range(N2):
                for n4 in range(N2):
                    a1 = minA1 + n1 * difA1
                    a2 = minA2 + n2 * difA2
                    lam1 = minLam1 + n3 * difLam1
                    lam2 = minLam2 + n4 * difLam2
                    
                    if a1 <= 0 or a2 <= 0 or lam1 <= 0 or lam2 <= 0:
                        continue

                    sqdif = _tcev_sqdif_helper(qs_arr, fs, a1, a2, lam1, lam2)
                    if sqdif < minsqdif:
                        minsqdif = sqdif
                        fitted_params = [a1, a2, lam1, lam2]
    
    if minsqdif == float('inf'):
        raise ValueError("TCEV grid search fallback failed to find a valid fit.")
    return fitted_params

def _tcev_sqdif_helper(qs_arr, fs_arr, a1, a2, lam1, lam2):
    """Helper for TCEV fitting: calculates sum of squared differences."""
    difsum = 0
    for q_obs, prob in zip(qs_arr, fs_arr):
        def _f_tcev_solver(val):
            try:
                term1 = np.clip(-val * lam1, -700, 700)
                term2 = np.clip(-val * lam2, -700, 700)
                return (
                    math.exp(
                        (-a1 * math.exp(term1))
                        - (a2 * math.exp(term2))
                    )
                    - prob
                )
            except (OverflowError, ValueError):
                return 1e10 # Penalize invalid calculations

        try:
            q_pred = fsolve(_f_tcev_solver, q_obs)[0]
        except Exception:
            q_pred = 1000000 # Penalize if solver fails
        
        difsum += (q_pred - q_obs) * (q_pred - q_obs)
    return difsum


def get_flow_from_tcev(return_period, tcev_params):
    """
    Calculates flow from TCEV parameters for a given return period.
    tcev_params: (alpha1, alpha2, lambda1, lambda2)
    """
    alpha1, alpha2, lambda1, lambda2 = tcev_params
    prob = 1 - 1.0 / return_period
    if prob <= 0 or prob >= 1:
        return 0

    def _f_tcev_solver(val):
        try:
            term1 = np.clip(-val * lambda1, -700, 700)
            term2 = np.clip(-val * lambda2, -700, 700)
            return (
                math.exp(
                    (-alpha1 * math.exp(term1))
                    - (alpha2 * math.exp(term2))
                )
                - prob
            )
        except (OverflowError, ValueError):
            return 1e10 # Return a large value to push solver away

    try:
        # Initial guess for fsolve, can be refined based on return_period range
        initial_guess = 75 # Default from original code
        if return_period > 100: initial_guess = 150
        if return_period > 250: initial_guess = 300
        if return_period > 400: initial_guess = 400

        flow = fsolve(_f_tcev_solver, initial_guess)[0]
        return flow
    except Exception:
        return 0 # Return 0 or handle error if solver fails
