"""ROM-backed operator settings contract; all comparisons stay in memory."""
from pathlib import Path
import importlib.util
import json
import os

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("operator_quality", ROOT / "tools/quality/run.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def main():
    sources = ["native/tests/mk5_operator_settings_tests.cpp"] + [
        "native/src/" + name + ".cpp" for name in
        ("mk5_program", "mk5_task_body", "mk5_irq", "mk5_live_video")]
    dependencies = sources + ["native/include/mk5_operator_settings.hpp",
                              "tools/mk1/partitions.json", "tools/mk1/generate.py"]
    result = {"passed": False, "scope": "ROM-backed operator parameters and ranking preservation",
              "source_sha256": {name: quality.sha(ROOT / name) for name in dependencies}}
    cleanup = {}
    try:
        with quality.scratch_tree() as (scratch, cleanup):
            executable = scratch / "operator-settings.exe"
            environment = {"PATH": str(quality.DEFAULT_CC.parent) + os.pathsep + os.environ["PATH"]}
            arguments = [str(quality.DEFAULT_CC), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                         "-DMKOPERATOR_ORACLE", "-municode", "-I" + str(ROOT / "native/include"),
                         *[str(ROOT / source) for source in sources], "-lbcrypt", "-luser32", "-lgdi32",
                         "-o", str(executable)]
            compiled = quality.command(arguments, scratch, timeout=180, env=environment, cwd=ROOT)
            result["compile"] = quality.compact(compiled)
            if not compiled["passed"]:
                raise RuntimeError("operator contract compilation failed")
            tested = quality.command([str(executable), str(ROOT)], scratch, timeout=60, env=environment, cwd=ROOT)
            result["test"] = quality.compact(tested)
            result["passed"] = tested["passed"]
    except Exception as error:
        result["error"] = str(error)
    finally:
        result["cleanup"] = cleanup
        quality.STAGE.mkdir(parents=True, exist_ok=True)
        (quality.STAGE / "operator-settings.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("passed", "scope", "cleanup")}, indent=2))
    if not result["passed"]:
        print(json.dumps({key: result[key] for key in ("error", "compile", "test") if key in result}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
