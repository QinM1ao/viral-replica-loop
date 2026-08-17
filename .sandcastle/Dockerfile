FROM node:22-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
  ca-certificates \
  git \
  curl \
  ffmpeg \
  jq \
  python3 \
  python3-httpx \
  python3-opencv \
  python3-pil \
  python3-yaml \
  ripgrep \
  && rm -rf /var/lib/apt/lists/*

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# Rename the base image's "node" user to "agent" and align UID/GID.
RUN groupmod -o -g $AGENT_GID node && usermod -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m -l agent node

# Install Codex CLI (run as root before USER agent)
RUN npm install -g @openai/codex@0.146.0

# Prepare the exact writable Codex directories used for session capture. The
# auth file and Plugin Creator skill are mounted read-only at runtime.
RUN mkdir -p /home/agent/.codex/sessions /home/agent/.codex/skills \
  && chown -R ${AGENT_UID}:${AGENT_GID} /home/agent/.codex

USER ${AGENT_UID}:${AGENT_GID}

WORKDIR /home/agent

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
