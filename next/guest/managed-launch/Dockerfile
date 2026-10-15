FROM ghcr.io/humanitylabs-org/hermes-agent:v2026.9.24-wizard-slim1
USER root
COPY launch-guard.c install.py /opt/wizard-managed/
RUN /usr/bin/python3 /opt/wizard-managed/install.py
LABEL ai.wizards.managed-launch="1" ai.wizards.stock-revision="f97608f178d1ffeca59860195ab7da295f7c8e5f"
