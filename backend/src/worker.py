import os,time,json,logging
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from src.config.database import Session
from src.models.run import Run
from src.models.pilot import PilotPlan, PilotRun
from src.models import user,study,observation,review,audit
from src.services.algorithm import calculate
from src.services import pilot_algorithm
from src.utils.serializers import checksum,now
ARTIFACTS=Path(os.environ.get('ARTIFACTS_DIR','/app/artifacts'))


def budget_job(id):
    with Session() as db:
        run=db.get(Run,id)
        if not run or run.status in ('completed','failed'): return
        run.status='running';db.commit()
        try:
            if checksum(run.snapshot)!=run.checksum: raise ValueError('输入快照校验失败')
            result=calculate(run.snapshot,run.parameters)
            result['input_sha256']=run.checksum
            run.result=result;run.status='completed'
            (ARTIFACTS/f'run-{id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
        except Exception as e:
            logging.exception('analysis failed');run.status='failed';run.error=str(e)
        db.commit()


def pilot_job(id):
    """计算一次单城增量。

    先无锁计算，再用短事务按“计划行 → 运行行”的固定顺序落库（与接口一致，避免死锁）。
    落库时若计划版本已前进，结果仍保留可查，但状态标为 superseded，不得作为当前结论。
    """
    with Session() as db:
        run = db.scalar(select(PilotRun).where(PilotRun.id == id).with_for_update())
        if not run or run.status not in ('queued', 'running'):
            return
        snapshot, expected, plan_id, revision = run.snapshot, run.checksum, run.plan_id, run.input_revision
        run.status = 'running'
        db.commit()
    try:
        if checksum(snapshot) != expected:
            raise ValueError('输入快照校验失败')
        result = pilot_algorithm.compute(snapshot)
        result['input_sha256'] = expected
    except Exception as e:
        logging.exception('pilot analysis failed')
        with Session() as db:
            plan = db.scalar(select(PilotPlan).where(PilotPlan.id == plan_id).with_for_update())
            run = db.scalar(select(PilotRun).where(PilotRun.id == id).with_for_update())
            if run and run.status not in ('completed', 'superseded'):
                run.completed_at = now()
                if run.superseded_at:
                    # 计算期间计划已被更正：不把旧版本尝试标成业务失败，只留档为历史。
                    run.status = 'superseded'
                else:
                    run.status = 'failed'
                    run.error = str(e)
            db.commit()
        return

    with Session() as db:
        plan = db.scalar(select(PilotPlan).where(PilotPlan.id == plan_id).with_for_update())
        run = db.scalar(select(PilotRun).where(PilotRun.id == id).with_for_update())
        if not run or run.status in ('completed', 'failed'):
            return
        run.result = result
        run.completed_at = now()
        if plan is None:
            run.status = 'failed'
            run.error = '试投计划已被删除'
        elif run.status == 'superseded' or plan.revision != revision:
            run.status = 'superseded'
            run.superseded_reason = (
                f'计算完成时计划已更新到版本 {plan.revision}，此结果基于版本 {revision}，不得作为当前结论'
            )
            run.superseded_at = now()
        else:
            run.status = 'completed'
        db.commit()
        (ARTIFACTS / f'pilot-{id}.json').write_text(
            json.dumps(result, ensure_ascii=False, allow_nan=False)
        )


def recover():
    """把中断后仍排队或运行中的任务重新入队；单 worker 部署。"""
    with Session() as db:
        pending=list(db.scalars(select(Run).where(Run.status.in_(['queued','running']))))
        if pending: redis.rpush('analysis-queue',*[run.id for run in pending])
        pending_pilot=list(db.scalars(select(PilotRun).where(PilotRun.status.in_(['queued','running']))))
        if pending_pilot: redis.rpush('pilot-queue',*[run.id for run in pending_pilot])


def main():
    global redis
    redis=Redis.from_url(os.environ['REDIS_URL'])
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    recover()
    while True:
        Path('/tmp/worker-heartbeat').touch()
        job=redis.blpop(['analysis-queue','pilot-queue'],timeout=2)
        if not job: continue
        queue,payload=job
        id=int(payload)
        try:
            if queue==b'pilot-queue': pilot_job(id)
            else: budget_job(id)
        except Exception:
            logging.exception('job dispatch failed')


if __name__=='__main__':
    main()
