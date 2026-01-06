# Procfile
web: uvicorn app.main:app --host 0.0.0.0 --port 10000 --workers 2
worker: celery -A app.tasks.celery_app worker --loglevel=info
