#!/usr/bin/env python
import os
from app.tasks import celery_app

if __name__ == "__main__":
    # 启动Celery worker
    celery_app.start()
