FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 app && mkdir /data && chown app /data
COPY --chown=app:app server.py pgstore.py supabase-schema.sql app.js *.html *.css ./
COPY --chown=app:app assets ./assets
USER app
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
