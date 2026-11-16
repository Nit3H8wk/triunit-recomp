"""Install the separate MSYS2 CLANG64 test toolchain; discard download cache."""
from pathlib import Path
import json
import run as quality

PACMAN = Path("C:/msys64/usr/bin/pacman.exe")
PACKAGES = ("mingw-w64-clang-x86_64-clang", "mingw-w64-clang-x86_64-compiler-rt")


def main():
    receipt = {"passed": False, "packages": list(PACKAGES),
               "installer_sha256": quality.sha(Path(__file__)),
               "product_compiler_changed": False}
    try:
        with quality.scratch_tree() as (scratch, cleanup):
            receipt["cleanup"] = cleanup
            cache = scratch / "packages"
            cache.mkdir()
            install = quality.command([PACMAN, "-S", "--needed", "--noconfirm",
                                       "--cachedir", cache.as_posix(), *PACKAGES],
                                      scratch, timeout=600)
            receipt["install"] = quality.compact(install)
            if install["passed"]:
                versions = quality.command([PACMAN, "-Q", *PACKAGES], scratch)
                receipt["installed_versions"] = quality.compact(versions)
                runtime = quality.ASAN_CC.parent / "libclang_rt.asan_dynamic-x86_64.dll"
                receipt["passed"] = (versions["passed"] and quality.ASAN_CC.is_file()
                                     and runtime.is_file())
                if receipt["passed"]:
                    receipt["compiler_sha256"] = quality.sha(quality.ASAN_CC)
                    receipt["runtime_sha256"] = quality.sha(runtime)
        receipt["passed"] = receipt["passed"] and cleanup.get("exists_after") is False
    except Exception as error:
        receipt.update(passed=False, error=repr(error))
    path = quality.STAGE / "asan-toolchain-install.json"
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise RuntimeError(f"Linked install receipt: {path}")
    if quality.STAGE.is_dir():
        # Retain the first successful download cleanup, including its byte count.
        if path.is_file():
            previous = json.loads(path.read_text(encoding="utf-8"))
            previous_cleanup = previous.get("download_cache_cleanup", previous.get("cleanup", {}))
            if previous_cleanup.get("exists_after") is False and previous_cleanup.get("bytes_removed", 0) > 0:
                receipt["download_cache_cleanup"] = previous_cleanup
        path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
