#!/bin/bash
# GPU benchmark job for Slurm (sbatch). Submit from the repo root:
#
#   sbatch infra/batch/slurm_eval.sh
#   MODEL=Qwen/Qwen2.5-7B-Instruct REPEATS=5 sbatch --export=ALL infra/batch/slurm_eval.sh
#
# Edit the partition/account lines for your cluster. Settings: see run_eval.sh.
#
#SBATCH --job-name=flightpath-eval
#SBATCH --output=benchmark-results/logs/%x.%j.log
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
##SBATCH --partition=gpu
##SBATCH --account=your-account

set -euo pipefail
for m in ${MODULES:-}; do module load "$m"; done
exec bash infra/batch/run_eval.sh
