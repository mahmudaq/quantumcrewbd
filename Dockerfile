# QuantumCrewBD — production image
#
# Multi-stage: dependencies are built once into a wheel cache, then copied into
# a slim runtime. The app is Streamlit, so there is no build step for the
# front-end — but the requirements are heavy (crewai pulls in a lot), which is
# exactly why the dependency layer is separated from the source layer: editing
# app.py must not reinstall the world.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1 is required by the numerical stack (numpy/scipy via crewai).
# curl is kept for the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --------------------------------------------------------------------------- #
FROM base AS deps

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# --------------------------------------------------------------------------- #
FROM base AS runtime

COPY --from=deps /install /usr/local

# Source last: this layer changes most often, everything above stays cached.
# Every top-level package the app imports must be listed here — a missing COPY
# produces an ImportError at request time, not at build time, so the container
# still reports healthy.
COPY app.py ./
COPY auth/ ./auth/
COPY llm/ ./llm/
COPY agents/ ./agents/
COPY models/ ./models/
COPY parsing/ ./parsing/
COPY orchestration/ ./orchestration/
COPY database/ ./database/
COPY tools.py ./

# Run as a non-root user. The app holds tenant API keys in memory, so it should
# not also be able to write to its own code.
RUN useradd --create-home --uid 10001 app \
 && chown -R app:app /app
USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# Secrets come from the environment at run time (see .env.example). Never
# bake them into the image.
CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
