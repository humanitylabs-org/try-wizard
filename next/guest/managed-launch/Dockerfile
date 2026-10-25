ARG HERMES_IMAGE
FROM ${HERMES_IMAGE} AS compiler
USER root
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev
COPY launch-guard.c install.py /opt/wizard-managed/
RUN /usr/bin/python3 /opt/wizard-managed/install.py

FROM ${HERMES_IMAGE}
ARG HERMES_IMAGE
COPY --from=compiler /opt/wizard-managed/ /opt/wizard-managed/
COPY control.py entrypoint.sh /opt/wizard-managed/
ENTRYPOINT ["/bin/sh", "/opt/wizard-managed/entrypoint.sh"]
# install.py discovers the base's real interpreter targets, including venv aliases.
# Copy every guarded target, not an assumed Python version or uv layout.
COPY --from=compiler /opt/wizard-managed/interpreter-overlay/ /
LABEL ai.wizards.managed-launch="1" ai.wizards.stock-image="${HERMES_IMAGE}"
