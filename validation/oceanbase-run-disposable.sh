#!/usr/bin/env bash
# Run only on a disposable GitHub-hosted Linux runner after building observer.
set -euo pipefail
: "${GITHUB_ACTIONS:?This helper requires a disposable Actions runner}"
: "${RUNNER_TEMP:?}"
source_dir=$(realpath "${1:?Pass the compiled source directory}")
fixture_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
runtime_dir=$(mktemp -d "$RUNNER_TEMP/ob-grant.XXXXXX")
export _OBD_HOME="$runtime_dir/obd-state"
export OB_DO_NO_GLOBAL_CLUSTER=1
export LD_LIBRARY_PATH="$source_dir/deps/3rd/u01/obclient/lib:${LD_LIBRARY_PATH:-}"
mkdir -p "$_OBD_HOME"
df -h "$runtime_dir"
free -h
python3 - "$fixture_dir/oceanbase-runtime.yaml.in" "$runtime_dir" <<'PY'
import pathlib
import sys
template = pathlib.Path(sys.argv[1]).read_text()
runtime = pathlib.Path(sys.argv[2])
assert "'" not in str(runtime)
(runtime / "runtime.yaml").write_text(template.replace("@HOME_PATH@", str(runtime / "observer")))
PY
cd "$source_dir/tools/deploy"
# All OBD state and server files are unique to this job. Never use a saved cluster.
bash ./obd.sh deploy -c "$runtime_dir/runtime.yaml" -n grant-regression --cp -b "$source_dir/build_debug"
python3 "$fixture_dir/oceanbase-grant-runtime.py" \
  --client "$source_dir/deps/3rd/u01/obclient/bin/obclient" \
  --port 2881 --user root@sys --expected-limit 32
# Further old-compatibility/plugin/Oracle tests are separate publication gates.
