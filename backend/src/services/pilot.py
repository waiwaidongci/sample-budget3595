import csv
import io
from fastapi import HTTPException
from sqlalchemy import select
from redis import Redis
import os
from src.models.pilot import PilotPlan, PilotDaily, PilotSeal, PilotSpillover, PilotRun
from src.services import pilot_algorithm
from src.services.audits import log
from src.utils.serializers import record, now, checksum

QUEUE = 'pilot-queue'


def _lock_plan(db, plan_id):
    """串行化同一计划的封存、日报与更正，避免封存与投放后数据并发越序。"""
    plan = db.scalar(select(PilotPlan).where(PilotPlan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(404, '试投计划不存在')
    return plan


def _plan_or_404(db, plan_id):
    plan = db.get(PilotPlan, plan_id)
    if not plan:
        raise HTTPException(404, '试投计划不存在')
    return plan


def _daily(db, plan_id):
    return [record(x) for x in db.scalars(
        select(PilotDaily).where(PilotDaily.plan_id == plan_id).order_by(PilotDaily.city, PilotDaily.date)
    )]


def _spillovers(db, plan_id):
    return [record(x) for x in db.scalars(
        select(PilotSpillover).where(PilotSpillover.plan_id == plan_id).order_by(PilotSpillover.id)
    )]


def _seal(db, plan_id):
    return db.scalar(select(PilotSeal).where(PilotSeal.plan_id == plan_id))


def _supersede(db, plan, reason):
    """版本前进后，基于旧快照的运行不再作为当前结论，但全部保留可查。

    已完成的结果立即标为 superseded。仍在排队或计算的运行只先打上原因，
    让 worker 算完后把结果一并留档再标 superseded，避免丢失这段历史。
    """
    runs = db.scalars(select(PilotRun).where(
        PilotRun.plan_id == plan.id, PilotRun.input_revision < plan.revision,
    ))
    for run in runs:
        if run.status == 'failed':
            continue
        run.superseded_reason = reason
        if run.status in ('queued', 'running'):
            run.superseded_at = now()
            continue
        run.status = 'superseded'
        run.superseded_at = now()


def _advance(db, plan, user, action, detail):
    """封存后的每次数据变动都推进版本，使在途或已完成结果自动退为历史。

    封存前没有可失效的结果（也无法提交核算），只记录审计，避免版本号无意义膨胀。
    """
    if plan.sealed_at:
        plan.revision = (plan.revision or 1) + 1
        _supersede(db, plan, f'输入已变更至版本 {plan.revision}（新增或更正），此结果基于旧快照，不得作为当前结论')
    log(db, user, action, detail)


def _run_record(db, run, plan=None):
    data = record(run)
    plan = plan or db.get(PilotPlan, run.plan_id)
    data['is_current'] = bool(run.status == 'completed' and plan and plan.revision == run.input_revision)
    data['current_revision'] = plan.revision if plan else None
    data['superseded'] = run.status == 'superseded'
    return data


def list_plans(db):
    plans = []
    for plan in db.scalars(select(PilotPlan).order_by(PilotPlan.id)):
        seal = _seal(db, plan.id)
        current_run = db.scalar(select(PilotRun).where(
            PilotRun.plan_id == plan.id, PilotRun.status == 'completed',
            PilotRun.input_revision == plan.revision,
        ).order_by(PilotRun.id.desc()))
        plans.append({
            **record(plan),
            'sealed': seal is not None,
            'seal_created_at': seal.created_at if seal else None,
            'daily_count': len(_daily(db, plan.id)),
            'spillover_count': len(_spillovers(db, plan.id)),
            'run_count': len([1 for r in db.scalars(select(PilotRun.id).where(PilotRun.plan_id == plan.id))]),
            'current_run_id': current_run.id if current_run else None,
        })
    return plans


def create(db, data, user):
    name = data.name.strip()
    city = data.treated_city.strip()
    if not city:
        raise HTTPException(422, '试验城不能为空')
    if db.scalar(select(PilotPlan).where(PilotPlan.name == name)):
        raise HTTPException(409, '试投计划名称已存在')
    plan = PilotPlan(
        name=name, treated_city=city, launch_date=data.launch_date,
        description=data.description, revision=1, sealed_at=None,
        created_by=user.email, created_at=now(),
    )
    db.add(plan); db.flush()
    log(db, user, 'pilot.plan.create', f'{plan.id}/{name}')
    db.commit()
    return record(plan)


def detail(db, plan_id):
    plan = _plan_or_404(db, plan_id)
    seal = _seal(db, plan_id)
    seal_data = None
    if seal:
        seal_data = {
            'weights': seal.weights,
            'metrics': seal.metrics,
            'pre_dates': seal.pre_dates,
            'pre_start': seal.pre_start,
            'pre_end': seal.pre_end,
            'input_sha256': seal.input_sha256,
            'created_by': seal.created_by,
            'created_at': seal.created_at,
        }
    runs = [_run_record(db, r, plan) for r in db.scalars(
        select(PilotRun).where(PilotRun.plan_id == plan_id).order_by(PilotRun.id.desc())
    )]
    daily = _daily(db, plan_id)
    pre_days = sorted({r['date'] for r in daily if r['date'] < plan.launch_date})
    post_days = sorted({r['date'] for r in daily if r['date'] >= plan.launch_date})
    return {
        **record(plan),
        'sealed': seal_data is not None,
        'seal': seal_data,
        'daily': daily,
        'pre_days': pre_days,
        'post_days': post_days,
        'spillovers': _spillovers(db, plan_id),
        'runs': runs,
    }


def save_daily(db, plan_id, data, user):
    plan = _lock_plan(db, plan_id)
    city = data.city.strip()
    if not city:
        raise HTTPException(422, '城市不能为空')
    is_post = data.date >= plan.launch_date
    if is_post and not plan.sealed_at:
        raise HTTPException(409, '投放后数据只在对照权重封存成功后才能接收；请先封存权重')
    if not is_post and plan.sealed_at:
        raise HTTPException(409, '投放前数据已用于封存，不能再修改；如需新口径请新建试投计划')
    if is_post and plan.sealed_at:
        seal_row = _seal(db, plan_id)
        # 封存时参与拟合的对照城市都继续收数；零权重城市不进入基线，但记录可留档。
        allowed = set((seal_row.weights or {}).keys()) | {plan.treated_city}
        if city not in allowed:
            raise HTTPException(
                422,
                f'{city} 不在封存的对照城市或试验城中（可录入：'
                + '、'.join(sorted(allowed)) + '），请核对城市名称；新增对照需新建试投计划并重新封存',
            )

    existing = db.scalar(select(PilotDaily).where(
        PilotDaily.plan_id == plan_id, PilotDaily.city == city, PilotDaily.date == data.date,
    ).with_for_update())
    if existing:
        if existing.impressions == data.impressions and existing.clicks == data.clicks:
            # 重复提交同一数值不是更正，不推进版本、不使在途结果失效。
            return record(existing)
        existing.impressions = data.impressions
        existing.clicks = data.clicks
        existing.updated_at = now()
        row = existing
        action = 'pilot.daily.update'
    else:
        row = PilotDaily(
            plan_id=plan_id, city=city, date=data.date, impressions=data.impressions,
            clicks=data.clicks, created_by=user.email, created_at=now(), updated_at=now(),
        )
        db.add(row); db.flush()
        action = 'pilot.daily.create'
    _advance(db, plan, user, action, f'{plan_id}/{city}/{data.date}')
    db.commit()
    return record(row)


def delete_daily(db, plan_id, row_id, user):
    plan = _lock_plan(db, plan_id)
    row = db.get(PilotDaily, row_id)
    if not row or row.plan_id != plan_id:
        raise HTTPException(404, '日报记录不存在')
    if row.date < plan.launch_date and plan.sealed_at:
        raise HTTPException(409, '投放前数据已用于封存，不能删除')
    if row.date >= plan.launch_date and not plan.sealed_at:
        raise HTTPException(409, '投放后数据尚未封存，不能存在此类记录')
    city, date = row.city, row.date
    db.delete(row)
    _advance(db, plan, user, 'pilot.daily.delete', f'{plan_id}/{city}/{date}')
    db.commit()
    return {'deleted': True}


def seal(db, plan_id, user):
    plan = _lock_plan(db, plan_id)
    if plan.sealed_at or _seal(db, plan_id):
        raise HTTPException(409, '对照权重已封存，不能重新拟合或改配')
    daily = _daily(db, plan_id)
    if any(r['date'] >= plan.launch_date for r in daily):
        raise HTTPException(409, '发现投放后日报；封存只用投放前数据，请先核对计划投放首日')
    spill = _spillovers(db, plan_id)
    try:
        fit = pilot_algorithm.fit_weights(daily, plan.treated_city, plan.launch_date, spill)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    snapshot = {
        'plan_id': plan.id,
        'treated_city': plan.treated_city,
        'launch_date': plan.launch_date,
        'weights': fit['weights'],
        'pre_dates': fit['pre_dates'],
        'pre_start': fit['pre_start'],
        'pre_end': fit['pre_end'],
        # 冻结实际参与拟合的投放前日报，使权重与 SHA256 可复核（不改写历史快照）。
        'pre_daily': [
            {k: r[k] for k in ('city', 'date', 'impressions', 'clicks')}
            for r in daily if r['date'] < plan.launch_date
        ],
    }
    seal_row = PilotSeal(
        plan_id=plan.id, weights=fit['weights'],
        metrics=fit['metrics'] | {'投放前试验城点击率': fit['treated_pre_rate']},
        pre_dates=fit['pre_dates'], pre_start=fit['pre_start'], pre_end=fit['pre_end'],
        input_sha256=checksum(snapshot), snapshot=snapshot,
        created_by=user.email, created_at=now(),
    )
    db.add(seal_row)
    # 先记审计再置封存标记：封存动作本身不推进版本（此前也无法提交核算）。
    _advance(db, plan, user, 'pilot.seal', f'{plan_id}/{fit["pre_start"]}~{fit["pre_end"]}/{len(fit["weights"])}城')
    plan.sealed_at = now()
    db.commit()
    return detail(db, plan_id)


def add_spillover(db, plan_id, data, user):
    plan = _lock_plan(db, plan_id)
    city = data.city.strip()
    if city == plan.treated_city:
        raise HTTPException(422, '试验城本身不登记为串投对照；请确认城市名称')
    known = {r['city'] for r in _daily(db, plan_id)}
    if city not in known:
        raise HTTPException(422, f'{city} 尚无任何日报记录，请先核对城市名称')
    if db.scalar(select(PilotSpillover).where(
        PilotSpillover.plan_id == plan_id, PilotSpillover.city == city,
        PilotSpillover.actual_start_date == data.actual_start_date,
    )):
        raise HTTPException(409, '该城市与此开始日的串投记录已存在')
    # 已封存权重时，登记更早的开始日会改变哪些投放后日期失效，必须推进版本。
    if plan.sealed_at and any(
        item['city'] == city and item['actual_start_date'] <= data.actual_start_date
        for item in _spillovers(db, plan_id)
    ):
        raise HTTPException(409, '该城市已有不晚于此开始日的串投记录，无需重复登记')
    row = PilotSpillover(
        plan_id=plan_id, city=city, actual_start_date=data.actual_start_date,
        note=data.note, created_by=user.email, created_at=now(),
    )
    db.add(row); db.flush()
    _advance(db, plan, user, 'pilot.spillover', f'{plan_id}/{city}/{data.actual_start_date}')
    db.commit()
    return record(row)


def _snapshot(db, plan, seal):
    return {
        'plan_id': plan.id,
        'name': plan.name,
        'treated_city': plan.treated_city,
        'launch_date': plan.launch_date,
        'revision': plan.revision,
        'seal': {
            'weights': seal.weights,
            'metrics': seal.metrics,
            'pre_start': seal.pre_start,
            'pre_end': seal.pre_end,
            'input_sha256': seal.input_sha256,
        },
        'daily': [
            {k: row[k] for k in ('city', 'date', 'impressions', 'clicks')}
            for row in _daily(db, plan.id)
        ],
        'spillovers': [
            {k: row[k] for k in ('city', 'actual_start_date', 'note')}
            for row in _spillovers(db, plan.id)
        ],
    }


def create_run(db, plan_id, data, user):
    plan = _lock_plan(db, plan_id)
    seal_row = _seal(db, plan_id)
    if not plan.sealed_at or not seal_row:
        raise HTTPException(409, '请先用投放前数据封存对照权重，再提交增量核算')
    daily = _daily(db, plan_id)
    if not any(r['city'] == plan.treated_city and r['date'] >= plan.launch_date for r in daily):
        raise HTTPException(422, '投放后尚无试验城日报，无法核算增量')
    snapshot = _snapshot(db, plan, seal_row)
    digest = checksum(snapshot)
    run = PilotRun(
        plan_id=plan_id, name=data.name.strip(), status='queued',
        input_revision=plan.revision, snapshot=snapshot, checksum=digest,
        created_by=user.email, created_at=now(),
    )
    db.add(run); db.flush()
    log(db, user, 'pilot.run.queue', f'{run.id}/plan{plan_id}/rev{plan.revision}')
    db.commit()
    Redis.from_url(os.environ['REDIS_URL']).rpush(QUEUE, run.id)
    return _run_record(db, run, plan)


def get_run(db, run_id):
    run = db.get(PilotRun, run_id)
    if not run:
        raise HTTPException(404, '核算运行不存在')
    return _run_record(db, run)


def list_runs(db, plan_id):
    _plan_or_404(db, plan_id)
    return [_run_record(db, r) for r in db.scalars(
        select(PilotRun).where(PilotRun.plan_id == plan_id).order_by(PilotRun.id.desc())
    )]


def current(db, plan_id):
    plan = _plan_or_404(db, plan_id)
    run = db.scalar(select(PilotRun).where(
        PilotRun.plan_id == plan_id, PilotRun.status == 'completed',
        PilotRun.input_revision == plan.revision,
    ).order_by(PilotRun.id.desc()))
    if not run:
        return {'current': None, 'revision': plan.revision}
    return {'current': _run_record(db, run, plan), 'revision': plan.revision}


def export(db, run_id, user):
    run = db.get(PilotRun, run_id)
    if not run:
        raise HTTPException(404, '核算运行不存在')
    if not run.result:
        raise HTTPException(409, '尚无可用结果')
    snapshot = run.snapshot
    result = run.result
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['运行编号', '试投计划', '试验城', '投放首日', '输入版本', '当前计划版本',
                     '状态', '输入校验SHA256', '指标', '值'])
    base = [run.id, snapshot.get('name'), snapshot.get('treated_city'), snapshot.get('launch_date'),
            run.input_revision, run.plan_id and db.get(PilotPlan, run.plan_id).revision,
            run.status, run.checksum]
    for key, value in result['metrics'].items():
        writer.writerow(base + [key, value])
    writer.writerow([])
    writer.writerow(['封存对照权重'])
    writer.writerow(['城市', '权重'])
    for item in result.get('seal_weights', []):
        writer.writerow([item['city'], item['weight']])
    writer.writerow([])
    writer.writerow(result['columns'])
    for row in result['rows']:
        writer.writerow(row)
    writer.writerow([])
    writer.writerow(['受影响城市', '原因', '首日', '末日', '天数', '封存权重'])
    for item in result.get('affected_cities', []):
        writer.writerow([item['city'], item['reasons'], item['first_date'], item['last_date'],
                         item['days'], item['sealed_weight']])
    writer.writerow([])
    writer.writerow(['解释', result['interpretation']])
    writer.writerow(['边界', result['caveat']])
    log(db, user, 'pilot.run.export', run_id)
    db.commit()
    return '﻿' + stream.getvalue()
