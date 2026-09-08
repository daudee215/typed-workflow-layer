# SLURM benchmark

`run_geoqa_benchmark.sh` is a real SLURM job-array entry point for HPC
experiments on the typed workflow layer. It runs the 204-test regression suite
once and evaluates search depths 1, 2, 3 and 4 as independent array tasks.

From the repository root on the cluster:

```bash
sbatch slurm/run_geoqa_benchmark.sh
squeue --me
sacct -j JOB_ID --format=JobID,State,Elapsed,AllocCPUS,MaxRSS
```

The script records the SLURM job and array IDs, host, Python version, Git
revision, dirty-tree state, test output, search statistics and elapsed time in
`results/slurm/JOB_ID_ARRAY_ID/`. The default `cpu_sapphire` partition follows
the HPC@PoliTO SLURM examples; override it with `sbatch --partition=...` when
the current account exposes a different CPU partition.

This benchmark currently runs the dependency-free rectangle/synthesis
prototype. It is not a claim that real PoliTO geospatial data has already been
processed; replace the benchmark input module with the approved real dataset
adapter before reporting real-data results.
