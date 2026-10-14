# EvidenceForge sample scenario

These synthetic logs were generated from `scenarios/stalk-branch.yaml` with EvidenceForge v1.0.0 (commit `12f385051c1cb80c8401f825f61eb243553e4eca`). That release derives stable random streams from the scenario and does not expose a separate seed option.

```sh
uv run --project /path/to/EvidenceForge@v1.0.0 \
  eforge generate scenarios/stalk-branch.yaml \
  --output /tmp/stalk-branch --force
```

The three log files are copied from the generated bundle and flattened for the application manifest. `GROUND_TRUTH.md` and `OBSERVATION_MANIFEST.json` are unchanged generator outputs. All records are synthetic.
