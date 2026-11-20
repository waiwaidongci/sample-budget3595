from src.services import pilot


def list_plans(db):
    return {'plans': pilot.list_plans(db)}


def create_plan(db, data, user):
    return pilot.create(db, data, user)


def plan_detail(db, plan_id):
    return pilot.detail(db, plan_id)


def save_daily(db, plan_id, data, user):
    return pilot.save_daily(db, plan_id, data, user)


def delete_daily(db, plan_id, row_id, user):
    return pilot.delete_daily(db, plan_id, row_id, user)


def seal(db, plan_id, user):
    return pilot.seal(db, plan_id, user)


def add_spillover(db, plan_id, data, user):
    return pilot.add_spillover(db, plan_id, data, user)


def create_run(db, plan_id, data, user):
    return pilot.create_run(db, plan_id, data, user)


def list_runs(db, plan_id):
    return {'runs': pilot.list_runs(db, plan_id)}


def get_run(db, run_id):
    return pilot.get_run(db, run_id)


def current(db, plan_id):
    return pilot.current(db, plan_id)


def export(db, run_id, user):
    return pilot.export(db, run_id, user)
