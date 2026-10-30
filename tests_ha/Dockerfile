# The real-Home-Assistant tier (tests_ha/) on any machine with Docker. Home Assistant only runs on
# Linux (it imports fcntl), so on Windows and macOS this is the way to run the tier locally. Test
# tooling only: nothing ships from this file. How to build and run it: docs/TESTING.md.
#
# The defaults are the production leg of the Real Home Assistant job in
# .github/workflows/ci-validate.yml (Home Assistant 2026.9 needs Python 3.14.2 or newer); the plugin pin
# is requirements-test-ha.txt, the same file that job installs. Move them together. The oldest
# supported leg is the same image built with the two build arguments that leg sets in that job
# (PYTHON and PLUGIN); docs/TESTING.md has the command.
ARG PYTHON=3.14.8
FROM python:${PYTHON}-slim-trixie

ARG PLUGIN="-r /tmp/requirements-test-ha.txt"
COPY requirements-test-ha.txt /tmp/requirements-test-ha.txt
RUN pip install --no-cache-dir -q ${PLUGIN} \
 && python -c "import platform; from homeassistant.const import __version__ as v; print('Python', platform.python_version(), 'Home Assistant', v)"

# The working tree arrives on stdin as a tar stream, not a bind mount, so the run sees exactly the
# files git would commit. Arguments go to pytest; the default runs the whole tier.
WORKDIR /repo
ENTRYPOINT ["sh", "-c", "tar -x -C /repo && exec python -m pytest \"$@\"", "--"]
CMD ["tests_ha", "-q"]
