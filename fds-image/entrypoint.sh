#!/bin/bash
# Sets up the NIST bundle environment, then runs the given command.
#   docker run ... fds:6.10.1 mpiexec -n 8 fds model.fds
set -e
source /opt/fds/bin/FDS6VARS.sh
source /opt/fds/bin/SMV6VARS.sh
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
exec "$@"
