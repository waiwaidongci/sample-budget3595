from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from src.config.database import get_db
from src.middlewares.auth import current_user, writer
from src.schemas.pilot import PilotPlanInput, PilotDailyInput, PilotSpilloverInput, PilotRunInput
from src.controllers import pilot

router = APIRouter(prefix='/pilot')


@router.get('/plans')
def plans(db=Depends(get_db), user=Depends(current_user)):
    return pilot.list_plans(db)


@router.post('/plans')
def create_plan(data: PilotPlanInput, db=Depends(get_db), user=Depends(writer)):
    return pilot.create_plan(db, data, user)


@router.get('/plans/{plan_id}')
def plan_detail(plan_id: int, db=Depends(get_db), user=Depends(current_user)):
    return pilot.plan_detail(db, plan_id)


@router.post('/plans/{plan_id}/daily')
def add_daily(plan_id: int, data: PilotDailyInput, db=Depends(get_db), user=Depends(writer)):
    return pilot.save_daily(db, plan_id, data, user)


@router.delete('/plans/{plan_id}/daily/{row_id}')
def remove_daily(plan_id: int, row_id: int, db=Depends(get_db), user=Depends(writer)):
    return pilot.delete_daily(db, plan_id, row_id, user)


@router.post('/plans/{plan_id}/seal')
def seal(plan_id: int, db=Depends(get_db), user=Depends(writer)):
    return pilot.seal(db, plan_id, user)


@router.post('/plans/{plan_id}/spillovers')
def add_spillover(plan_id: int, data: PilotSpilloverInput, db=Depends(get_db), user=Depends(writer)):
    return pilot.add_spillover(db, plan_id, data, user)


@router.get('/plans/{plan_id}/runs')
def runs(plan_id: int, db=Depends(get_db), user=Depends(current_user)):
    return pilot.list_runs(db, plan_id)


@router.post('/plans/{plan_id}/runs')
def create_run(plan_id: int, data: PilotRunInput, db=Depends(get_db), user=Depends(writer)):
    return pilot.create_run(db, plan_id, data, user)


@router.get('/plans/{plan_id}/current')
def current(plan_id: int, db=Depends(get_db), user=Depends(current_user)):
    return pilot.current(db, plan_id)


@router.get('/runs/{run_id}')
def get_run(run_id: int, db=Depends(get_db), user=Depends(current_user)):
    return pilot.get_run(db, run_id)


@router.get('/runs/{run_id}/export')
def export(run_id: int, db=Depends(get_db), user=Depends(current_user)):
    content = pilot.export(db, run_id, user)
    return Response(
        content=content.encode('utf-8'), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="pilot-{run_id}.csv"'},
    )
