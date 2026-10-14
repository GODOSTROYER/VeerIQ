# Collect the full reliability cohort across quota windows

The target remains 20 trials for each briefing (`task_only`, `with_rules`) per model: 40 trials for the default model. Small invocations do not reduce that target. Partial results are provisional, with requested, recorded and pending counts; completion rates describe observed trials only until the full cohort is complete.

From the repository root, start a bounded invocation:

```sh
python tasks.py eval-reliability --trials 20 --models openai/gpt-oss-120b \
  --briefings task_only,with_rules --timeout 180 \
  --max-trials-per-invocation 3 --stop-on-rate-limit \
  --out "$PWD/evidence/reliability-20261013T175457Z.json"
```

After the provider has enough quota, continue the same artifact:

```sh
python tasks.py eval-reliability --trials 20 --models openai/gpt-oss-120b \
  --briefings task_only,with_rules --timeout 180 \
  --max-trials-per-invocation 3 --stop-on-rate-limit \
  --resume "$PWD/evidence/reliability-20261013T175457Z.json"
```

The current post-fix collection has one recorded trial and 39 pending. The earlier six-trial artifact `reliability-20261013T172610Z.json` is a pre-fix diagnostic; do not resume or pool it with this collection. No recurring schedule has been created, as requested. The first command is a template for a new collection; choose a new filename rather than overwriting the existing artifact. For a new collection, choose a new UTC-stamped filename; never overwrite completed evidence. Resume requires matching models, briefings, trial target and evaluator checksum. Keep the fixture, planner and deployment configuration unchanged during collection and retain timestamps for all trials. Comparing different daily windows can introduce provider/environment variation; report the collection window alongside the rates.

A provider-rate-limit attempt is recorded as a failure, not removed or replaced. Remaining unstarted trials stay pending. Interrupted attempts are retained separately with unknown safety evidence; their history prevents a blanket zero-effects claim. The same isolated database, grant, full poisoned observation and dispatcher path are used. No preview database reset or authority expansion is permitted.

The post-fix trial used 28,064 tokens. Three trials may consume roughly 84,000 tokens, with substantial variation; this is not a guarantee of available capacity. Invocation bounds and stop-on-rate-limit prevent an exhausted quota from triggering the entire pending cohort. No recurring run is scheduled without user authorization.
