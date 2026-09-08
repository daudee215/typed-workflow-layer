#!/usr/bin/env bash
#SBATCH --job-name=geoqa-benchmark
#SBATCH --partition=cpu_sapphire
#SBATCH --array=1-4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%A_%a.out
#SBATCH --error=slurm-%A_%a.err

# Submit from the repository root with:
#   sbatch slurm/run_geoqa_benchmark.sh
# The partition can be overridden at submission time if the account exposes a
# different CPU partition: sbatch --partition=<available-partition> ...

set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is not set}"
PYTHON_BIN="${GEOQA_PYTHON:-python3}"
RESULT_DIR="results/slurm/${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$RESULT_DIR"

{
    echo "slurm_job_id=${SLURM_JOB_ID}"
    echo "slurm_array_task_id=${SLURM_ARRAY_TASK_ID}"
    echo "slurm_job_name=${SLURM_JOB_NAME}"
    echo "slurm_submit_dir=${SLURM_SUBMIT_DIR}"
    echo "hostname=$(hostname)"
    echo "python=$($PYTHON_BIN --version 2>&1)"
    echo "git_revision=$(git rev-parse HEAD)"
    echo "git_dirty=$(if git diff --quiet; then echo false; else echo true; fi)"
    date -u +"started_utc=%Y-%m-%dT%H:%M:%SZ"
} | tee "$RESULT_DIR/run-metadata.txt"

# Run the full regression suite once, on the first array task. The other tasks
# are independent depth benchmarks and do not duplicate the expensive suite.
if [[ "$SLURM_ARRAY_TASK_ID" == "1" ]]; then
    srun --cpu-bind=cores "$PYTHON_BIN" -m unittest discover -s tests \
        2>&1 | tee "$RESULT_DIR/tests.txt"
fi

# Each array task measures one search depth. This is an embarrassingly parallel
# experiment: the tasks share no mutable state and write to separate folders.
export GEOQA_DEPTH="$SLURM_ARRAY_TASK_ID"
srun --cpu-bind=cores "$PYTHON_BIN" -c '
import json
import os
import time

import analysis
from synthesis import enumerate_workflows

depth = int(os.environ["GEOQA_DEPTH"])
started = time.perf_counter()
workflows = enumerate_workflows(
    analysis.SOURCES,
    analysis.TARGET,
    max_depth=depth,
    max_workflows=100000,
)
elapsed = time.perf_counter() - started
payload = {
    "depth": depth,
    "workflows": len(workflows),
    "candidates_examined": workflows.stats.candidates_examined,
    "type_checks": workflows.stats.type_checks,
    "truncated": workflows.stats.truncated,
    "elapsed_seconds": round(elapsed, 6),
}
with open(os.path.join(
    "results", "slurm",
    "{0}_{1}".format(os.environ["SLURM_JOB_ID"], os.environ["SLURM_ARRAY_TASK_ID"]),
    "depth-result.json",
), "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
print(json.dumps(payload, sort_keys=True))
' 2>&1 | tee "$RESULT_DIR/depth-benchmark.txt"

date -u +"finished_utc=%Y-%m-%dT%H:%M:%SZ" | tee -a "$RESULT_DIR/run-metadata.txt"
