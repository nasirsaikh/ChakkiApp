FROM node:22-alpine AS assets
WORKDIR /app
COPY package.json ./
COPY static_src ./static_src
COPY static ./static
COPY templates ./templates
COPY apps ./apps
RUN npm install --no-audit --no-fund
RUN npm run build:css

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=assets /app/static/css/app.css /app/static/css/app.css
RUN python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "chakki_erp.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
