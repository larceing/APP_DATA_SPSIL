FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput
RUN chmod +x docker-entrypoint.sh

EXPOSE 8010
CMD ["./docker-entrypoint.sh"]
