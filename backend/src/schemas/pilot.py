from datetime import date as date_type
from pydantic import BaseModel, Field, field_validator


def _valid_date(value: str, label: str) -> str:
    try:
        return date_type.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(label + '须为 YYYY-MM-DD 格式的有效日期')


class PilotPlanInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    treated_city: str = Field(min_length=1, max_length=60)
    launch_date: str
    description: str = Field(default='', max_length=2000)

    @field_validator('launch_date')
    @classmethod
    def check_launch(cls, value):
        return _valid_date(value, '投放首日')


class PilotDailyInput(BaseModel):
    city: str = Field(min_length=1, max_length=60)
    date: str
    impressions: int = Field(ge=1, le=100000000)
    clicks: int = Field(ge=0, le=100000000)

    @field_validator('date')
    @classmethod
    def check_date(cls, value):
        return _valid_date(value, '日期')

    @field_validator('clicks')
    @classmethod
    def check_clicks(cls, value, info):
        impressions = info.data.get('impressions')
        if impressions is not None and value > impressions:
            raise ValueError('点击数不得超过触达数')
        return value


class PilotSpilloverInput(BaseModel):
    city: str = Field(min_length=1, max_length=60)
    actual_start_date: str
    note: str = Field(default='', max_length=2000)

    @field_validator('actual_start_date')
    @classmethod
    def check_start(cls, value):
        return _valid_date(value, '实际开始日')


class PilotRunInput(BaseModel):
    name: str = Field(default='单城增量核算', min_length=2, max_length=120)
