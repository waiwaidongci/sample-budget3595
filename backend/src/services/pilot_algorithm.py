"""单城试投增量：仅用投放前数据拟合对照权重，再在封存权重下估算每日增量区间。

核心口径
- 权重 w_c >= 0，Σw_c = 1，只用投放前逐城日报拟合，封存后不再重配。
- 投放后若某对照城市缺报或串投失效，其权重部分对应点击率未知，按 0 到 1 端点
  给出对照基线与增量的上下界，不把该权重转给其他城市。
- 试验城自身缺报的日期不进入增量汇总，只列为受影响日期。
"""
import math

import numpy as np
from scipy.optimize import minimize

RATE_DIGITS = 6
POINT_DIGITS = 4
WEIGHT_DIGITS = 10
WEIGHT_UNITS = 10 ** WEIGHT_DIGITS


def _rate(row):
    return float(row['clicks']) / float(row['impressions'])


def _key(city, date):
    return (city, date)


def build_pre_panel(daily, treated_city, launch_date):
    """返回可完整覆盖投放前窗口的对照城市列表。

    拟合要求完整面板：只保留在试验城每个投放前日期都有日报的对照城市，
    避免缺报日在拟合阶段被当成零点击。
    """
    index = {_key(r['city'], r['date']): r for r in daily}
    treated_dates = sorted(r['date'] for r in daily if r['city'] == treated_city and r['date'] < launch_date)
    if not treated_dates:
        raise ValueError('投放前没有试验城日报，无法拟合对照权重')
    controls = sorted({r['city'] for r in daily if r['city'] != treated_city and r['date'] < launch_date})
    complete = [c for c in controls if all(_key(c, d) in index for d in treated_dates)]
    incomplete = [c for c in controls if c not in complete]
    if len(complete) < 2:
        detail = '、'.join(incomplete[:8]) if incomplete else '无'
        raise ValueError(
            f'投放前完整覆盖的对照城市不足 2 个（候选 {len(controls)} 个，不完整：{detail}）；'
            '请在封存前补齐各对照城市同一批投放前日期的日报'
        )
    return treated_dates, complete, incomplete, index


def fit_weights(daily, treated_city, launch_date, spillovers=None):
    """在单纯形上最小化投放前逐日点击率残差（按试验城触达量加权）。

    若已登记的串投记录覆盖了某对照城市的投放前窗口，该城不能作为干净对照，
    整个城市排除在外，并记录排除原因；排除发生在封存之前，封存后权重不再重配。
    """
    dates, controls, incomplete, index = build_pre_panel(daily, treated_city, launch_date)
    spill = _spillover_start(spillovers or [])
    contaminated = [c for c in controls if c in spill and spill[c] <= dates[-1]]
    controls = [c for c in controls if c not in contaminated]
    if len(controls) < 2:
        raise ValueError(
            '扣除串投失效后的投放前完整对照城市不足 2 个（失效：'
            + ('、'.join(contaminated) if contaminated else '无')
            + '）；请补充干净的对照城市或在封存前调整口径'
        )
    incomplete = sorted(set(incomplete) | set(contaminated))
    treated = np.array([_rate(index[_key(treated_city, d)]) for d in dates], dtype=float)
    matrix = np.array([[_rate(index[_key(c, d)]) for c in controls] for d in dates], dtype=float)
    impressions = np.array([index[_key(treated_city, d)]['impressions'] for d in dates], dtype=float)
    scale = np.sqrt(impressions)
    design = matrix * scale[:, None]
    target = treated * scale
    k = len(controls)

    def objective(w):
        residual = design @ w - target
        return float(residual @ residual)

    constraints = ({'type': 'eq', 'fun': lambda w: float(np.sum(w) - 1.0)},)
    bounds = [(0.0, 1.0)] * k
    starts = [np.full(k, 1.0 / k)] + [np.eye(k)[i] for i in range(k)]
    best = None
    for start in starts:
        result = minimize(
            objective, start, method='SLSQP', bounds=bounds, constraints=constraints,
            options={'maxiter': 600, 'ftol': 1e-13},
        )
        if not result.success or not np.all(np.isfinite(result.x)):
            continue
        weights = np.clip(np.asarray(result.x, dtype=float), 0.0, None)
        weights[weights < 1e-10] = 0.0
        total = float(weights.sum())
        if total <= 0:
            weights = np.full(k, 1.0 / k)
        else:
            weights = weights / total
        value = objective(weights)
        if best is None or value < best[0]:
            best = (value, weights)

    if best is None:
        raise ValueError('对照权重拟合未收敛，请检查投放前日报是否存在异常值')

    _, weights = best
    fitted = matrix @ weights
    gap = fitted - treated
    rmse = float(math.sqrt(float(np.sum(impressions * gap ** 2)) / float(impressions.sum())))
    max_gap = float(np.max(np.abs(gap))) if len(gap) else 0.0
    if float(np.max(weights)) <= 1e-10:
        raise ValueError('拟合结果没有正权重，请补充投放前对照城市数据')
    # 用 1e-10 个整数单位归一，保证非负且总和严格为 1；低于 1e-9 的数值噪声权重清零。
    floor = 10
    units = [int(round(float(w) * WEIGHT_UNITS)) for w in weights]
    units = [u if u >= floor else 0 for u in units]
    if not any(units):
        units[max(range(len(units)), key=lambda i: float(weights[i]))] = WEIGHT_UNITS
    remainder = WEIGHT_UNITS - sum(units)
    units[max(range(len(units)), key=lambda i: units[i])] += remainder
    weight_map = {}
    for city, unit in sorted(zip(controls, units), key=lambda pair: -pair[1]):
        weight_map[city] = round(unit / WEIGHT_UNITS, WEIGHT_DIGITS)
    if abs(sum(weight_map.values()) - 1.0) > 1e-9 or min(weight_map.values()) < 0:
        raise ValueError('权重归一化失败，请检查投放前数据')
    return {
        'weights': weight_map,
        'controls': controls,
        'excluded_controls': incomplete,
        'pre_dates': dates,
        'pre_start': dates[0],
        'pre_end': dates[-1],
        'metrics': {
            '对照城市数': len(controls),
            '正权重城市数': len([w for w in weight_map.values() if w > 0]),
            '因缺报或串投未纳入城市数': len(incomplete),
            '投放前拟合天数': len(dates),
            '权重合计': round(sum(weight_map.values()), WEIGHT_DIGITS),
            '拟合RMSE(点击率)': round(rmse, RATE_DIGITS),
            '拟合最大偏差(点击率)': round(max_gap, RATE_DIGITS),
        },
        'treated_pre_rate': round(float(np.average(treated, weights=impressions)), RATE_DIGITS),
    }


