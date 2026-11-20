import json
import numpy as np
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.config.domain import DOMAIN
from src.models.user import User
from src.models.study import Study
from src.models.observation import Observation
from src.models.pilot import PilotPlan, PilotDaily, PilotSeal
from src.models import run,review,audit
from src.utils.security import hash_password

PILOT_NAME='榆灯·单城试投·冬季主城'
PILOT_TREATED='主城'
PILOT_LAUNCH='2026-12-01'
PILOT_CONTROLS=['东城','西城','南城','北城']


def seed_pilot(db, rng):
    """合成一座试验城与四座对照城的逐城日报。

    只写投放前数据与计划；对照权重留给分析师在页面上封存，
    避免把“封存”这一人工决定伪造进种子数据。
    """
    if db.scalar(select(PilotPlan).where(PilotPlan.name==PILOT_NAME)): return
    plan=PilotPlan(name=PILOT_NAME,treated_city=PILOT_TREATED,launch_date=PILOT_LAUNCH,
                   description='单城试投 / 合成逐城日报 / 仅用于方法与流程演示',revision=1,
                   created_by='system@demo.local',created_at='2026-11-30T00:00:00+00:00')
    db.add(plan);db.flush()
    base={PILOT_TREATED:.20,'东城':.175,'西城':.225,'南城':.19,'北城':.21}
    for d in range(1,15):
        date=f'2026-11-{d:02d}'
        for n,city in enumerate([PILOT_TREATED]+PILOT_CONTROLS):
            rate=base[city]+float(rng.normal(0,.004))
            impressions=12000+n*800
            db.add(PilotDaily(plan_id=plan.id,city=city,date=date,impressions=impressions,
                              clicks=int(round(rate*impressions)),created_by='system@demo.local',
                              created_at='2026-11-30T00:00:00+00:00',updated_at='2026-11-30T00:00:00+00:00'))

def seed():
    Base.metadata.create_all(engine)
    rng=np.random.default_rng(42)
    i=DOMAIN['index']
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)): db.add(User(email=email,role=role,password_hash=hash_password('Research2026!')))
        for k,name in enumerate(DOMAIN['names']):
            study=db.scalar(select(Study).where(Study.name==name))
            if not study:
                study=Study(name=name,source_filename=DOMAIN['slug']+f'-202611-{k+1}.csv',description='独立合成业务观测 / 固定种子42 / 仅用于方法与流程演示');db.add(study);db.flush()
            rows=[]
            if i==0:
                for n in range(120): rows.append({'moisture':round(float(np.clip(rng.normal(5.2+k*.7,.7),0,100)),3),'extract':round(float(np.clip(rng.normal(34+k*2,2.4),0,100)),3)})
            elif i==1:
                rows=[{'group':'A','success':87+k*2,'failure':13-k*2},{'group':'B','success':96-k,'failure':4+k}]
            elif i==2:
                for n in range(24):
                    b=float(rng.uniform(3,6));rows.append({'before':round(b,3),'after':round(max(.1,b+rng.normal(-.45+k*.3,.5)),3)})
            elif i==3:
                for n in range(90):
                    x=round(float(rng.uniform(4,28)),1);rows.append({'porosity':x,'absorption':round(max(0,x*(.18+k*.08)+rng.normal(0,1.5)),2)})
            else: rows=[{'p0':.08+k*.02,'p1':.1+k*.025,'cost_per_contact':.12+k*.04,'budget':3000+k*500}]
            for n,values in enumerate(rows):
                key=f'DEMO-{k+1}-{n+1:04}'
                if not db.scalar(select(Observation.id).where(Observation.study_id==study.id,Observation.source_key==key)):
                    db.add(Observation(study_id=study.id,source_key=key,values=values))
        seed_pilot(db,rng)
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (User,Study,Observation,PilotPlan,PilotDaily)}
        print(json.dumps(counts));return counts
if __name__=='__main__': seed()
