#!/bin/bash -l
# GPU benchmark job for Grid Engine schedulers (qsub). Submit from the repo root:
#
#   qsub infra/batch/sge_eval.sh
#   qsub -v MODEL=Qwen/Qwen2.5-7B-Instruct,REPEATS=5 infra/batch/sge_eval.sh
#
# GPU request syntax differs between clusters. "-l gpus=1" is common; others use
# "-l gpu=1" or a queue name (-q gpu). Check your cluster's documentation and edit the
# resource lines below. Settings: see infra/batch/run_eval.sh.
#
#$ -N flightpath-eval
#$ -cwd
#$ -j y
#$ -o benchmark-results/logs/$JOB_NAME.$JOB_ID.log
#$ -l h_rt=04:00:00
#$ -pe omp 4
#$ -l gpus=1

set -euo pipefail
# Load site modules if your cluster needs them, e.g. MODULES="python3/3.12 cuda/12.6".
for m in ${MODULES:-}; do module load "$m"; done
exec bash infra/batch/run_eval.sh