def _spillover_start(spillovers):
    starts = {}
    for item in spillovers:
        city = item['city']
        date = item['actual_start_date']
        starts[city] = min(starts.get(city, date), date)
    return starts


def compute(snapshot):
    """按封存权重计算投放后每日增量区间与汇总。snapshot 由服务层冻结。"""
    treated_city = snapshot['treated_city']
    launch_date = snapshot['launch_date']
    weights = {city: float(w) for city, w in snapshot['seal']['weights'].items() if float(w) > 0}
    if not weights:
        raise ValueError('封存件中没有正权重城市')
    daily = snapshot['daily']
    spill = _spillover_start(snapshot.get('spillovers') or [])
    index = {_key(r['city'], r['date']): r for r in daily}
    # 只按试验城与封存正权重对照城市的投放后日期展开，避免零权重城市的日子干扰区间。
    post = [
        r for r in daily
        if r['date'] >= launch_date and (r['city'] == treated_city or r['city'] in weights)
    ]
    if not any(r['city'] == treated_city for r in post):
        raise ValueError('投放后尚无试验城日报，无法计算增量')
    dates = sorted({r['date'] for r in post})

    affected = {}
    rows = []
    covered_impressions = 0
    covered_clicks = 0
    covered_rate_weighted = 0.0
    baseline_low_weighted = 0.0
    baseline_high_weighted = 0.0
    max_invalid_weight = 0.0
    treated_missing_days = 0

    for date in dates:
        treated_row = index.get(_key(treated_city, date))
        valid_rate = 0.0
        invalid_weight = 0.0
        day_affected = []
        for city, weight in weights.items():
            row = index.get(_key(city, date))
            if city in spill and date >= spill[city]:
                invalid_weight += weight
                day_affected.append(f'{city}(串投失效)')
                info = affected.setdefault(city, {'city': city, 'reasons': set(), 'dates': []})
                info['reasons'].add('串投失效')
                info['dates'].append(date)
                continue
            if row is None:
                invalid_weight += weight
                day_affected.append(f'{city}(缺报)')
                info = affected.setdefault(city, {'city': city, 'reasons': set(), 'dates': []})
                info['reasons'].add('缺报')
                info['dates'].append(date)
                continue
            valid_rate += weight * _rate(row)

        baseline_low = valid_rate
        baseline_high = valid_rate + invalid_weight
        max_invalid_weight = max(max_invalid_weight, invalid_weight)

        if treated_row is None:
            treated_missing_days += 1
            rows.append([
                date, None, None, None,
                round(baseline_low, RATE_DIGITS), round(baseline_high, RATE_DIGITS),
                None, None, round(invalid_weight, WEIGHT_DIGITS),
                '试验城缺报', '试验城当日无日报，不计入增量汇总',
            ])
            info = affected.setdefault(treated_city, {'city': treated_city, 'reasons': set(), 'dates': []})
            info['reasons'].add('试验城缺报')
            info['dates'].append(date)
            continue

        treated_rate = _rate(treated_row)
        increment_low = (treated_rate - baseline_high) * 100.0
        increment_high = (treated_rate - baseline_low) * 100.0
        impressions = int(treated_row['impressions'])
        covered_impressions += impressions
        covered_clicks += int(treated_row['clicks'])
        covered_rate_weighted += treated_rate * impressions
        baseline_low_weighted += baseline_low * impressions
        baseline_high_weighted += baseline_high * impressions
        note = ''
        if invalid_weight > 0:
            note = '部分对照权重缺报或失效，增量按点击率0–1端点给出区间，权重不重配'
        rows.append([
            date,
            impressions,
            int(treated_row['clicks']),
            round(treated_rate, RATE_DIGITS),
            round(baseline_low, RATE_DIGITS),
            round(baseline_high, RATE_DIGITS),
            round(increment_low, POINT_DIGITS),
            round(increment_high, POINT_DIGITS),
            round(invalid_weight, WEIGHT_DIGITS),
            '、'.join(day_affected) if day_affected else '无',
            note,
        ])

    if covered_impressions <= 0:
        raise ValueError('投放后试验城没有可用日报，无法汇总增量')

    treated_rate = covered_rate_weighted / covered_impressions
    baseline_low = baseline_low_weighted / covered_impressions
    baseline_high = baseline_high_weighted / covered_impressions
    increment_low = (treated_rate - baseline_high) * 100.0
    increment_high = (treated_rate - baseline_low) * 100.0

    affected_list = []
    for city, info in sorted(affected.items()):
        affected_list.append({
            'city': city,
            'reasons': '、'.join(sorted(info['reasons'])),
            'first_date': min(info['dates']),
            'last_date': max(info['dates']),
            'days': len(set(info['dates'])),
            'sealed_weight': round(weights.get(city, 0.0), WEIGHT_DIGITS),
        })

    warnings = []
    if max_invalid_weight > 0:
        warnings.append(
            '投放后存在对照城市缺报或串投失效：受影响权重按点击率0到1的端点计入上下界，'
            '原封存权重不重新分配；区间宽度即这部分权重的不确定性。'
        )
    if treated_missing_days:
        warnings.append(f'试验城有 {treated_missing_days} 天缺报，这些日期不进入增量汇总，仅列示。')
    for city, start in sorted(spill.items()):
        if start < launch_date and city in weights:
            warnings.append(
                f'对照城市 {city} 的实际开始日 {start} 早于投放首日，其投放前数据可能已被串投污染；'
                '按封存口径权重不重配，该城投放后数据自实际开始日起全部失效。'
            )

    metrics = {
        '投放后天数': len([r for r in rows if r[0] >= launch_date]),
        '试验城可用天数': len([r for r in rows if r[3] is not None]),
        '试验城投放后触达': covered_impressions,
        '试验城投放后点击': covered_clicks,
        '试验城投放后点击率': round(treated_rate, RATE_DIGITS),
        '对照基线点击率下界': round(baseline_low, RATE_DIGITS),
        '对照基线点击率上界': round(baseline_high, RATE_DIGITS),
        '增量下界(百分点)': round(increment_low, POINT_DIGITS),
        '增量上界(百分点)': round(increment_high, POINT_DIGITS),
        '单日最大失效权重': round(max_invalid_weight, WEIGHT_DIGITS),
        '受影响城市数': len(affected_list),
        '试验城缺报天数': treated_missing_days,
    }

    columns = [
        '日期', '试验城触达', '试验城点击', '试验城点击率',
        '对照基线下界', '对照基线上界', '增量下界(百分点)', '增量上界(百分点)',
        '失效权重', '受影响城市', '说明',
    ]
    direction = '为正' if increment_low > 0 else ('为负' if increment_high < 0 else '跨越零')
    interpretation = (
        f'投放后试验城可用 {metrics["试验城可用天数"]} 天，点击率 {treated_rate:.3%}；'
        f'封存权重给出的对照基线区间为 {baseline_low:.3%}–{baseline_high:.3%}。'
        f'增量区间 {increment_low:.2f} 至 {increment_high:.2f} 个百分点，结论{direction}；'
        f'区间宽度来自 {len(affected_list)} 个受影响城市的缺报或串投失效权重。'
    )
    caveat = (
        '单城试投无随机对照，增量依赖“对照城市在无投放时与试验城同步变化”的假设；'
        '权重仅用投放前日报拟合并封存，投放后缺报或串投失效的部分按点击率0–1端点给出上下界，'
        '不重新分配权重，因此区间是保守边界而非置信区间。'
    )
    return {
        'metrics': metrics,
        'columns': columns,
        'rows': rows,
        'affected_cities': affected_list,
        'warnings': warnings,
        'caveat': caveat,
        'interpretation': interpretation,
        'post_start': dates[0],
        'post_end': dates[-1],
        'seal_weights': [
            {'city': c, 'weight': round(w, WEIGHT_DIGITS)} for c, w in sorted(weights.items())
        ],
        'input_revision': snapshot.get('revision'),
    }
