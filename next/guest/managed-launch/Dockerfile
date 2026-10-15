FROM ghcr.io/humanitylabs-org/hermes-agent:v2026.9.24-wizard-slim1 AS compiler
USER root
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev
COPY launch-guard.c install.py /opt/wizard-managed/
RUN /usr/bin/python3 /opt/wizard-managed/install.py

FROM ghcr.io/humanitylabs-org/hermes-agent:v2026.9.24-wizard-slim1
COPY --from=compiler /opt/wizard-managed/ /opt/wizard-managed/
COPY control.py entrypoint.sh /opt/wizard-managed/
ENTRYPOINT ["/bin/sh", "/opt/wizard-managed/entrypoint.sh"]
COPY --from=compiler /usr/bin/python3.13 /usr/bin/python3.13
COPY --from=compiler /opt/uv-python/cpython-3.13.13-linux-aarch64-gnu/bin/python3.13 /opt/uv-python/cpython-3.13.13-linux-aarch64-gnu/bin/python3.13
LABEL ai.wizards.managed-launch="1" ai.wizards.stock-revision="f97608f178d1ffeca59860195ab7da295f7c8e5f"
