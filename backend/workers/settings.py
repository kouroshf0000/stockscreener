from arq.connections import RedisSettings
from arq.cron import cron

from backend.app.config import get_settings
from backend.workers.jobs import nightly_hunt, valuate_one


def _redis_settings() -> RedisSettings:
    url = get_settings().redis_url
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    redis_settings = _redis_settings()
    functions = [nightly_hunt, valuate_one]
    cron_jobs = [cron(nightly_hunt, hour=6, minute=0, run_at_startup=False)]
    max_jobs = 4
    job_timeout = 900
    keep_result = 86_400
