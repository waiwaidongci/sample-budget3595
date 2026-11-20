from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, UniqueConstraint
from src.config.database import Base


class PilotPlan(Base):
    """单城试投计划。launch_date 为投放首日；此前为投放前，此后为投放后。"""
    __tablename__ = 'pilot_plans'
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    treated_city = Column(String(60), nullable=False)
    launch_date = Column(String(10), nullable=False)
    description = Column(Text, default='')
    revision = Column(Integer, nullable=False, default=1)
    sealed_at = Column(String(40), nullable=True)
    created_by = Column(String(120), nullable=False)
    created_at = Column(String(40), nullable=False)


class PilotDaily(Base):
    """逐城每日触达与点击。封存前只收投放前数据，封存后才收投放后数据。"""
    __tablename__ = 'pilot_daily'
    __table_args__ = (UniqueConstraint('plan_id', 'city', 'date'),)
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey('pilot_plans.id'), nullable=False)
    city = Column(String(60), nullable=False)
    date = Column(String(10), nullable=False)
    impressions = Column(Integer, nullable=False)
    clicks = Column(Integer, nullable=False)
    created_by = Column(String(120), nullable=False)
    created_at = Column(String(40), nullable=False)
    updated_at = Column(String(40), nullable=False)


class PilotSeal(Base):
    """用投放前数据拟合的对照权重封存件。一个计划只有一份，之后不可修改。"""
    __tablename__ = 'pilot_seals'
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey('pilot_plans.id'), unique=True, nullable=False)
    weights = Column(JSON, nullable=False)
    metrics = Column(JSON, nullable=False)
    pre_dates = Column(JSON, nullable=False)
    pre_start = Column(String(10), nullable=False)
    pre_end = Column(String(10), nullable=False)
    input_sha256 = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_by = Column(String(120), nullable=False)
    created_at = Column(String(40), nullable=False)


class PilotSpillover(Base):
    """迟到的串投记录：该城自 actual_start_date 起不能再作为对照。"""
    __tablename__ = 'pilot_spillovers'
    __table_args__ = (UniqueConstraint('plan_id', 'city', 'actual_start_date'),)
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey('pilot_plans.id'), nullable=False)
    city = Column(String(60), nullable=False)
    actual_start_date = Column(String(10), nullable=False)
    note = Column(Text, default='')
    created_by = Column(String(120), nullable=False)
    created_at = Column(String(40), nullable=False)


class PilotRun(Base):
    """一次增量核算。input_revision 记录快照时的计划版本；版本变化后的结果不得成为当前结论。"""
    __tablename__ = 'pilot_runs'
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey('pilot_plans.id'), nullable=False)
    name = Column(String(120), nullable=False)
    status = Column(String(20), default='queued')
    input_revision = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(Text, default='')
    superseded_reason = Column(Text, default='')
    created_by = Column(String(120), nullable=False)
    created_at = Column(String(40), nullable=False)
    completed_at = Column(String(40), nullable=True)
    superseded_at = Column(String(40), nullable=True)
