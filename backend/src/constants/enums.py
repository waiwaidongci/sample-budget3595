ROLES=('admin','analyst','viewer')
STATES=('queued','running','completed','failed')
# 单城试投的运行在输入被更正后保留可查，但不能作为当前结论发布。
PILOT_STATES=('queued','running','completed','failed','superseded')
