# Dockerfile.kid — image used by EloPhanto kid agents.
#
# A kid is a sandboxed child EloPhanto instance running inside a
# container with hardened defaults (cap-drop=ALL, read-only rootfs,
# non-root uid 10001). The codebase is BAKED IN at build time — we
# don't bind-mount it from the host, by design (see KID_AGENTS_PLAN.md
# isolation rules).
#
# Build:  elophanto kid build
# Or:     docker build -f Dockerfile.kid -t elophanto-kid:latest .

FROM python:3.12-slim

# System tools the kid is allowed to use during sandbox tasks. Add
# sparingly — every package here is part of the kid's attack surface.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. Matches KidConfig.run_as_uid default.
RUN groupadd -g 10001 kid && useradd -u 10001 -g 10001 -m -d /home/kid kid

# /workspace is the named-volume mount point. We pre-create it with
# kid ownership so the read-only rootfs doesn't block writes.
RUN mkdir -p /workspace && chown 10001:10001 /workspace

# Copy the EloPhanto source tree into the image.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY core ./core
COPY tools ./tools
COPY channels ./channels
COPY cli ./cli
COPY plugins ./plugins
COPY skills ./skills
COPY knowledge ./knowledge

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

USER 10001:10001
WORKDIR /workspace

# The kid runs through core.kid_bootstrap, which:
#   1. Reads + clears KID_VAULT_JSON env (bounds plaintext exposure window)
#   2. Builds a minimal Config with the scoped vault keys mapped to providers
#   3. Constructs an Agent (ELOPHANTO_KID=true triggers registry tool-strip
#      + planner <kid_self> block injection)
#   4. Connects to parent's gateway as a client and processes
#      CHILD_TASK_ASSIGNED events through the agent loop
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "core.kid_bootstrap"]
